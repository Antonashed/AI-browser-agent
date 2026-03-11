from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MAX_SUMMARY_CHARS = 2000
MAX_RESULT_CHARS = 5000
_MAX_ARG_VALUE_LEN = 200
# Overhead for system prompt + tool definitions (tokens)
_SYSTEM_TOOLS_OVERHEAD = 3500


@dataclass
class Step:
    action: str | None = None
    result: str | None = None
    thinking: str | None = None
    observation: str | None = None
    tool_call_id: str | None = None
    group_id: str | None = None
    is_error: bool = False
    args: dict[str, Any] | None = None


class ContextManager:
    """Maintains conversation history and builds Anthropic-format messages."""

    def __init__(self) -> None:
        self._goal: str | None = None
        self._steps: list[Step] = []
        self._summary: str | None = None
        self._plan_text: str | None = None
        self._task_context_text: str | None = None

    def set_plan_text(self, text: str | None) -> None:
        """Set or clear the plan status text injected into every goal message."""
        self._plan_text = text

    def set_task_context_text(self, text: str | None) -> None:
        """Set or clear the task context summary injected into every goal message."""
        self._task_context_text = text

    def set_goal(self, goal: str) -> None:
        self._goal = goal

    def add_step(self, step: Step) -> None:
        if step.result and len(step.result) > MAX_RESULT_CHARS:
            step.result = step.result[:MAX_RESULT_CHARS] + "\n... [truncated]"
        # Don't store thinking in context — it wastes tokens (LLM already has it)
        step.thinking = None
        self._steps.append(step)

    def add_text_response(self, text: str) -> None:
        """Add a text-only assistant response to the context."""
        self._steps.append(Step(result=text))

    def add_system_note(self, note: str) -> None:
        """Inject a system-level note into context as a text response.

        Appears as an assistant→user exchange so the LLM sees the note.
        """
        self._steps.append(Step(result=f"[SYSTEM] {note}"))

    def get_step_count(self) -> int:
        return len(self._steps)

    def estimate_tokens(self) -> int:
        text = ""
        if self._goal:
            text += self._goal
        if self._summary:
            text += self._summary
        for s in self._steps:
            for val in (s.action, s.result, s.observation):
                if val:
                    text += val
            if s.args:
                text += str(s.args)
        if not text:
            return 0
        return int(len(text) / 3.5) + _SYSTEM_TOOLS_OVERHEAD

    def reset(self) -> None:
        self._goal = None
        self._steps.clear()
        self._summary = None
        self._plan_text = None
        self._task_context_text = None

    def set_summary(self, summary: str) -> None:
        self._summary = summary
        self._steps.clear()

    def build_messages(self) -> list[dict]:
        if self._goal is None:
            return []

        messages: list[dict] = []

        # First user message: goal + optional summary
        goal_text = f"Task: {self._goal}"
        if self._task_context_text:
            goal_text += f"\n\n{self._task_context_text}"
        elif self._plan_text:
            goal_text += f"\n\n{self._plan_text}"
        if self._summary:
            goal_text += f"\n\nSummary of previous steps:\n{self._summary}"
        messages.append({"role": "user", "content": goal_text})

        # Build messages: group tool calls by group_id, handle text responses
        i = 0
        while i < len(self._steps):
            step = self._steps[i]

            # Text-only response (no action)
            if step.action is None:
                messages.append({"role": "assistant", "content": step.result or ""})
                messages.append({"role": "user", "content": "Continue."})
                i += 1
                continue

            # Collect consecutive steps with the same group_id
            group = [step]
            if step.group_id is not None:
                j = i + 1
                while (
                    j < len(self._steps)
                    and self._steps[j].group_id == step.group_id
                    and self._steps[j].action is not None
                ):
                    group.append(self._steps[j])
                    j += 1
                i = j
            else:
                i += 1

            # Build assistant message with tool_use blocks
            assistant_content: list[dict] = []

            user_content: list[dict] = []

            for s in group:
                tool_call_id = s.tool_call_id or f"call_{id(s)}"
                assistant_content.append({
                    "type": "tool_use",
                    "id": tool_call_id,
                    "name": s.action or "unknown",
                    "input": _truncate_args(s.args) if s.args else {},
                })
                tool_result: dict = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": s.result or "",
                }
                if s.is_error:
                    tool_result["is_error"] = True
                user_content.append(tool_result)

            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": user_content})

        return messages

    async def compress_old_steps(self, llm_client: Any = None, keep_recent: int = 7) -> None:
        """Summarize old steps, keeping only the most recent ones.

        Preserves milestone steps (remember calls) to maintain task progress awareness.
        Uses deterministic local summarization by default.
        If llm_client is provided, uses it for summarization instead.
        """
        if len(self._steps) <= keep_recent:
            return

        old_steps = self._steps[:-keep_recent]
        recent_steps = self._steps[-keep_recent:]

        # Extract milestone steps (remember calls) to preserve progress tracking
        milestones = [
            s for s in old_steps
            if s.action == "remember" and s.args
        ]
        milestone_text = ""
        if milestones:
            milestone_lines = [
                f"  - {s.args.get('key', '?')}: {s.args.get('value', '?')}"
                for s in milestones
            ]
            milestone_text = "\nMilestones saved:\n" + "\n".join(milestone_lines)

        if llm_client is not None:
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
            summary_text = (response.text or old_text[:500]) + milestone_text
        else:
            lines = [
                f"Step {i}: {s.action}({(s.result or '')[:100]})"
                for i, s in enumerate(old_steps, 1)
            ]
            summary_text = "\n".join(lines) + milestone_text

        if self._summary and llm_client is None:
            self._summary += "\n" + summary_text
        else:
            self._summary = summary_text

        # Cap summary size to prevent unbounded growth, keeping beginning + end
        if self._summary and len(self._summary) > MAX_SUMMARY_CHARS:
            half = MAX_SUMMARY_CHARS // 2
            head = self._summary[:half].rsplit("\n", 1)[0]
            tail = self._summary[-half:].split("\n", 1)[-1]
            self._summary = head + "\n[...compressed...]\n" + tail

        self._steps = recent_steps


def _truncate_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Truncate long string values in tool args to save tokens."""
    if not args:
        return {}
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > _MAX_ARG_VALUE_LEN:
            out[k] = v[:_MAX_ARG_VALUE_LEN] + "..."
        else:
            out[k] = v
    return out
