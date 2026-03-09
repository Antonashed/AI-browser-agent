from __future__ import annotations

from agent.tools import CUSTOM_TOOLS, get_custom_tool_names, merge_tools

EXPECTED_NAMES = {"remember", "recall", "ask_user", "show_preview", "confirm", "done"}


class TestCustomTools:
    def test_custom_tools_have_required_fields(self) -> None:
        for tool in CUSTOM_TOOLS:
            assert "name" in tool, f"Missing 'name' in {tool}"
            assert "description" in tool, f"Missing 'description' in {tool}"
            assert "input_schema" in tool, f"Missing 'input_schema' in {tool}"

    def test_no_duplicate_names(self) -> None:
        names = [t["name"] for t in CUSTOM_TOOLS]
        assert len(names) == len(set(names))

    def test_custom_tool_count(self) -> None:
        assert len(CUSTOM_TOOLS) == 6

    def test_expected_custom_tools_exist(self) -> None:
        names = set(get_custom_tool_names())
        assert names == EXPECTED_NAMES


class TestMergeTools:
    def test_merge_combines_mcp_and_custom(self) -> None:
        mcp_tools = [
            {"name": "browser_click", "description": "Click", "input_schema": {}},
            {"name": "browser_navigate", "description": "Navigate", "input_schema": {}},
        ]
        merged = merge_tools(mcp_tools)
        merged_names = {t["name"] for t in merged}
        assert "browser_click" in merged_names
        assert "browser_navigate" in merged_names
        for name in EXPECTED_NAMES:
            assert name in merged_names
        assert len(merged) == len(mcp_tools) + len(CUSTOM_TOOLS)

    def test_merge_no_name_conflicts(self) -> None:
        """If MCP returns a tool with the same name as a custom tool, ours wins."""
        mcp_tools = [
            {"name": "remember", "description": "MCP remember", "input_schema": {}},
        ]
        merged = merge_tools(mcp_tools)
        remember_tools = [t for t in merged if t["name"] == "remember"]
        assert len(remember_tools) == 1
        assert remember_tools[0]["description"] != "MCP remember"
