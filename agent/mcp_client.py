from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPClient:
    """Manages lifecycle of an MCP server and provides list_tools / call_tool."""

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._stdio_context: Any = None
        self._session_context: Any = None

    async def start(self, command: str, args: list[str]) -> None:
        params = StdioServerParameters(command=command, args=args)
        self._stdio_context = stdio_client(params)
        read_stream, write_stream = await self._stdio_context.__aenter__()
        self._session = ClientSession(read_stream, write_stream)
        await self._session.__aenter__()
        await self._session.initialize()

    async def stop(self) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except (Exception, KeyboardInterrupt):
                logger.debug("Error closing MCP session", exc_info=True)
            self._session = None
        if self._stdio_context is not None:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except (Exception, KeyboardInterrupt):
                logger.debug("Error closing MCP stdio transport", exc_info=True)
            self._stdio_context = None

    async def list_tools(self) -> list[dict]:
        if self._session is None:
            raise RuntimeError("MCPClient not started")
        result = await self._session.list_tools()
        return [self._convert_tool(t) for t in result.tools]

    async def call_tool(self, name: str, arguments: dict, timeout: float = 60.0) -> str:
        if self._session is None:
            raise RuntimeError("MCPClient not started")
        result = await asyncio.wait_for(
            self._session.call_tool(name, arguments), timeout=timeout,
        )
        return self._extract_text(result)

    async def __aenter__(self) -> MCPClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    @staticmethod
    def _convert_tool(mcp_tool: Any) -> dict:
        return {
            "name": mcp_tool.name,
            "description": mcp_tool.description or "",
            "input_schema": mcp_tool.inputSchema,
        }

    @staticmethod
    def _extract_text(result: Any) -> str:
        parts: list[str] = []
        for block in result.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "\n".join(parts) if parts else ""
