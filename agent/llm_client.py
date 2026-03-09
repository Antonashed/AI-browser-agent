from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import anthropic


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    text: str | None = None
    thinking: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class LLMClient:
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=api_key)

    async def send_message(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
    ) -> LLMResponse:
        cached_system = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        cached_tools = self._apply_cache_to_tools(tools)

        response = await asyncio.to_thread(
            self._client.messages.create,
            model=self._model,
            max_tokens=self._max_tokens,
            system=cached_system,
            messages=messages,
            tools=cached_tools,
        )
        return self._parse_response(response)

    @staticmethod
    def _apply_cache_to_tools(tools: list[dict]) -> list[dict]:
        """Copy tools list and add cache_control to the last tool."""
        if not tools:
            return tools
        cached = [dict(t) for t in tools]
        cached[-1] = {**cached[-1], "cache_control": {"type": "ephemeral"}}
        return cached

    def _parse_response(self, response: Any) -> LLMResponse:
        text_parts: list[str] = []
        thinking: str | None = None
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "thinking":
                thinking = block.thinking
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, args=block.input)
                )

        return LLMResponse(
            text="\n".join(text_parts) if text_parts else None,
            thinking=thinking,
            tool_calls=tool_calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        )
