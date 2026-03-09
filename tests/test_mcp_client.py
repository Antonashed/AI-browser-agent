import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from agent.mcp_client import MCPClient


def _make_mock_tool(name: str, description: str, input_schema: dict):
    """Create a mock MCP Tool object."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema
    return tool


def _make_mock_call_result(text: str, is_error: bool = False):
    """Create a mock CallToolResult."""
    content_item = MagicMock()
    content_item.type = "text"
    content_item.text = text
    result = MagicMock()
    result.content = [content_item]
    result.isError = is_error
    return result


def _build_mocked_session(tools=None, call_result=None):
    """Build a mocked ClientSession with list_tools/call_tool."""
    session = AsyncMock()
    session.initialize = AsyncMock()

    list_result = MagicMock()
    list_result.tools = tools or []
    session.list_tools = AsyncMock(return_value=list_result)

    session.call_tool = AsyncMock(
        return_value=call_result or _make_mock_call_result("ok")
    )
    return session


@asynccontextmanager
async def _fake_stdio_client(params):
    read_stream = MagicMock()
    write_stream = MagicMock()
    yield read_stream, write_stream


@pytest.mark.asyncio
class TestMCPClient:

    async def test_start_and_stop(self):
        session = _build_mocked_session()
        with (
            patch("agent.mcp_client.stdio_client", side_effect=_fake_stdio_client),
            patch("agent.mcp_client.ClientSession", return_value=session),
        ):
            client = MCPClient()
            await client.start(command="npx", args=["@playwright/mcp", "--headless"])
            session.initialize.assert_awaited_once()
            await client.stop()

    async def test_context_manager(self):
        session = _build_mocked_session()
        with (
            patch("agent.mcp_client.stdio_client", side_effect=_fake_stdio_client),
            patch("agent.mcp_client.ClientSession", return_value=session),
        ):
            async with MCPClient() as client:
                await client.start(command="npx", args=["@playwright/mcp"])
                session.initialize.assert_awaited_once()

    async def test_list_tools_returns_anthropic_format(self):
        mock_tools = [
            _make_mock_tool(
                "browser_click",
                "Click an element",
                {"type": "object", "properties": {"ref": {"type": "string"}}},
            ),
            _make_mock_tool(
                "browser_navigate",
                "Navigate to URL",
                {"type": "object", "properties": {"url": {"type": "string"}}},
            ),
        ]
        session = _build_mocked_session(tools=mock_tools)
        with (
            patch("agent.mcp_client.stdio_client", side_effect=_fake_stdio_client),
            patch("agent.mcp_client.ClientSession", return_value=session),
        ):
            async with MCPClient() as client:
                await client.start(command="npx", args=["@playwright/mcp"])
                tools = await client.list_tools()

                assert len(tools) == 2
                for tool in tools:
                    assert "name" in tool
                    assert "description" in tool
                    assert "input_schema" in tool

                assert tools[0]["name"] == "browser_click"
                assert tools[1]["name"] == "browser_navigate"

    async def test_call_tool_returns_string(self):
        call_result = _make_mock_call_result("Navigated to https://google.com")
        session = _build_mocked_session(call_result=call_result)
        with (
            patch("agent.mcp_client.stdio_client", side_effect=_fake_stdio_client),
            patch("agent.mcp_client.ClientSession", return_value=session),
        ):
            async with MCPClient() as client:
                await client.start(command="npx", args=["@playwright/mcp"])
                result = await client.call_tool("browser_navigate", {"url": "https://google.com"})
                assert isinstance(result, str)
                assert "google.com" in result

    async def test_call_nonexistent_tool_raises(self):
        session = _build_mocked_session()
        session.call_tool = AsyncMock(side_effect=Exception("Tool not found: fly_to_moon"))
        with (
            patch("agent.mcp_client.stdio_client", side_effect=_fake_stdio_client),
            patch("agent.mcp_client.ClientSession", return_value=session),
        ):
            async with MCPClient() as client:
                await client.start(command="npx", args=["@playwright/mcp"])
                with pytest.raises(Exception, match="fly_to_moon"):
                    await client.call_tool("fly_to_moon", {})
