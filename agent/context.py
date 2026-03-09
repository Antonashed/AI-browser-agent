from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.llm_client import LLMClient


@dataclass
class Step:
    action: str | None = None
    result: str | None = None
    thinking: str | None = None
    observation: str | None = None
    tool_call_id: str | None = None


class ContextManager:
    """Maintains conversation history and builds Anthropic-format messages."""

    def __init__(self) -> None:
        self._goal: str | None = None
        self._steps: list[Step] = []
        self._summary: str | None = None

    def set_goal(self, goal: str) -> None:
        self._goal = goal

    def add_step(self, step: Step) -> None:
        self._steps.append(step)

    def get_step_count(self) -> int:
        return len(self._steps)

    def estimate_tokens(self) -> int:
        text = ""
        if self._goal:
            text += self._goal
        if self._summary:
            text += self._summary
        for s in self._steps:
            for val in (s.action, s.result, s.thinking, s.observation):
                if val:
                    text += val
        return len(text) // 4

    def reset(self) -> None:
        self._goal = None
        self._steps.clear()
        self._summary = None

    def set_summary(self, summary: str) -> None:
        self._summary = summary
        self._steps.clear()

    def build_messages(self) -> list[dict]:
        if self._goal is None:
            return []

        messages: list[dict] = []

        # First user message: goal + optional summary
        goal_text = f"Task: {self._goal}"
        if self._summary:
            goal_text += f"\n\nSummary of previous steps:\n{self._summary}"
        messages.append({"role": "user", "content": goal_text})

        # Each step → assistant (tool_use) + user (tool_result)
        for step in self._steps:
            tool_call_id = step.tool_call_id or f"call_{id(step)}"

            assistant_content: list[dict] = []
            if step.thinking:
                assistant_content.append({"type": "text", "text": step.thinking})
            assistant_content.append({
                "type": "tool_use",
                "id": tool_call_id,
                "name": step.action or "unknown",
                "input": {},
            })
            messages.append({"role": "assistant", "content": assistant_content})

            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": step.result or "",
                    }
                ],
            })

        return messages

    async def compress_old_steps(self, llm_client: LLMClient, keep_recent: int = 10) -> None:
        """Summarize old steps via LLM, keeping only the most recent ones."""
        if len(self._steps) <= keep_recent:
            return

        old_steps = self._steps[:-keep_recent]
        recent_steps = self._steps[-keep_recent:]

        old_text = "\n".join(
            f"- {s.action}: {(s.result or '')[:200]}" for s in old_steps
        )

        existing = f"Previous summary:\n{self._summary}\n\n" if self._summary else ""
        prompt = (
            f"{existing}Summarize these agent steps concisely (2-3 sentences):\n{old_text}"
        )

        response = await llm_client.send_message(
            messages=[{"role": "user", "content": prompt}],
            system="You are a concise summarizer. Summarize the agent's steps in 2-3 sentences.",
            tools=[],
        )

        self._summary = response.text or old_text[:500]
        self._steps = recent_steps
