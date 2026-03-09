from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.mcp_client import MCPClient
    from agent.memory import Memory

from agent.llm_client import ToolCall


class ToolExecutor:
    """Routes tool calls: MCP tools → mcp_client, custom tools → local handlers."""

    def __init__(self, mcp_client: MCPClient, memory: Memory) -> None:
        self._mcp = mcp_client
        self._memory = memory
        self._mcp_tool_names: set[str] = set()

    async def init_mcp_tools(self) -> list[dict]:
        tools = await self._mcp.list_tools()
        self._mcp_tool_names = {t["name"] for t in tools}
        return tools

    async def execute(self, tool_call: ToolCall) -> str:
        try:
            if tool_call.name in self._mcp_tool_names:
                return await self._mcp.call_tool(tool_call.name, tool_call.args)

            match tool_call.name:
                case "remember":
                    self._memory.save(tool_call.args["key"], tool_call.args["value"])
                    return f"Saved '{tool_call.args['key']}'."
                case "recall":
                    value = self._memory.load(tool_call.args["key"])
                    if value is None:
                        return f"Key '{tool_call.args['key']}' not found in memory."
                    return value
                case "ask_user" | "show_preview" | "confirm" | "done":
                    # These are handled by the AgentLoop (core.py), not here.
                    return f"Handled by agent loop: {tool_call.name}"
                case _:
                    return f"Unknown tool: {tool_call.name}"
        except Exception as e:
            return f"Error: {e}"
