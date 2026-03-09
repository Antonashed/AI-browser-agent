from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent.context import ContextManager, Step


class TestSetGoal:
    def test_set_goal(self):
        ctx = ContextManager()
        ctx.set_goal("Buy a burger")
        msgs = ctx.build_messages()
        assert len(msgs) >= 1
        assert msgs[0]["role"] == "user"
        assert "Buy a burger" in msgs[0]["content"]

    def test_goal_always_first(self):
        ctx = ContextManager()
        ctx.set_goal("Do something")
        ctx.add_step(Step(action="browser_click", result="ok"))
        msgs = ctx.build_messages()
        assert msgs[0]["role"] == "user"
        assert "Do something" in msgs[0]["content"]


class TestAddStep:
    def test_add_step_increases_count(self):
        ctx = ContextManager()
        ctx.set_goal("task")
        assert ctx.get_step_count() == 0
        ctx.add_step(Step(action="browser_navigate", result="done"))
        assert ctx.get_step_count() == 1
        ctx.add_step(Step(action="browser_click", result="clicked"))
        assert ctx.get_step_count() == 2


class TestBuildMessages:
    def test_build_messages_format(self):
        """Messages alternate user/assistant; each step produces
        an assistant message (tool_use) and a user message (tool_result)."""
        ctx = ContextManager()
        ctx.set_goal("task")
        ctx.add_step(Step(action="browser_navigate", result="navigated"))
        msgs = ctx.build_messages()
        # goal (user) + assistant (tool_use) + user (tool_result)
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "user"

    def test_multiple_steps(self):
        ctx = ContextManager()
        ctx.set_goal("task")
        ctx.add_step(Step(action="a1", result="r1"))
        ctx.add_step(Step(action="a2", result="r2"))
        msgs = ctx.build_messages()
        # goal + 2*(assistant + user) = 5
        assert len(msgs) == 5
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "user", "assistant", "user"]


class TestEstimateTokens:
    def test_estimate_tokens_positive(self):
        ctx = ContextManager()
        ctx.set_goal("Research topic")
        ctx.add_step(Step(action="navigate", result="page loaded"))
        assert ctx.estimate_tokens() > 0

    def test_empty_context_zero(self):
        ctx = ContextManager()
        assert ctx.estimate_tokens() == 0


class TestReset:
    def test_reset_clears(self):
        ctx = ContextManager()
        ctx.set_goal("goal")
        ctx.add_step(Step(action="x", result="y"))
        ctx.reset()
        assert ctx.get_step_count() == 0
        # After reset, build_messages returns empty (no goal set)
        assert ctx.build_messages() == []


class TestSetSummary:
    def test_summary_replaces_old_steps(self):
        ctx = ContextManager()
        ctx.set_goal("goal")
        for i in range(5):
            ctx.add_step(Step(action=f"a{i}", result=f"r{i}"))
        ctx.set_summary("Summary of previous steps")
        msgs = ctx.build_messages()
        # Goal message should contain both the goal and the summary
        assert "Summary of previous steps" in msgs[0]["content"]


class TestCompressOldSteps:
    @pytest.mark.asyncio
    async def test_compress_reduces_steps(self):
        ctx = ContextManager()
        ctx.set_goal("task")
        for i in range(15):
            ctx.add_step(Step(action=f"step_{i}", result=f"result_{i}"))

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "Summary: did steps 0-4"
        mock_llm.send_message = AsyncMock(return_value=mock_response)

        await ctx.compress_old_steps(mock_llm, keep_recent=10)
        assert ctx.get_step_count() == 10
        msgs = ctx.build_messages()
        assert "Summary: did steps 0-4" in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_compress_skips_when_few_steps(self):
        ctx = ContextManager()
        ctx.set_goal("task")
        for i in range(5):
            ctx.add_step(Step(action=f"step_{i}", result=f"result_{i}"))

        mock_llm = AsyncMock()
        await ctx.compress_old_steps(mock_llm, keep_recent=10)
        assert ctx.get_step_count() == 5
        mock_llm.send_message.assert_not_called()
