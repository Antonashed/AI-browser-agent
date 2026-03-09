from __future__ import annotations

from dataclasses import field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.llm_client import LLMClient, LLMResponse, ToolCall


class TestToolCallDataclass:
    def test_tool_call_fields(self) -> None:
        tc = ToolCall(id="tc_1", name="browser_click", args={"ref": "e5"})
        assert tc.id == "tc_1"
        assert tc.name == "browser_click"
        assert tc.args == {"ref": "e5"}


class TestLLMResponseDefaults:
    def test_response_defaults(self) -> None:
        resp = LLMResponse()
        assert resp.text is None
        assert resp.thinking is None
        assert resp.tool_calls == []
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0


class TestParseResponse:
    def _make_text_response(self, text: str) -> MagicMock:
        block = MagicMock()
        block.type = "text"
        block.text = text
        resp = MagicMock()
        resp.content = [block]
        resp.usage = MagicMock(input_tokens=10, output_tokens=20)
        return resp

    def _make_tool_response(
        self, tool_id: str, tool_name: str, tool_input: dict, thinking: str | None = None
    ) -> MagicMock:
        blocks = []
        if thinking:
            tb = MagicMock()
            tb.type = "thinking"
            tb.thinking = thinking
            blocks.append(tb)
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = tool_id
        tool_block.name = tool_name
        tool_block.input = tool_input
        blocks.append(tool_block)
        resp = MagicMock()
        resp.content = blocks
        resp.usage = MagicMock(input_tokens=100, output_tokens=200)
        return resp

    def test_parse_text_response(self) -> None:
        client = LLMClient(api_key="test-key", model="test-model")
        raw = self._make_text_response("Hello, world!")
        result = client._parse_response(raw)
        assert result.text == "Hello, world!"
        assert result.tool_calls == []
        assert result.input_tokens == 10
        assert result.output_tokens == 20

    def test_parse_tool_response(self) -> None:
        client = LLMClient(api_key="test-key", model="test-model")
        raw = self._make_tool_response(
            tool_id="tc_42",
            tool_name="browser_click",
            tool_input={"ref": "e5"},
            thinking="I should click the button",
        )
        result = client._parse_response(raw)
        assert result.thinking == "I should click the button"
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "tc_42"
        assert tc.name == "browser_click"
        assert tc.args == {"ref": "e5"}
        assert result.input_tokens == 100
        assert result.output_tokens == 200


@pytest.mark.asyncio
class TestSendMessage:
    async def test_send_message_calls_api(self) -> None:
        mock_response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "OK"
        mock_response.content = [text_block]
        mock_response.usage = MagicMock(input_tokens=5, output_tokens=10)

        with patch("agent.llm_client.anthropic") as mock_anthropic:
            mock_client_instance = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client_instance
            mock_client_instance.messages.create.return_value = mock_response

            client = LLMClient(api_key="sk-test", model="claude-test", max_tokens=1024)
            result = await client.send_message(
                messages=[{"role": "user", "content": "Hi"}],
                system="You are helpful.",
                tools=[{"name": "t", "description": "d", "input_schema": {}}],
            )

            mock_client_instance.messages.create.assert_called_once()
            call_kwargs = mock_client_instance.messages.create.call_args
            assert call_kwargs.kwargs["model"] == "claude-test"
            assert call_kwargs.kwargs["system"] == "You are helpful."
            assert call_kwargs.kwargs["messages"] == [{"role": "user", "content": "Hi"}]
            assert result.text == "OK"
