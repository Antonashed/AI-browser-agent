from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agent.core import AgentLoop, AUDIT_LOG_PATH, SENSITIVE_KEY_PATTERNS
from agent.context import ContextManager
from agent.events import EventType
from agent.llm_client import LLMResponse, ToolCall
from agent.memory import Memory


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


# --- Block 14 Tests ---


@pytest.mark.asyncio
async def test_session_id_in_audit_log(tmp_path, monkeypatch):
    """run() generates a UUID session_id and includes it in every audit log entry."""
    log_file = tmp_path / "agent_log.jsonl"
    monkeypatch.setattr("agent.core.AUDIT_LOG_PATH", log_file)

    responses = [
        LLMResponse(tool_calls=[ToolCall(id="1", name="browser_navigate", args={"url": "https://example.com"})]),
        LLMResponse(tool_calls=[ToolCall(id="2", name="done", args={"summary": "Done"})]),
    ]
    loop, _, _ = _make_loop(responses)
    await loop.run("Test task")

    assert log_file.exists()
    entries = [json.loads(line) for line in log_file.read_text(encoding="utf-8").strip().split("\n")]
    assert len(entries) == 2
    # All entries share the same session_id (UUID format)
    sid = entries[0]["session_id"]
    assert len(sid) == 36  # UUID format
    assert all(e["session_id"] == sid for e in entries)


@pytest.mark.asyncio
async def test_mask_sensitive_in_audit_log(tmp_path, monkeypatch):
    """Sensitive memory values (keys containing 'password', 'token', etc.) are masked in audit log."""
    log_file = tmp_path / "agent_log.jsonl"
    monkeypatch.setattr("agent.core.AUDIT_LOG_PATH", log_file)

    mem_file = tmp_path / "memory.json"
    memory = Memory(filepath=mem_file)
    memory.save("api_token", "SECRET_ABC_123")
    memory.save("user_password", "MyP@ssw0rd")
    memory.save("user_name", "Alice")  # not sensitive key

    responses = [
        LLMResponse(tool_calls=[ToolCall(id="1", name="browser_fill", args={"ref": "5", "value": "SECRET_ABC_123"})]),
        LLMResponse(tool_calls=[ToolCall(id="2", name="done", args={"summary": "Done"})]),
    ]
    llm_client = AsyncMock()
    llm_client.send_message = AsyncMock(side_effect=responses)
    tool_executor = AsyncMock()
    tool_executor.execute = AsyncMock(return_value="filled SECRET_ABC_123 into field")
    context = ContextManager()
    config = MagicMock()
    config.max_agent_steps = 10
    all_tools = []

    loop = AgentLoop(
        llm_client=llm_client,
        tool_executor=tool_executor,
        context=context,
        config=config,
        all_tools=all_tools,
        memory=memory,
    )
    await loop.run("Fill form")

    entries = [json.loads(line) for line in log_file.read_text(encoding="utf-8").strip().split("\n")]
    fill_entry = entries[0]
    # The sensitive value should be masked in args and result
    assert "SECRET_ABC_123" not in json.dumps(fill_entry)
    assert "***MASKED***" in json.dumps(fill_entry)
    # Non-sensitive values remain
    assert "Alice" not in json.dumps(fill_entry)  # wasn't in the tool call anyway


@pytest.mark.asyncio
async def test_export_metrics_structure():
    """export_metrics() returns dict with all required fields."""
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
    await loop.run("Test metrics")

    metrics = loop.export_metrics()
    assert metrics["session_id"]
    assert len(metrics["session_id"]) == 36
    assert metrics["task"] == "Test metrics"
    assert metrics["steps"] == 2
    assert metrics["input_tokens"] == 1100
    assert metrics["output_tokens"] == 250
    assert metrics["errors_count"] == 0
    assert metrics["duration_seconds"] >= 0
    assert metrics["success"] is True


@pytest.mark.asyncio
async def test_export_metrics_failure():
    """export_metrics() reports success=False when agent hits step limit."""
    responses = [
        LLMResponse(tool_calls=[ToolCall(id=str(i), name="browser_click", args={"ref": "1"})]) for i in range(5)
    ]
    loop, _, _ = _make_loop(responses, max_steps=3)
    await loop.run("Failing task")

    metrics = loop.export_metrics()
    assert metrics["success"] is False


@pytest.mark.asyncio
async def test_export_audit(tmp_path, monkeypatch):
    """export_audit() returns only entries for the current session."""
    log_file = tmp_path / "agent_log.jsonl"
    monkeypatch.setattr("agent.core.AUDIT_LOG_PATH", log_file)

    # Pre-write an entry from a "different" session
    old_entry = {"session_id": "old-session", "step": 1, "tool": "browser_click", "args": {}, "result": "ok", "timestamp": "2026-01-01T00:00:00Z"}
    log_file.write_text(json.dumps(old_entry) + "\n", encoding="utf-8")

    responses = [
        LLMResponse(tool_calls=[ToolCall(id="1", name="browser_navigate", args={"url": "https://test.com"})]),
        LLMResponse(tool_calls=[ToolCall(id="2", name="done", args={"summary": "OK"})]),
    ]
    loop, _, _ = _make_loop(responses)
    await loop.run("Audit test")

    audit = loop.export_audit()
    assert len(audit) == 2
    assert all(e["session_id"] == loop._session_id for e in audit)


def test_captcha_keywords_in_prompt():
    """System prompt contains CAPTCHA detection instructions."""
    from agent.prompts import SYSTEM_PROMPT
    prompt_lower = SYSTEM_PROMPT.lower()
    for keyword in ["captcha", "recaptcha", "2fa", "ask_user"]:
        assert keyword in prompt_lower, f"Missing keyword '{keyword}' in system prompt"


def test_payment_stop_in_prompt():
    """System prompt contains payment safety rules."""
    from agent.prompts import SYSTEM_PROMPT
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "payment" in prompt_lower or "checkout" in prompt_lower
    assert "confirm" in prompt_lower


def test_captcha_detected_event_type():
    """CAPTCHA_DETECTED exists in EventType."""
    assert EventType.CAPTCHA_DETECTED.value == "captcha_detected"


def test_sensitive_key_patterns():
    """SENSITIVE_KEY_PATTERNS covers expected keywords."""
    assert "password" in SENSITIVE_KEY_PATTERNS
    assert "token" in SENSITIVE_KEY_PATTERNS
    assert "key" in SENSITIVE_KEY_PATTERNS
    assert "secret" in SENSITIVE_KEY_PATTERNS
