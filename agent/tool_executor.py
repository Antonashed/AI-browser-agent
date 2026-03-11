from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.mcp_client import MCPClient
    from agent.memory import Memory

from agent.llm_client import ToolCall
from agent.page_parser import extract_zone, page_stats, parse_zones, zone_summary

# Strip verbose Playwright code blocks from MCP results to save tokens
_CODE_BLOCK_RE = re.compile(
    r"### Ran Playwright code\n```js\n.*?\n```\n?",
    re.DOTALL,
)

# Actions that change page content → reset zone cache
_PAGE_CHANGE_ACTIONS = {
    "browser_navigate", "browser_click", "browser_type",
    "browser_select_option", "browser_go_back",
}


class ToolExecutor:
    """Routes tool calls: MCP tools → mcp_client, custom tools → local handlers."""

    MAX_SNAPSHOT_CHARS = 6000

    def __init__(self, mcp_client: MCPClient, memory: Memory) -> None:
        self._mcp = mcp_client
        self._memory = memory
        self._mcp_tool_names: set[str] = set()
        self._last_zone_results: dict[str, str] = {}
        self._processed_items_ref: list[str] | None = None
        self._recalled_keys: dict[str, str] = {}  # key → short excerpt for dedup
        self._recall_all_count: int = 0

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
                cleaned = self._clean_mcp_result(result)
                if tool_call.name in _PAGE_CHANGE_ACTIONS and not cleaned.startswith("[ERROR]"):
                    self._last_zone_results.clear()
                    # Auto-close extra tabs after navigation to keep single-tab workflow
                    if tool_call.name == "browser_navigate":
                        await self._close_extra_tabs()
                        # Auto-read page content so the agent doesn't need a separate get_zone call
                        try:
                            snapshot = await self._mcp.call_tool("browser_snapshot", {})
                            zone_text = extract_zone(snapshot, "main")
                            if "not found" in zone_text.lower():
                                zone_text = extract_zone(snapshot, "all")
                            zone_text = self._truncate_snapshot(zone_text, max_chars=4000)
                            self._last_zone_results["main"] = zone_text
                            self._zone_repeat_count = 0
                            cleaned += f"\n\n📄 PAGE CONTENT (auto-read):\n{zone_text}"
                        except Exception:
                            pass  # Non-critical
                return cleaned

            match tool_call.name:
                case "page_overview":
                    snapshot = await self._mcp.call_tool("browser_snapshot", {})
                    zones = parse_zones(snapshot)
                    stats = page_stats(snapshot)
                    self._last_zone_results.clear()
                    return f"{stats}\n\n{zone_summary(zones)}"
                case "get_zone":
                    zone_name = tool_call.args["zone"]
                    max_chars = min(tool_call.args.get("max_chars", 6000), 12000)
                    snapshot = await self._mcp.call_tool("browser_snapshot", {})
                    text = extract_zone(snapshot, zone_name)
                    result_text = self._truncate_snapshot(text, max_chars=max_chars)
                    # Detect repeated identical content (anti-loop)
                    if (
                        zone_name in self._last_zone_results
                        and result_text == self._last_zone_results[zone_name]
                    ):
                        self._zone_repeat_count = getattr(self, '_zone_repeat_count', 0) + 1
                        if self._zone_repeat_count >= 2:
                            return (
                                f"[SAME CONTENT x{self._zone_repeat_count}] "
                                "STOP. Use data from previous read. Call remember() or done()."
                            )
                        return (
                            f"[SAME CONTENT] Zone '{zone_name}' unchanged. "
                            "Use data from previous read. Call remember() then next item."
                        )
                    self._last_zone_results[zone_name] = result_text
                    self._zone_repeat_count = 0
                    return result_text
                case "remember":
                    key = tool_call.args["key"]
                    value = tool_call.args["value"]
                    self._memory.save(key, value)
                    # Cache for recall dedup — agent already has this data in context
                    self._recalled_keys[key] = value[:80]
                    return f"Saved '{key}'. Navigate to next item URL now."
                case "recall":
                    key = tool_call.args["key"]
                    # Dedup: if already recalled/saved this key, return short hint
                    if key in self._recalled_keys:
                        return (
                            f"Already in context. '{key}' = {self._recalled_keys[key]}... "
                            "Use data from conversation history. Do NOT recall again."
                        )
                    value = self._memory.load(key)
                    if value is not None:
                        self._recalled_keys[key] = value[:80]
                        return value
                    # Fuzzy match: find keys containing the query or vice versa
                    all_keys = list(self._memory.list_keys())
                    key_lower = key.lower()
                    matches = [
                        k for k in all_keys
                        if key_lower in k.lower() or k.lower() in key_lower
                    ]
                    if matches:
                        parts = [f"- {k}: {self._memory.load(k)}" for k in matches]
                        return f"Key '{key}' not found. Similar keys:\n" + "\n".join(parts)
                    if all_keys:
                        return f"Key '{key}' not found. Available keys: {', '.join(all_keys)}"
                    return f"Key '{key}' not found in memory."
                case "recall_all":
                    self._recall_all_count += 1
                    if self._recall_all_count > 1:
                        # Already recalled all — data is in conversation history
                        return (
                            "You already called recall_all(). All data is in your "
                            "conversation history above. Do NOT call recall_all() again."
                        )
                    keys = list(self._memory.list_keys())
                    if not keys:
                        text = "Memory is empty."
                    else:
                        parts = [f"- {k}: {self._memory.load(k)}" for k in keys]
                        text = "Stored memory:\n" + "\n".join(parts)
                        # Cache all keys for recall dedup
                        for k in keys:
                            v = self._memory.load(k)
                            if v:
                                self._recalled_keys[k] = v[:80]
                    if self._processed_items_ref:
                        text += "\n\nProcessed items (DO NOT revisit):\n"
                        text += "\n".join(f"- ✅ {item}" for item in self._processed_items_ref)
                    return text
                case "ask_user" | "show_preview" | "confirm" | "done" | "set_plan" | "complete_plan_step" | "mark_processed":
                    # These are handled by the AgentLoop (core.py), not here.
                    return f"Handled by agent loop: {tool_call.name}"
                case _:
                    return f"Unknown tool: {tool_call.name}"
        except Exception as e:
            return f"[ERROR] {e}"

    @staticmethod
    def _clean_mcp_result(text: str) -> str:
        """Strip verbose Playwright code blocks to save tokens."""
        cleaned = _CODE_BLOCK_RE.sub("", text)
        # Collapse multiple blank lines
        while "\n\n\n" in cleaned:
            cleaned = cleaned.replace("\n\n\n", "\n\n")
        return cleaned.strip()

    async def _close_extra_tabs(self) -> None:
        """Close all browser tabs except the current one to prevent tab accumulation."""
        try:
            tabs_result = await self._mcp.call_tool("browser_tab_list", {})
            if not tabs_result:
                return
            # Parse tab lines — each line typically contains a tab entry
            lines = [l.strip() for l in tabs_result.strip().split("\n") if l.strip()]
            if len(lines) <= 1:
                return
            # Close all non-current tabs via browser_close for each extra tab
            for line in lines:
                # Skip the current/active tab
                if "[current]" in line.lower() or "(current)" in line.lower() or "* " in line[:3]:
                    continue
                # Try to close by calling browser_tab_close if available, otherwise ignore
                if "browser_tab_close" in self._mcp_tool_names:
                    # Extract tab index from line if possible
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        try:
                            await self._mcp.call_tool("browser_tab_close", {"index": int(parts[0])})
                        except Exception:
                            pass
        except Exception:
            pass  # Non-critical — don't break navigation on tab cleanup failure

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
