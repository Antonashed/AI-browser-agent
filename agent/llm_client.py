from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx

from agent.events import AgentEvent, EventType

logger = logging.getLogger(__name__)

MAX_RETRY_DELAY = 30
RATE_LIMIT_DELAY = 60

_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
    httpx.ConnectError,
    httpx.ReadError,
)

# 529 Overloaded is not a separate class in anthropic SDK v0.52;
# it arrives as APIStatusError with status_code=529.
_RETRYABLE_STATUS_CODES = {529}
_APIStatusError = anthropic.APIStatusError


def _retry_delay(exc: Exception, attempt: int) -> int:
    """Choose delay based on error type: 60s for rate-limit, exponential backoff otherwise."""
    if isinstance(exc, anthropic.RateLimitError):
        return RATE_LIMIT_DELAY
    return min(attempt * 2, MAX_RETRY_DELAY)


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
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096, proxy: str = "") -> None:
        self._model = model
        self._max_tokens = max_tokens
        if proxy:
            sync_http = httpx.Client(proxy=proxy)
            async_http = httpx.AsyncClient(proxy=proxy)
            self._client = anthropic.Anthropic(api_key=api_key, http_client=sync_http)
            self._async_client = anthropic.AsyncAnthropic(api_key=api_key, http_client=async_http)
        else:
            self._client = anthropic.Anthropic(api_key=api_key)
            self._async_client = anthropic.AsyncAnthropic(api_key=api_key)

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

        attempt = 0
        while True:
            try:
                response = await asyncio.to_thread(
                    self._client.messages.create,
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=cached_system,
                    messages=messages,
                    tools=cached_tools,
                )
                return self._parse_response(response)
            except _RETRYABLE_ERRORS as exc:
                attempt += 1
                delay = _retry_delay(exc, attempt)
                logger.warning(
                    "Anthropic API error (attempt %d): %s — retrying in %ds",
                    attempt, exc, delay,
                )
                await asyncio.sleep(delay)
            except _APIStatusError as exc:
                if exc.status_code in _RETRYABLE_STATUS_CODES:
                    attempt += 1
                    delay = _retry_delay(exc, attempt)
                    logger.warning(
                        "Anthropic API overloaded (attempt %d): %s — retrying in %ds",
                        attempt, exc, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

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

    async def send_message_stream(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
    ) -> AsyncGenerator[AgentEvent | LLMResponse, None]:
        """Stream LLM response, yielding AgentEvents for thinking/text deltas.

        Yields AgentEvent(THINKING_DELTA/TEXT_DELTA) during streaming.
        Final yield is an LLMResponse with aggregated data.
        """
        cached_system = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        cached_tools = self._apply_cache_to_tools(tools)

        attempt = 0
        while True:
            try:
                text_parts: list[str] = []
                thinking_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                current_tool: dict[str, Any] | None = None
                input_tokens = 0
                output_tokens = 0

                async with self._async_client.messages.stream(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=cached_system,
                    messages=messages,
                    tools=cached_tools,
                ) as stream:
                    async for event in stream:
                        if event.type == "content_block_start":
                            block = event.content_block
                            if block.type == "tool_use":
                                current_tool = {"id": block.id, "name": block.name, "input_json": ""}
                        elif event.type == "content_block_delta":
                            delta = event.delta
                            if delta.type == "thinking_delta":
                                thinking_parts.append(delta.thinking)
                                yield AgentEvent(
                                    type=EventType.THINKING_DELTA,
                                    data={"text": delta.thinking},
                                )
                            elif delta.type == "text_delta":
                                text_parts.append(delta.text)
                                yield AgentEvent(
                                    type=EventType.TEXT_DELTA,
                                    data={"text": delta.text},
                                )
                            elif delta.type == "input_json_delta" and current_tool:
                                current_tool["input_json"] += delta.partial_json
                        elif event.type == "content_block_stop":
                            if current_tool:
                                import json as _json
                                try:
                                    args = _json.loads(current_tool["input_json"]) if current_tool["input_json"] else {}
                                except _json.JSONDecodeError:
                                    args = {}
                                tool_calls.append(ToolCall(
                                    id=current_tool["id"],
                                    name=current_tool["name"],
                                    args=args,
                                ))
                                current_tool = None
                        elif event.type == "message_delta":
                            usage = getattr(event, "usage", None)
                            if usage:
                                output_tokens = getattr(usage, "output_tokens", 0) or 0

                    # Get final message for usage info
                    final_message = await stream.get_final_message()
                    input_tokens = final_message.usage.input_tokens
                    output_tokens = final_message.usage.output_tokens

                yield LLMResponse(
                    text="\n".join(text_parts) if text_parts else None,
                    thinking="\n".join(thinking_parts) if thinking_parts else None,
                    tool_calls=tool_calls,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_input_tokens=getattr(final_message.usage, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(final_message.usage, "cache_read_input_tokens", 0) or 0,
                )
                return
            except _RETRYABLE_ERRORS as exc:
                attempt += 1
                delay = _retry_delay(exc, attempt)
                logger.warning(
                    "Anthropic streaming error (attempt %d): %s — retrying in %ds",
                    attempt, exc, delay,
                )
                await asyncio.sleep(delay)
            except _APIStatusError as exc:
                if exc.status_code in _RETRYABLE_STATUS_CODES:
                    attempt += 1
                    delay = _retry_delay(exc, attempt)
                    logger.warning(
                        "Anthropic streaming overloaded (attempt %d): %s — retrying in %ds",
                        attempt, exc, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
