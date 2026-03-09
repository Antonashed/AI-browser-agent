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
