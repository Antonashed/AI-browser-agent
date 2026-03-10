from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.llm_client import ToolCall
from agent.tool_executor import ToolExecutor


@pytest.fixture
def mock_mcp_client() -> AsyncMock:
    mcp = AsyncMock()
    mcp.list_tools.return_value = [
        {"name": "browser_click", "description": "Click", "input_schema": {}},
        {"name": "browser_navigate", "description": "Nav", "input_schema": {}},
    ]
    mcp.call_tool.return_value = "tool result"
    return mcp


@pytest.fixture
def mock_memory() -> MagicMock:
    mem = MagicMock()
    mem.save = MagicMock()
    mem.load = MagicMock(return_value=None)
    return mem


@pytest.fixture
def executor(mock_mcp_client: AsyncMock, mock_memory: MagicMock) -> ToolExecutor:
    return ToolExecutor(mcp_client=mock_mcp_client, memory=mock_memory)


@pytest.mark.asyncio
class TestToolExecutor:
    async def test_mcp_tool_routed_to_mcp(
        self, executor: ToolExecutor, mock_mcp_client: AsyncMock
    ) -> None:
        await executor.init_mcp_tools()
        tc = ToolCall(id="1", name="browser_click", args={"ref": "e5"})
        result = await executor.execute(tc)
        mock_mcp_client.call_tool.assert_called_once_with("browser_click", {"ref": "e5"})
        assert result == "tool result"

    async def test_remember_saves_to_memory(
        self, executor: ToolExecutor, mock_memory: MagicMock
    ) -> None:
        tc = ToolCall(id="2", name="remember", args={"key": "user_email", "value": "a@b.com"})
        result = await executor.execute(tc)
        mock_memory.save.assert_called_once_with("user_email", "a@b.com")
        assert "saved" in result.lower()

    async def test_recall_existing(
        self, executor: ToolExecutor, mock_memory: MagicMock
    ) -> None:
        mock_memory.load.return_value = "a@b.com"
        tc = ToolCall(id="3", name="recall", args={"key": "user_email"})
        result = await executor.execute(tc)
        mock_memory.load.assert_called_once_with("user_email")
        assert "a@b.com" in result

    async def test_recall_missing(
        self, executor: ToolExecutor, mock_memory: MagicMock
    ) -> None:
        mock_memory.load.return_value = None
        tc = ToolCall(id="4", name="recall", args={"key": "nonexistent"})
        result = await executor.execute(tc)
        assert "not found" in result.lower()

    async def test_unknown_tool_returns_error(self, executor: ToolExecutor) -> None:
        tc = ToolCall(id="5", name="fly_to_moon", args={})
        result = await executor.execute(tc)
        assert "unknown tool" in result.lower()


class TestTruncateSnapshot:
    def test_truncate_snapshot_short(self) -> None:
        """Text shorter than max_chars → returned unchanged."""
        short = "line1\nline2\nline3"
        assert ToolExecutor._truncate_snapshot(short) == short

    def test_truncate_snapshot_long(self) -> None:
        """Text longer than max_chars → truncated with marker."""
        long_text = "\n".join(f"line {i}: {'x' * 80}" for i in range(200))
        result = ToolExecutor._truncate_snapshot(long_text, max_chars=500)
        assert len(result) <= 600  # some slack for truncation marker
        assert "truncated" in result.lower()


SAMPLE_SNAPSHOT = """\
- banner "Site" [ref=e1]
  - link "Logo" [ref=e2]
- main "Content" [ref=e3]
  - heading "Title" [ref=e4]
  - paragraph "Text" [ref=e5]
- contentinfo [ref=e6]
  - text "Footer" """


@pytest.mark.asyncio
class TestPageOverviewAndGetZone:
    async def test_page_overview_returns_summary(
        self, executor: ToolExecutor, mock_mcp_client: AsyncMock
    ) -> None:
        mock_mcp_client.call_tool.return_value = SAMPLE_SNAPSHOT
        tc = ToolCall(id="10", name="page_overview", args={})
        result = await executor.execute(tc)
        assert "Zones:" in result
        assert "banner" in result
        assert "main" in result
        assert "Total:" in result

    async def test_get_zone_returns_filtered(
        self, executor: ToolExecutor, mock_mcp_client: AsyncMock
    ) -> None:
        mock_mcp_client.call_tool.return_value = SAMPLE_SNAPSHOT
        tc = ToolCall(id="11", name="get_zone", args={"zone": "main"})
        result = await executor.execute(tc)
        assert "Title" in result
        assert "Logo" not in result

    async def test_get_zone_all(
        self, executor: ToolExecutor, mock_mcp_client: AsyncMock
    ) -> None:
        mock_mcp_client.call_tool.return_value = SAMPLE_SNAPSHOT
        tc = ToolCall(id="12", name="get_zone", args={"zone": "all"})
        result = await executor.execute(tc)
        assert "banner" in result
        assert "main" in result
        assert "contentinfo" in result

    async def test_get_zone_missing(
        self, executor: ToolExecutor, mock_mcp_client: AsyncMock
    ) -> None:
        mock_mcp_client.call_tool.return_value = SAMPLE_SNAPSHOT
        tc = ToolCall(id="13", name="get_zone", args={"zone": "nonexistent"})
        result = await executor.execute(tc)
        assert "not found" in result.lower()
