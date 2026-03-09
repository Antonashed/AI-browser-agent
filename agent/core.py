from __future__ import annotations

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
from agent.prompts import build_system_prompt

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

    async def run(self, task: str) -> str:
        self._context.set_goal(task)

        for step_num in range(1, self._config.max_agent_steps + 1):
            messages = self._context.build_messages()
            response = await self._llm.send_message(
                messages, self._system_prompt, self._all_tools
            )

            if not response.tool_calls:
                logger.info("LLM text response (no tools): %s", response.text)
                continue

            for tc in response.tool_calls:
                result = await self._handle_tool_call(tc, step_num)

                if tc.name == "done":
                    return tc.args.get("summary", "")

                self._context.add_step(Step(
                    action=tc.name,
                    result=result,
                    thinking=response.thinking,
                    tool_call_id=tc.id,
                ))

        return "Достигнут лимит шагов (limit reached)."

    async def _handle_tool_call(self, tc: ToolCall, step_num: int) -> str:
        match tc.name:
            case "done":
                result = tc.args.get("summary", "")
            case "ask_user":
                question = tc.args.get("question", "")
                print(f"\n🤖 Агент спрашивает: {question}")
                result = input("> ")
            case "confirm":
                question = tc.args.get("question", "")
                print(f"\n⚠️ Подтверждение: {question}")
                answer = input("(да/нет) > ")
                result = "true" if answer.strip().lower() in ("да", "yes", "y", "д") else "false"
            case "show_preview":
                title = tc.args.get("title", "")
                items = tc.args.get("items", [])
                print(f"\n📋 {title}")
                for i, item in enumerate(items, 1):
                    print(f"  {i}. {item}")
                result = "preview_shown"
            case _:
                result = await self._executor.execute(tc)

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
