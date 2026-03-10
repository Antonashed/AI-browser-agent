"""CLI entry point: load config → start MCP → run agent loop with Rich UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from agent.cli import CLI
from agent.config import load_config
from agent.context import ContextManager
from agent.core import AgentLoop
from agent.llm_client import LLMClient
from agent.mcp_client import MCPClient
from agent.memory import Memory
from agent.tool_executor import ToolExecutor
from agent.tools import merge_tools

METRICS_LOG_PATH = Path("session_metrics.jsonl")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cli = CLI()
    config = load_config()
    memory = Memory(load_env_defaults=True)

    mcp = MCPClient()

    # Build MCP server args
    mcp_args = [config.mcp_browser_args]

    if config.cdp_endpoint:
        mcp_args.append(f"--cdp-endpoint={config.cdp_endpoint}")
        cli.print_connecting("cdp", config.cdp_endpoint)
    else:
        if config.browser_headless:
            mcp_args.append("--headless")
        mcp_args.append(f"--viewport-size={config.browser_viewport_width},{config.browser_viewport_height}")
        if config.browser_storage_path:
            storage = config.browser_storage_path
            if os.path.exists(storage):
                mcp_args.append(f"--storage-state={storage}")
            mcp_args.append(f"--save-storage={storage}")
        cli.print_connecting(f"headless={config.browser_headless}")

    cli.print_status("Запускаю MCP-сервер (Playwright)…")
    try:
        await mcp.start(config.mcp_browser_command, mcp_args)
    except Exception as exc:
        if config.cdp_endpoint:
            cli.print_error(f"Не удалось подключиться к браузеру ({config.cdp_endpoint}).")
            cli.print_status("Запустите Chrome: chrome.exe --remote-debugging-port=9222")
        else:
            cli.print_error(f"Не удалось запустить MCP-сервер: {exc}")
        sys.exit(1)

    try:
        executor = ToolExecutor(mcp, memory)
        mcp_tools = await executor.init_mcp_tools()
        all_tools = merge_tools(mcp_tools)

        llm = LLMClient(
            api_key=config.anthropic_api_key,
            model=config.llm_model,
            max_tokens=config.llm_max_tokens,
        )

        mode = f"CDP ({config.cdp_endpoint})" if config.cdp_endpoint else "Standalone"
        cli.print_banner(len(all_tools), len(mcp_tools), mode)

        # Session tracking
        session_input_tokens = 0
        session_output_tokens = 0
        task_history: list[str] = []
        last_plan_task: str | None = None

        while True:
            try:
                task = cli.prompt_task()
            except (EOFError, KeyboardInterrupt):
                cli.print_status("Завершение…")
                break

            if not task:
                continue

            # --- Slash commands ---
            lower = task.lower()

            if lower in ("/exit", "/quit", "/q", "quit", "exit", "выход"):
                cli.print_status("Завершение…")
                break

            if lower in ("/help", "/h"):
                cli.print_help()
                continue

            if lower in ("/memory", "/m", "memory", "память"):
                keys = memory.list_keys()
                data = {k: memory.load(k) or "" for k in keys}
                cli.print_memory(data)
                continue

            if lower in ("/history",):
                cli.print_history(task_history)
                continue

            if lower in ("/cost",):
                cli.print_session_cost(session_input_tokens, session_output_tokens, len(task_history))
                continue

            # Plan command
            plan_task: str | None = None
            if lower.startswith("/plan "):
                plan_task = task[6:].strip()
            elif lower.startswith("plan "):
                plan_task = task[5:].strip()
            elif lower.startswith("план "):
                plan_task = task[len("план "):].strip()

            if plan_task is not None:
                if not plan_task:
                    cli.print_error("Укажите задачу: /plan <описание>")
                    continue
                context = ContextManager()
                agent = AgentLoop(llm, executor, context, config, all_tools)
                try:
                    plan_text = await agent.plan(plan_task)
                    cli.print_plan(plan_text)
                    usage = agent.get_usage()
                    session_input_tokens += usage["input_tokens"]
                    session_output_tokens += usage["output_tokens"]
                except Exception as exc:
                    cli.print_error(f"Ошибка планирования: {exc}")
                last_plan_task = plan_task
                continue

            # Execute last plan
            if lower in ("/go", "go", "выполняй"):
                if last_plan_task:
                    task = last_plan_task
                    last_plan_task = None
                else:
                    cli.print_error("Нет плана для выполнения. Используйте /plan <задача>")
                    continue

            # --- Execute task ---
            task_history.append(task)
            context = ContextManager()
            agent = AgentLoop(
                llm, executor, context, config, all_tools,
                on_event=cli.handle_event,
                memory=memory,
            )

            try:
                result = await agent.run(task)
                cli.print_result(result)
                usage = agent.get_usage()
                session_input_tokens += usage["input_tokens"]
                session_output_tokens += usage["output_tokens"]
                cli.print_usage(usage["steps"], usage["input_tokens"], usage["output_tokens"])

                # Save session metrics
                metrics = agent.export_metrics()
                try:
                    with open(METRICS_LOG_PATH, "a", encoding="utf-8") as f:
                        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")
                except OSError:
                    pass
            except KeyboardInterrupt:
                cli.print_error("Прервано пользователем.")
            except Exception as exc:
                cli.print_error(f"Ошибка: {exc}")
    finally:
        await mcp.stop()
        cli.print_status("MCP-сервер остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
