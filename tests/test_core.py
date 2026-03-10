from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.core import AgentLoop
from agent.context import ContextManager
from agent.llm_client import LLMResponse, ToolCall


def _make_loop(
    llm_responses: list[LLMResponse],
    max_steps: int = 10,
) -> tuple[AgentLoop, AsyncMock, AsyncMock]:
    """Create AgentLoop with mocked LLM and ToolExecutor."""
    llm_client = AsyncMock()
    llm_client.send_message = AsyncMock(side_effect=llm_responses)

    tool_executor = AsyncMock()
    tool_executor.execute = AsyncMock(return_value="ok")

    context = ContextManager()

    config = MagicMock()
    config.max_agent_steps = max_steps

    all_tools = [{"name": "browser_navigate", "description": "nav", "input_schema": {}}]

    loop = AgentLoop(
        llm_client=llm_client,
        tool_executor=tool_executor,
        context=context,
        config=config,
        all_tools=all_tools,
    )

    return loop, llm_client, tool_executor


@pytest.mark.asyncio
async def test_returns_summary_on_done():
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="1", name="done", args={"summary": "All done!"})]),
    ]
    loop, _, _ = _make_loop(responses)
    result = await loop.run("Do something")
    assert result == "All done!"


@pytest.mark.asyncio
async def test_executes_tool_and_continues():
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="1", name="browser_navigate", args={"url": "https://example.com"})]),
        LLMResponse(tool_calls=[ToolCall(id="2", name="done", args={"summary": "Navigated!"})]),
    ]
    loop, _, executor = _make_loop(responses)
    result = await loop.run("Go to example.com")
    assert result == "Navigated!"
    executor.execute.assert_called_once()


@pytest.mark.asyncio
async def test_stops_at_max_steps():
    responses = [
        LLMResponse(tool_calls=[ToolCall(id=str(i), name="browser_click", args={"ref": "1"})]) for i in range(5)
    ]
    loop, _, _ = _make_loop(responses, max_steps=3)
    result = await loop.run("Infinite task")
    assert "лимит" in result.lower() or "limit" in result.lower()


@pytest.mark.asyncio
async def test_ask_user_gets_input():
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="1", name="ask_user", args={"question": "What city?"})]),
        LLMResponse(tool_calls=[ToolCall(id="2", name="done", args={"summary": "Got input"})]),
    ]
    loop, _, _ = _make_loop(responses)
    with patch("builtins.input", return_value="Moscow"):
        result = await loop.run("Ask city")
    assert result == "Got input"


@pytest.mark.asyncio
async def test_confirm_yes():
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="1", name="confirm", args={"question": "Delete?"})]),
        LLMResponse(tool_calls=[ToolCall(id="2", name="done", args={"summary": "Confirmed"})]),
    ]
    loop, _, _ = _make_loop(responses)
    with patch("builtins.input", return_value="да"):
        result = await loop.run("Delete files")
    assert result == "Confirmed"


@pytest.mark.asyncio
async def test_show_preview(capsys):
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="1", name="show_preview", args={"title": "Items", "items": ["a", "b"]})]),
        LLMResponse(tool_calls=[ToolCall(id="2", name="done", args={"summary": "Previewed"})]),
    ]
    loop, _, _ = _make_loop(responses)
    result = await loop.run("Show stuff")
    assert result == "Previewed"
    captured = capsys.readouterr()
    assert "Items" in captured.out


@pytest.mark.asyncio
async def test_text_only_response_continues():
    """If LLM returns text without tools, loop should continue."""
    responses = [
        LLMResponse(text="Let me think..."),
        LLMResponse(tool_calls=[ToolCall(id="1", name="done", args={"summary": "Done thinking"})]),
    ]
    loop, _, _ = _make_loop(responses)
    result = await loop.run("Think about it")
    assert result == "Done thinking"


@pytest.mark.asyncio
async def test_usage_tracking():
    """After run(), get_usage() returns steps, input_tokens, output_tokens."""
    responses = [
        LLMResponse(
            tool_calls=[ToolCall(id="1", name="browser_navigate", args={"url": "https://example.com"})],
            input_tokens=500,
            output_tokens=100,
        ),
        LLMResponse(
            tool_calls=[ToolCall(id="2", name="done", args={"summary": "Done"})],
            input_tokens=600,
            output_tokens=150,
        ),
    ]
    loop, _, _ = _make_loop(responses)
    await loop.run("Go somewhere")
    usage = loop.get_usage()
    assert usage["steps"] == 2
    assert usage["input_tokens"] == 1100
    assert usage["output_tokens"] == 250


@pytest.mark.asyncio
async def test_plan_returns_text():
    """plan() → non-empty text, no tool calls executed."""
    plan_text = "1. browser_navigate: Open page\n2. browser_snapshot: Check content"
    plan_response = LLMResponse(text=plan_text, input_tokens=200, output_tokens=50)

    llm_client = AsyncMock()
    llm_client.send_message = AsyncMock(return_value=plan_response)

    tool_executor = AsyncMock()
    context = ContextManager()
    config = MagicMock()
    config.max_agent_steps = 10

    all_tools = [{"name": "browser_navigate", "description": "nav", "input_schema": {}}]

    loop = AgentLoop(
        llm_client=llm_client,
        tool_executor=tool_executor,
        context=context,
        config=config,
        all_tools=all_tools,
    )

    result = await loop.plan("Search for flights")
    assert result == plan_text
    assert len(result) > 0
    tool_executor.execute.assert_not_called()
    usage = loop.get_usage()
    assert usage["input_tokens"] == 200
    assert usage["output_tokens"] == 50
