"""CLI entry point: load config → start MCP → run agent loop."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from agent.config import load_config
from agent.context import ContextManager
from agent.core import AgentLoop
from agent.llm_client import LLMClient
from agent.mcp_client import MCPClient
from agent.memory import Memory
from agent.tool_executor import ToolExecutor
from agent.tools import merge_tools


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config()
    memory = Memory(load_env_defaults=True)

    mcp = MCPClient()

    # Build MCP server args: package + CDP or headless/viewport flags
    mcp_args = [config.mcp_browser_args]

    if config.cdp_endpoint:
        # CDP mode: connect to an already-running browser
        mcp_args.append(f"--cdp-endpoint={config.cdp_endpoint}")
    else:
        # Standalone mode: MCP launches its own browser
        if config.browser_headless:
            mcp_args.append("--headless")
        mcp_args.append(f"--viewport-size={config.browser_viewport_width},{config.browser_viewport_height}")
        if config.browser_storage_path:
            storage = config.browser_storage_path
            if os.path.exists(storage):
                mcp_args.append(f"--storage-state={storage}")
            mcp_args.append(f"--save-storage={storage}")

    if config.cdp_endpoint:
        print(f"🌐 Режим: подключение к открытому браузеру ({config.cdp_endpoint})")
        print(f"   Убедитесь, что Chrome запущен с --remote-debugging-port=9222")
    else:
        print(f"🌐 Режим: MCP запускает свой браузер (headless={config.browser_headless})")

    print("🚀 Запускаю MCP-сервер (Playwright)…")
    try:
        await mcp.start(config.mcp_browser_command, mcp_args)
    except Exception as exc:
        if config.cdp_endpoint:
            print(f"❌ Не удалось подключиться к браузеру ({config.cdp_endpoint}).")
            print(f"   Запустите Chrome: chrome.exe --remote-debugging-port=9222")
        else:
            print(f"❌ Не удалось запустить MCP-сервер: {exc}")
        sys.exit(1)
    print("✅ MCP-сервер запущен.")

    try:
        executor = ToolExecutor(mcp, memory)
        mcp_tools = await executor.init_mcp_tools()
        all_tools = merge_tools(mcp_tools)

        llm = LLMClient(
            api_key=config.anthropic_api_key,
            model=config.llm_model,
            max_tokens=config.llm_max_tokens,
        )

        print(f"🔧 Загружено tools: {len(all_tools)} (MCP: {len(mcp_tools)}, кастомных: {len(all_tools) - len(mcp_tools)})")
        print("Введите задачу для агента (или 'выход' для завершения, 'memory' для просмотра памяти, 'plan <задача>' для планирования).\n")

        last_plan_task: str | None = None
        while True:
            try:
                task = input("📝 Задача > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nЗавершение…")
                break

            if not task:
                continue

            if task.lower() in ("quit", "exit", "выход"):
                print("Завершение…")
                break

            if task.lower() in ("memory", "память"):
                keys = memory.list_keys()
                if not keys:
                    print("  (память пуста)")
                else:
                    for key in keys:
                        print(f"  {key}: {memory.load(key)}")
                print()
                continue

            # Dry-run planning mode
            plan_prefix = None
            lower = task.lower()
            if lower.startswith("plan "):
                plan_prefix = 5
            elif lower.startswith("\u043f\u043b\u0430\u043d "):
                plan_prefix = len("\u043f\u043b\u0430\u043d ")

            if plan_prefix is not None:
                plan_task = task[plan_prefix:].strip()
                if not plan_task:
                    print("❓ Укажите задачу: plan <описание>\n")
                    continue
                context = ContextManager()
                agent = AgentLoop(llm, executor, context, config, all_tools)
                try:
                    plan_text = await agent.plan(plan_task)
                    print(f"\n\U0001f4cb План:\n{plan_text}\n")
                    print("Введите 'go' для выполнения этого плана или новую задачу.\n")
                except Exception as exc:
                    print(f"\n\u274c Ошибка планирования: {exc}\n")
                last_plan_task = plan_task
                continue

            # Execute last plan with 'go' / 'выполняй'
            if task.lower() in ("go", "\u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0439") and last_plan_task:
                task = last_plan_task
                last_plan_task = None

            context = ContextManager()
            agent = AgentLoop(llm, executor, context, config, all_tools)

            try:
                result = await agent.run(task)
                usage = agent.get_usage()
                print(f"\n\u2705 Результат: {result}")
                print(f"\U0001f4ca [{usage['steps']} шагов, {usage['input_tokens']//1000}K input, {usage['output_tokens']//1000}K output]\n")
            except KeyboardInterrupt:
                print("\n⚠️ Прервано пользователем.\n")
            except Exception as exc:
                print(f"\n❌ Ошибка: {exc}\n")
    finally:
        await mcp.stop()
        print("MCP-сервер остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
