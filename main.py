"""CLI entry point: load config → start MCP → run agent loop."""

from __future__ import annotations

import asyncio
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
    config = load_config()
    memory = Memory(load_env_defaults=True)

    mcp = MCPClient()

    # Build MCP server args: package + headless/viewport flags
    mcp_args = [config.mcp_browser_args]
    if config.browser_headless:
        mcp_args.append("--headless")
    mcp_args.append(f"--viewport-size={config.browser_viewport_width},{config.browser_viewport_height}")

    print("🚀 Запускаю MCP-сервер (Playwright)…")
    try:
        await mcp.start(config.mcp_browser_command, mcp_args)
    except Exception as exc:
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
        print("Введите задачу для агента (или 'выход' для завершения, 'memory' для просмотра памяти).\n")

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

            context = ContextManager()
            agent = AgentLoop(llm, executor, context, config, all_tools)

            try:
                result = await agent.run(task)
                print(f"\n✅ Результат: {result}\n")
            except KeyboardInterrupt:
                print("\n⚠️ Прервано пользователем.\n")
            except Exception as exc:
                print(f"\n❌ Ошибка: {exc}\n")
    finally:
        await mcp.stop()
        print("MCP-сервер остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
