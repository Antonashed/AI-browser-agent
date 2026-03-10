from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.config import Config
    from agent.llm_client import LLMClient, LLMResponse, ToolCall
    from agent.memory import Memory
    from agent.tool_executor import ToolExecutor

from agent.context import ContextManager, Step
from agent.events import AgentEvent, EventType
from agent.prompts import build_system_prompt, PLAN_PROMPT

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = Path("agent_log.jsonl")

SENSITIVE_KEY_PATTERNS = {"password", "token", "key", "secret"}


class AgentLoop:
    """ReAct loop: LLM thinks → calls tools → observes results → repeats."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_executor: ToolExecutor,
        context: ContextManager,
        config: Config,
        all_tools: list[dict],
        on_event: Callable[[AgentEvent], None] | None = None,
        memory: Memory | None = None,
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
        self._errors_count: int = 0
        self._on_event = on_event
        self._memory = memory
        self._session_id: str = ""
        self._start_time: float = 0.0
        self._task: str = ""
        self._success: bool = False
        self._escalated: bool = False

    def _emit(self, event: AgentEvent) -> None:
        if self._on_event:
            self._on_event(event)

    async def _get_response(self, messages: list[dict]) -> LLMResponse:
        """Get LLM response, using streaming if on_event is set."""
        from agent.llm_client import LLMResponse as LLMResp

        if self._on_event:
            response: LLMResp | None = None
            async for item in self._llm.send_message_stream(
                messages, self._system_prompt, self._all_tools
            ):
                if isinstance(item, AgentEvent):
                    self._emit(item)
                else:
                    response = item
            assert response is not None
            return response
        return await self._llm.send_message(
            messages, self._system_prompt, self._all_tools
        )

    async def run(self, task: str) -> str:
        self._session_id = str(uuid.uuid4())
        self._start_time = time.monotonic()
        self._task = task
        self._success = False
        self._errors_count = 0
        self._context.set_goal(task)
        consecutive_text = 0
        consecutive_errors = 0

        for step_num in range(1, self._config.max_agent_steps + 1):
            # Compress old steps if context is too large
            if self._context.estimate_tokens() > 6000:
                await self._context.compress_old_steps(keep_recent=4)

            messages = self._context.build_messages()
            response = await self._get_response(messages)
            self._total_input_tokens += response.input_tokens
            self._total_output_tokens += response.output_tokens
            self._total_steps += 1

            if not response.tool_calls:
                consecutive_text += 1
                logger.info("LLM text response (no tools): %s", response.text)
                self._context.add_text_response(response.text or "")
                if consecutive_text >= 5:
                    logger.warning("5 consecutive text-only responses — aborting")
                    return response.text or "Агент не смог выполнить задачу."
                if consecutive_text >= 3:
                    self._context.add_text_response(
                        "Reminder: use a tool to proceed, or call done() to finish."
                    )
                continue

            consecutive_text = 0
            group_id = f"resp_{step_num}"
            step_had_error = False
            for tc in response.tool_calls:
                result = await self._handle_tool_call(tc, step_num)

                if tc.name == "done":
                    self._success = True
                    return tc.args.get("summary", "")

                is_error = result.startswith("[ERROR]") if result else False
                if is_error:
                    step_had_error = True
                    self._errors_count += 1

                self._context.add_step(Step(
                    action=tc.name,
                    result=result,
                    thinking=response.thinking,
                    tool_call_id=tc.id,
                    group_id=group_id,
                    is_error=is_error,
                    args=tc.args,
                ))

            # Auto-escalate to strong model after 3 consecutive errors
            if step_had_error:
                consecutive_errors += 1
                if consecutive_errors >= 3 and not self._escalated and self._config.llm_model_strong:
                    self._llm.set_model(self._config.llm_model_strong)
                    self._escalated = True
                    logger.info("Escalated to strong model: %s", self._config.llm_model_strong)
                    self._emit(AgentEvent(
                        type=EventType.STATUS,
                        data={"text": f"Переключаюсь на сильную модель: {self._config.llm_model_strong}"},
                    ))
                if consecutive_errors >= 5:
                    logger.error("Circuit breaker: 5 consecutive errors — aborting")
                    return "Прервано: слишком много ошибок подряд (circuit breaker)."
            else:
                consecutive_errors = 0

        return "Достигнут лимит шагов (limit reached)."

    def get_usage(self) -> dict:
        return {
            "steps": self._total_steps,
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "session_id": self._session_id,
        }

    def export_metrics(self) -> dict:
        """Export session metrics as a dict."""
        duration = time.monotonic() - self._start_time if self._start_time else 0.0
        return {
            "session_id": self._session_id,
            "task": self._task,
            "steps": self._total_steps,
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "errors_count": self._errors_count,
            "duration_seconds": round(duration, 2),
            "success": self._success,
        }

    def export_audit(self) -> list[dict]:
        """Export audit log entries for current session."""
        entries: list[dict] = []
        if not AUDIT_LOG_PATH.exists():
            return entries
        try:
            with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if entry.get("session_id") == self._session_id:
                        entries.append(entry)
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to read audit log for export")
        return entries

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
                self._emit(AgentEvent(type=EventType.DONE, data={"summary": result}))
            case "ask_user":
                question = tc.args.get("question", "")
                self._emit(AgentEvent(type=EventType.ASK_USER, data={"question": question}))
                if not self._on_event:
                    print(f"\n🤖 Агент спрашивает: {question}")
                result = await asyncio.to_thread(input, "> ")
            case "confirm":
                question = tc.args.get("question", "")
                self._emit(AgentEvent(type=EventType.CONFIRM, data={"question": question}))
                if not self._on_event:
                    print(f"\n⚠️ Подтверждение: {question}")
                answer = await asyncio.to_thread(input, "(да/нет) > ")
                result = "true" if answer.strip().lower() in ("да", "yes", "y", "д") else "false"
            case "show_preview":
                title = tc.args.get("title", "")
                items = tc.args.get("items", [])
                self._emit(AgentEvent(type=EventType.SHOW_PREVIEW, data={"title": title, "items": items}))
                if not self._on_event:
                    print(f"\n📋 {title}")
                    for i, item in enumerate(items, 1):
                        print(f"  {i}. {item}")
                result = "preview_shown"
            case _:
                self._emit(AgentEvent(type=EventType.TOOL_START, data={"name": tc.name, "args": tc.args}))
                t0 = time.monotonic()
                try:
                    result = await self._executor.execute(tc)
                except Exception as exc:
                    logger.error("Tool %s failed: %s", tc.name, exc)
                    result = f"[ERROR] {exc}"
                elapsed = time.monotonic() - t0
                is_error = result.startswith("[ERROR]") if result else False
                self._emit(AgentEvent(type=EventType.TOOL_RESULT, data={
                    "name": tc.name, "result": result[:200], "elapsed": round(elapsed, 1), "is_error": is_error,
                }))

        self._write_audit_log(step_num, tc, result)
        return result

    def _write_audit_log(self, step_num: int, tc: ToolCall, result: str) -> None:
        masked_args = json.dumps(tc.args, ensure_ascii=False)
        masked_args = self._mask_sensitive(masked_args)
        masked_result = self._mask_sensitive(result[:500])
        entry = {
            "session_id": self._session_id,
            "step": step_num,
            "tool": tc.name,
            "args": json.loads(masked_args),
            "result": masked_result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Failed to write audit log")

    def _mask_sensitive(self, text: str) -> str:
        """Replace sensitive values from memory in text with ***MASKED***."""
        if not self._memory:
            return text
        for key in self._memory.list_keys():
            if any(kw in key.lower() for kw in SENSITIVE_KEY_PATTERNS):
                value = self._memory.load(key)
                if value:
                    text = text.replace(value, "***MASKED***")
        return text
