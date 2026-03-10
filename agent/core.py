from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.config import Config
    from agent.llm_client import LLMClient, ToolCall
    from agent.tool_executor import ToolExecutor

from agent.context import ContextManager, Step
from agent.prompts import build_system_prompt, PLAN_PROMPT

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = Path("agent_log.jsonl")


class AgentLoop:
    """ReAct loop: LLM thinks → calls tools → observes results → repeats."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_executor: ToolExecutor,
        context: ContextManager,
        config: Config,
        all_tools: list[dict],
    ) -> None:
        self._llm = llm_client
        self._executor = tool_executor
        self._context = context
        self._config = config
        self._all_tools = all_tools
        self._system_prompt = build_system_prompt(config)
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_steps: int = 0

    async def run(self, task: str) -> str:
        self._context.set_goal(task)

        for step_num in range(1, self._config.max_agent_steps + 1):
            # Compress old steps if context is too large
            if self._context.estimate_tokens() > 15000:
                await self._context.compress_old_steps()

            messages = self._context.build_messages()
            response = await self._llm.send_message(
                messages, self._system_prompt, self._all_tools
            )
            self._total_input_tokens += response.input_tokens
            self._total_output_tokens += response.output_tokens
            self._total_steps += 1

            if not response.tool_calls:
                logger.info("LLM text response (no tools): %s", response.text)
                self._context.add_text_response(response.text or "")
                continue

            group_id = f"resp_{step_num}"
            for tc in response.tool_calls:
                result = await self._handle_tool_call(tc, step_num)

                if tc.name == "done":
                    return tc.args.get("summary", "")

                self._context.add_step(Step(
                    action=tc.name,
                    result=result,
                    thinking=response.thinking,
                    tool_call_id=tc.id,
                    group_id=group_id,
                    is_error=result.startswith("[ERROR]") if result else False,
                ))

        return "Достигнут лимит шагов (limit reached)."

    def get_usage(self) -> dict:
        return {
            "steps": self._total_steps,
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
        }

    async def plan(self, task: str) -> str:
        """Generate an execution plan without running any tools."""
        system = self._system_prompt + "\n\n" + PLAN_PROMPT
        messages = [{"role": "user", "content": f"Task: {task}"}]
        response = await self._llm.send_message(messages, system, self._all_tools)
        self._total_input_tokens += response.input_tokens
        self._total_output_tokens += response.output_tokens
        return response.text or ""

    async def _handle_tool_call(self, tc: ToolCall, step_num: int) -> str:
        match tc.name:
            case "done":
                result = tc.args.get("summary", "")
            case "ask_user":
                question = tc.args.get("question", "")
                print(f"\n🤖 Агент спрашивает: {question}")
                result = await asyncio.to_thread(input, "> ")
            case "confirm":
                question = tc.args.get("question", "")
                print(f"\n⚠️ Подтверждение: {question}")
                answer = await asyncio.to_thread(input, "(да/нет) > ")
                result = "true" if answer.strip().lower() in ("да", "yes", "y", "д") else "false"
            case "show_preview":
                title = tc.args.get("title", "")
                items = tc.args.get("items", [])
                print(f"\n📋 {title}")
                for i, item in enumerate(items, 1):
                    print(f"  {i}. {item}")
                result = "preview_shown"
            case _:
                try:
                    result = await self._executor.execute(tc)
                except Exception as exc:
                    logger.error("Tool %s failed: %s", tc.name, exc)
                    result = f"[ERROR] {exc}"

        self._write_audit_log(step_num, tc, result)
        return result

    def _write_audit_log(self, step_num: int, tc: ToolCall, result: str) -> None:
        entry = {
            "step": step_num,
            "tool": tc.name,
            "args": tc.args,
            "result": result[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Failed to write audit log")
