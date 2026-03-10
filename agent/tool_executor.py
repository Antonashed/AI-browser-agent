from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.mcp_client import MCPClient
    from agent.memory import Memory

from agent.llm_client import ToolCall
from agent.page_parser import extract_zone, parse_zones, zone_summary


class ToolExecutor:
    """Routes tool calls: MCP tools → mcp_client, custom tools → local handlers."""

    MAX_SNAPSHOT_CHARS = 8000

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
                result = await self._mcp.call_tool(tool_call.name, tool_call.args)
                if tool_call.name == "browser_snapshot":
                    result = self._truncate_snapshot(result)
                return result

            match tool_call.name:
                case "page_overview":
                    snapshot = await self._mcp.call_tool("browser_snapshot", {})
                    zones = parse_zones(snapshot)
                    return zone_summary(zones)
                case "get_zone":
                    zone_name = tool_call.args["zone"]
                    max_chars = tool_call.args.get("max_chars", 6000)
                    snapshot = await self._mcp.call_tool("browser_snapshot", {})
                    text = extract_zone(snapshot, zone_name)
                    return self._truncate_snapshot(text, max_chars=max_chars)
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
            return f"[ERROR] {e}"

    @staticmethod
    def _truncate_snapshot(text: str, max_chars: int = 8000) -> str:
        """Truncate long a11y snapshots, keeping structure."""
        if len(text) <= max_chars:
            return text
        lines = text.split("\n")
        output: list[str] = []
        total = 0
        for line in lines:
            if total + len(line) > max_chars:
                break
            output.append(line)
            total += len(line) + 1
        output.append(f"\n... [truncated — {len(text) - total} chars omitted]")
        return "\n".join(output)
