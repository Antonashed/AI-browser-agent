"""CLI entry point: load config → start MCP → run agent loop with Rich UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import anthropic

from agent.cli import CLI
from agent.config import Config, load_config
from agent.context import ContextManager
from agent.core import AgentLoop
from agent.llm_client import LLMClient
from agent.mcp_client import MCPClient
from agent.memory import Memory
from agent.presets import PresetManager
from agent.tool_executor import ToolExecutor
from agent.tools import get_all_tools

DATA_DIR = Path("data")
METRICS_LOG_PATH = DATA_DIR / "session_metrics.jsonl"


def _setup_logging(config: Config) -> None:
    """Configure logging: to file if LOG_FILE is set, otherwise stderr."""

    class _FlushFilter(logging.Filter):
        """Flush the handler stream after every log record."""
        def __init__(self, target_handler: logging.FileHandler) -> None:
            super().__init__()
            self._handler = target_handler

        def filter(self, record: logging.LogRecord) -> bool:
            # Always allow the record; flush is a side-effect
            self._handler.flush()
            return True

    log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    level = getattr(logging, config.log_level, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    # Remove any pre-existing handlers
    root.handlers.clear()

    if config.log_file:
        handler: logging.Handler = logging.FileHandler(config.log_file, encoding="utf-8")
        handler.addFilter(_FlushFilter(handler))
    else:
        handler = logging.StreamHandler()

    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(log_fmt, datefmt="%H:%M:%S"))
    root.addHandler(handler)


async def main() -> None:
    cli = CLI()
    config = load_config()
    _setup_logging(config)
    DATA_DIR.mkdir(exist_ok=True)
    memory = Memory(load_env_defaults=True)

    mcp = MCPClient()

    # Build MCP server args (standalone — MCP launches its own Chromium)
    mcp_args = [config.mcp_browser_args]
    if config.browser_headless:
        mcp_args.append("--headless")
    mcp_args.append(f"--viewport-size={config.browser_viewport_width}x{config.browser_viewport_height}")
    if config.browser_storage_path:
        storage = config.browser_storage_path
        if os.path.exists(storage):
            mcp_args.append(f"--storage-state={storage}")

    cli.print_status("Запускаю MCP-сервер (Playwright)…")
    try:
        await mcp.start(config.mcp_browser_command, mcp_args)
    except Exception as exc:
        cli.print_error(f"Не удалось запустить MCP-сервер: {exc}")
        sys.exit(1)

    try:
        executor = ToolExecutor(mcp, memory)
        mcp_tools = await executor.init_mcp_tools()
        all_tools = get_all_tools(mcp_tools)

        llm = LLMClient(
            api_key=config.anthropic_api_key,
            model=config.llm_model,
            max_tokens=config.llm_max_tokens,
            proxy=config.anthropic_proxy,
        )

        mode = "Standalone"
        cli.print_banner(len(all_tools), len(mcp_tools), mode, config.llm_model)

        # Session tracking
        session_input_tokens = 0
        session_output_tokens = 0
        task_history: list[str] = []
        last_plan_task: str | None = None
        last_agent: AgentLoop | None = None
        preset_manager = PresetManager()

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

            if lower in ("/presets",):
                names = preset_manager.list_presets()
                cli.print_presets(names)
                continue

            if lower in ("/preset",):
                if last_agent is None:
                    cli.print_error("Нет завершённой задачи для создания пресета.")
                    continue
                plan_steps = last_agent.get_plan_steps()
                agent_task = last_agent.get_task()
                if not plan_steps:
                    cli.print_error("У последней задачи нет плана. Пресет не создан.")
                    continue
                name = input("  Название пресета: ").strip()
                if not name:
                    cli.print_error("Название не может быть пустым.")
                    continue
                preset = preset_manager.create_from_session(
                    name=name,
                    task=agent_task,
                    plan=plan_steps,
                )
                path = preset_manager.save(preset)
                cli.print_preset_saved(preset.name, str(path))
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

            # /strong — force strong model for this task
            force_strong = False
            if lower.startswith("/strong "):
                task = task[8:].strip()
                if not task:
                    cli.print_error("Укажите задачу: /strong <описание>")
                    continue
                force_strong = True

            # --- Execute task ---
            if force_strong:
                llm.set_model(config.llm_model_strong)
                cli.print_status(f"Модель: {config.llm_model_strong} (принудительно)")

            task_history.append(task)
            context = ContextManager()
            agent = AgentLoop(
                llm, executor, context, config, all_tools,
                on_event=cli.handle_event,
                memory=memory,
                preset_manager=preset_manager,
            )

            try:
                result = await agent.run(task)
                cli.print_result(result)
                usage = agent.get_usage()
                session_input_tokens += usage["input_tokens"]
                session_output_tokens += usage["output_tokens"]
                cli.print_usage(usage["steps"], usage["input_tokens"], usage["output_tokens"])
                last_agent = agent

                # Save session metrics
                metrics = agent.export_metrics()
                try:
                    with open(METRICS_LOG_PATH, "a", encoding="utf-8") as f:
                        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")
                except OSError:
                    pass
            except KeyboardInterrupt:
                cli.print_error("Прервано пользователем.")
            except anthropic.RateLimitError as exc:
                cli.print_error(f"Rate limit: {exc} — повторяю через 60с...")
                await asyncio.sleep(60)
                continue
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                cli.print_error(f"API ошибка: {exc} — повторяю через 20с...")
                await asyncio.sleep(20)
                continue
            except Exception as exc:
                cli.print_error(f"Ошибка: {exc}")
            finally:
                llm.reset_model()
    finally:
        await mcp.stop()
        cli.print_status("MCP-сервер остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
