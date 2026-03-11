from __future__ import annotations

import asyncio
import hashlib
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
from agent.presets import PresetManager
from agent.prompts import build_system_prompt, PLAN_PROMPT
from agent.task_context import TaskContext

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
AUDIT_LOG_PATH = DATA_DIR / "agent_log.jsonl"

SENSITIVE_KEY_PATTERNS = {"password", "token", "key", "secret"}

# Loop detection settings
_LOOP_WINDOW = 10
_LOOP_MIN_PATTERN = 2

# Navigation loop detection: max times agent can navigate to similar search URLs
_NAV_LOOP_THRESHOLD = 1

# Stagnation detection: consecutive observe-only steps before warning
_STAGNATION_THRESHOLD = 3

# Plan staleness: steps on same plan step before warning
_PLAN_STALE_THRESHOLD = 8

# Maximum tracked navigation URLs (FIFO)
_NAV_URLS_CAP = 50

# Actions that do NOT change page state (observation-only)
_OBSERVE_ONLY_ACTIONS = frozenset({
    "browser_snapshot", "get_zone", "page_overview",
    "browser_press_key", "recall", "recall_all",
    "browser_take_screenshot", "browser_tab_list",
    "browser_hover",
})

# Budget warning thresholds (fraction of max_steps)
_BUDGET_WARN_50 = 0.50
_BUDGET_WARN_75 = 0.75


class ToolMetrics:
    """Tracks per-tool execution metrics."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def record(self, name: str, elapsed: float, is_error: bool) -> None:
        if name not in self._data:
            self._data[name] = {
                "count": 0, "total_time": 0.0,
                "min_time": float("inf"), "max_time": 0.0,
                "error_count": 0,
            }
        m = self._data[name]
        m["count"] += 1
        m["total_time"] += elapsed
        m["min_time"] = min(m["min_time"], elapsed)
        m["max_time"] = max(m["max_time"], elapsed)
        if is_error:
            m["error_count"] += 1

    def export(self) -> dict[str, dict]:
        result = {}
        for name, m in self._data.items():
            count = m["count"]
            result[name] = {
                "count": count,
                "total_time": round(m["total_time"], 2),
                "avg_time": round(m["total_time"] / count, 2) if count else 0,
                "min_time": round(m["min_time"], 2) if m["min_time"] != float("inf") else 0,
                "max_time": round(m["max_time"], 2),
                "error_count": m["error_count"],
                "error_rate": round(m["error_count"] / count, 2) if count else 0,
            }
        return result


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
        preset_manager: PresetManager | None = None,
    ) -> None:
        self._llm = llm_client
        self._executor = tool_executor
        self._context = context
        self._config = config
        self._all_tools = all_tools
        self._system_prompt = build_system_prompt(config)
        self._preset_manager = preset_manager or PresetManager()
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
        # Loop detection: list of action signatures (name + args_hash)
        self._action_history: list[str] = []
        # Navigation loop detection: track navigate URLs to catch search-page loops
        self._nav_urls: list[str] = []
        # ask_user deduplication
        self._asked_questions: set[str] = set()
        # Budget warning tracking
        self._budget_warned_50: bool = False
        self._budget_warned_75: bool = False
        # Stagnation detection: consecutive steps with only observation actions
        self._consecutive_observe_steps: int = 0
        # Consecutive recall limiter
        self._consecutive_recall_steps: int = 0
        # Plan tracking
        self._plan: list[dict] = []
        self._tasks: list[dict] = []  # hierarchical plan
        self._plan_step_idx: int = 0
        self._plan_last_advance: int = 0
        # Task context file
        self._task_ctx = TaskContext()
        # Tool metrics
        self._tool_metrics = ToolMetrics()

    def _emit(self, event: AgentEvent) -> None:
        if self._on_event:
            self._on_event(event)

    async def _get_response(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        """Get LLM response, using streaming if on_event is set."""
        from agent.llm_client import LLMResponse as LLMResp

        active_tools = tools if tools is not None else self._all_tools

        if self._on_event:
            response: LLMResp | None = None
            async for item in self._llm.send_message_stream(
                messages, self._system_prompt, active_tools
            ):
                if isinstance(item, AgentEvent):
                    self._emit(item)
                else:
                    response = item
            assert response is not None
            return response
        return await self._llm.send_message(
            messages, self._system_prompt, active_tools
        )

    async def run(self, task: str) -> str:
        self._session_id = str(uuid.uuid4())
        self._start_time = time.monotonic()
        self._task = task
        self._success = False
        self._errors_count = 0
        self._action_history.clear()
        self._nav_urls.clear()
        self._asked_questions.clear()
        self._budget_warned_50 = False
        self._budget_warned_75 = False
        self._consecutive_observe_steps = 0
        self._consecutive_recall_steps = 0
        self._plan.clear()
        self._tasks.clear()
        self._plan_step_idx = 0
        self._plan_last_advance = 0
        self._context.set_goal(task)

        # Create task context file for state tracking
        self._task_ctx.create(self._session_id, task)
        # Share processed items reference with tool executor for recall_all
        self._executor._processed_items_ref = self._task_ctx.processed_items

        # Inject available memory keys so the agent knows what data exists
        if self._memory:
            keys = self._memory.list_keys()
            if keys:
                self._context.add_system_note(
                    "📋 Memory keys available (call recall_all() or recall(key) to get values): "
                    + ", ".join(keys)
                )

        # Prompt agent to create a structured plan early
        self._context.add_system_note(
            "📝 After recall_all(), call set_plan(tasks=[{name, subtasks}]) to break the task "
            "into 2-4 tasks with subtasks. Complete ALL subtasks of task 1 before task 2. "
            "Then set_criteria(criteria=[...]) with measurable completion criteria."
        )

        # Check for matching preset
        matched_preset = self._preset_manager.match(task)
        if matched_preset:
            self._context.add_system_note(
                f"📋 PRESET FOUND: \"{matched_preset.name}\"\n"
                f"{matched_preset.to_prompt_injection()}\n"
                "Use this preset's plan as a starting point. Call set_plan() with these steps."
            )

        consecutive_text = 0
        consecutive_errors = 0
        max_steps = self._config.max_agent_steps

        for step_num in range(1, max_steps + 1):
            # Compress old steps if context is too large
            if self._context.estimate_tokens() > 3000:
                await self._context.compress_old_steps(keep_recent=4)

            # --- Budget warnings ---
            progress = step_num / max_steps
            if progress >= _BUDGET_WARN_75 and not self._budget_warned_75:
                self._budget_warned_75 = True
                self._context.add_system_note(
                    f"⚠️ BUDGET WARNING: You have used {step_num}/{max_steps} steps "
                    f"({int(progress*100)}%). Wrap up soon — call done() with results."
                )
            elif progress >= _BUDGET_WARN_50 and not self._budget_warned_50:
                self._budget_warned_50 = True
                self._context.add_system_note(
                    f"📊 Budget: {step_num}/{max_steps} steps used ({int(progress*100)}%). "
                    f"Stay focused on the main goal."
                )

            # --- Loop detection ---
            loop_msg = self._detect_loop()
            if loop_msg:
                self._context.add_system_note(loop_msg)

            # --- Stagnation detection ---
            if self._consecutive_observe_steps >= _STAGNATION_THRESHOLD:
                self._context.add_system_note(
                    f"⚠️ STAGNATION ({self._consecutive_observe_steps} observe steps). "
                    "Extract data from previous reads → remember() → next item or done()."
                )
                self._consecutive_observe_steps = 0  # reset to avoid spam

            # --- Recall spam block: after 2+ consecutive recall-only steps, force action ---
            if self._consecutive_recall_steps >= 2:
                self._context.add_system_note(
                    "🚫 RECALL BLOCKED: You called recall/recall_all 2+ times in a row. "
                    "All data is in your conversation history above. "
                    "STOP recalling and ACT: navigate, remember, or done()."
                )
                self._consecutive_recall_steps = 0

            # --- Plan staleness detection ---
            if (
                self._plan
                and self._plan_step_idx < len(self._plan)
                and step_num - self._plan_last_advance >= _PLAN_STALE_THRESHOLD
            ):
                current_step = self._plan[self._plan_step_idx]["step"]
                self._context.add_system_note(
                    f"⚠️ PLAN STALE: You have been on step {self._plan_step_idx + 1} "
                    f"(\"{current_step}\") for {step_num - self._plan_last_advance} steps. "
                    "Either complete it with complete_plan_step() or change approach."
                )
                self._plan_last_advance = step_num  # reset to avoid spam

            # --- Update plan in context ---
            if self._plan:
                self._context.set_plan_text(self._build_plan_status())

            # --- Update task context summary for LLM ---
            self._context.set_task_context_text(self._task_ctx.get_summary())

            # --- Last step: force-done ---
            is_last_step = step_num == max_steps
            tools_for_step = self._all_tools
            if is_last_step:
                tools_for_step = [
                    t for t in self._all_tools if t["name"] in ("done", "ask_user")
                ]
                self._context.add_system_note(
                    "🛑 LAST STEP! You MUST call done() now with a summary of what was accomplished."
                )

            messages = self._context.build_messages()
            response = await self._get_response(messages, tools=tools_for_step)
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

                # Track action for loop detection
                self._track_action(tc)

                if tc.name == "done":
                    self._success = True
                    self._task_ctx.cleanup()
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

            # --- Track progress vs observation for stagnation detection ---
            step_had_progress = any(
                tc.name not in _OBSERVE_ONLY_ACTIONS
                for tc in response.tool_calls
            )
            if step_had_progress:
                self._consecutive_observe_steps = 0
                self._consecutive_recall_steps = 0
            else:
                self._consecutive_observe_steps += 1
                # Track consecutive recall-only steps specifically
                all_recall = all(
                    tc.name in ("recall", "recall_all")
                    for tc in response.tool_calls
                )
                if all_recall:
                    self._consecutive_recall_steps += 1
                else:
                    self._consecutive_recall_steps = 0

            # --- Auto-done nudge when all completion criteria are met ---
            if self._task_ctx.check_criteria():
                self._context.add_system_note(
                    "✅ ALL COMPLETION CRITERIA ARE MET. Call done() immediately with a summary."
                )

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

        self._task_ctx.cleanup()
        return "Достигнут лимит шагов (limit reached)."

    def get_usage(self) -> dict:
        return {
            "steps": self._total_steps,
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "session_id": self._session_id,
        }

    def get_plan_steps(self) -> list[str]:
        """Return list of plan step descriptions (for preset creation)."""
        return [item["step"] for item in self._plan]

    def get_task(self) -> str:
        """Return the task description."""
        return self._task

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
            "tool_metrics": self._tool_metrics.export(),
        }

    def _track_action(self, tc: ToolCall) -> None:
        """Record action signature for loop detection."""
        args_str = json.dumps(tc.args, sort_keys=True, ensure_ascii=False)
        sig = f"{tc.name}:{hashlib.md5(args_str.encode()).hexdigest()[:8]}"
        self._action_history.append(sig)
        # Keep only recent window
        if len(self._action_history) > _LOOP_WINDOW * 2:
            self._action_history = self._action_history[-_LOOP_WINDOW * 2:]

        # Track navigation URLs for search-loop detection
        if tc.name == "browser_navigate" and "url" in tc.args:
            self._nav_urls.append(tc.args["url"])
            if len(self._nav_urls) > _NAV_URLS_CAP:
                self._nav_urls = self._nav_urls[-_NAV_URLS_CAP:]

    def _detect_loop(self) -> str | None:
        """Check if recent actions form a repeating pattern.

        Returns a nudge message if a loop is detected, None otherwise.
        """
        history = self._action_history
        if len(history) < _LOOP_WINDOW:
            return None

        recent = history[-_LOOP_WINDOW:]

        # Check for repeating patterns of length 1..4
        for pattern_len in range(1, 5):
            if len(recent) < pattern_len * _LOOP_MIN_PATTERN:
                continue
            pattern = recent[-pattern_len:]
            repeats = 0
            for offset in range(pattern_len, len(recent), pattern_len):
                chunk = recent[-(offset + pattern_len):-offset] if offset > 0 else recent[-pattern_len:]
                if offset == 0:
                    continue
                start = len(recent) - offset - pattern_len
                end = len(recent) - offset
                if start < 0:
                    break
                chunk = recent[start:end]
                if chunk == pattern:
                    repeats += 1
                else:
                    break
            if repeats >= _LOOP_MIN_PATTERN:
                return (
                    "🔄 LOOP DETECTED: You are repeating the same actions. "
                    "STOP and try a completely different approach. "
                    "Consider: different element refs, scrolling, navigating to a different page, "
                    "or calling done() if the task is partially complete."
                )

        # Name-only pattern detection (catches semantic loops with varying args)
        name_loop = self._detect_name_pattern_loop()
        if name_loop:
            return name_loop

        # Navigation loop: detect repeated visits to similar search/listing URLs
        nav_loop = self._detect_nav_loop()
        if nav_loop:
            return nav_loop

        return None

    def _detect_nav_loop(self) -> str | None:
        """Detect when the agent keeps navigating to similar search/listing URLs.

        Counts visits to URLs that share the same base path (ignoring query params).
        If the agent visits the same base URL >= _NAV_LOOP_THRESHOLD times,
        it's likely stuck in a search loop.
        Also detects revisits to processed items.
        """
        if len(self._nav_urls) < _NAV_LOOP_THRESHOLD:
            # Still check for processed item revisits even with few URLs
            return self._detect_processed_revisit()

        from urllib.parse import urlparse

        # Check processed item revisits first
        processed_msg = self._detect_processed_revisit()
        if processed_msg:
            return processed_msg

        # Count visits by base URL (scheme + host + path, ignoring query)
        base_counts: dict[str, int] = {}
        for url in self._nav_urls:
            try:
                parsed = urlparse(url)
                base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                base_counts[base] = base_counts.get(base, 0) + 1
            except Exception:
                continue

        for base_url, count in base_counts.items():
            if count >= _NAV_LOOP_THRESHOLD:
                return (
                    f"🔄 NAVIGATION LOOP: You have navigated to '{base_url}' "
                    f"{count} times. STOP revisiting the same URLs! "
                    "You already have data from these pages in your conversation history. "
                    "Extract what you need from previous reads, call remember() + mark_processed(), "
                    "then navigate to a COMPLETELY NEW URL you haven't visited before. "
                    "If you have enough items, call done() with results."
                )

        return None

    def _detect_processed_revisit(self) -> str | None:
        """Detect if the agent is navigating to an already-processed item."""
        from urllib.parse import urlparse

        processed = self._task_ctx.processed_items
        if not processed or not self._nav_urls:
            return None

        last_url = self._nav_urls[-1]
        try:
            last_parsed = urlparse(last_url)
            last_base = f"{last_parsed.scheme}://{last_parsed.netloc}{last_parsed.path}"
        except Exception:
            last_base = last_url

        for item in processed:
            # Extract URL part (before the action in parentheses)
            item_url = item.split(" (")[0] if " (" in item else item
            if not item_url:
                continue
            try:
                item_parsed = urlparse(item_url)
                item_base = f"{item_parsed.scheme}://{item_parsed.netloc}{item_parsed.path}"
            except Exception:
                item_base = item_url
            if item_base == last_base:
                return (
                    f"🚫 REVISITING PROCESSED ITEM: You are navigating to '{last_url}' "
                    f"which was already processed ({item}). "
                    "DO NOT revisit processed items. Move to the next unprocessed item, "
                    "or call done() if all items are processed."
                )
        return None

    def _detect_name_pattern_loop(self) -> str | None:
        """Detect loops using action names only (ignoring args).

        Catches semantic loops like PageDown→Snapshot→Home→Snapshot where
        exact args differ but the pattern of tool names repeats.
        Requires 3+ repetitions to reduce false positives.
        """
        if len(self._action_history) < 6:
            return None

        names = [sig.split(":")[0] for sig in self._action_history[-_LOOP_WINDOW * 2:]]

        for plen in range(2, 5):
            if len(names) < plen * 3:
                continue
            pattern = names[-plen:]
            count = 1
            pos = len(names) - plen * 2
            while pos >= 0:
                if names[pos:pos + plen] == pattern:
                    count += 1
                    pos -= plen
                else:
                    break
            if count >= 3:
                return (
                    f"🔄 PATTERN LOOP: The sequence [{' → '.join(pattern)}] has repeated "
                    f"{count} times. The page state is NOT changing. "
                    "STOP this pattern and try a completely different approach: "
                    "navigate to another page, click a different element, "
                    "or call done() if the task is partially complete."
                )

        return None

    def _build_plan_status(self) -> str:
        """Build a human-readable plan status string for context injection."""
        if self._tasks:
            lines = ["## Your Plan (Tasks → Subtasks)"]
            for ti, task in enumerate(self._tasks):
                task_ctx = self._task_ctx._tasks[ti] if ti < len(self._task_ctx._tasks) else None
                is_done = task_ctx["done"] if task_ctx else False
                marker = "✅" if is_done else "▶"
                lines.append(f"T{ti + 1}. {marker} {task['name']}")
                subtasks = task.get("subtasks", [])
                for si, st in enumerate(subtasks):
                    st_done = task_ctx["subtasks"][si]["done"] if task_ctx and si < len(task_ctx["subtasks"]) else False
                    sm = "✅" if st_done else "○"
                    lines.append(f"  {si + 1}. {sm} {st}")
            return "\n".join(lines)
        if not self._plan:
            return ""
        lines = ["## Your Plan"]
        for i, step in enumerate(self._plan):
            if step["done"]:
                marker = "✅"
            elif i == self._plan_step_idx:
                marker = "▶"
            else:
                marker = "○"
            lines.append(f"{i + 1}. {marker} {step['step']}")
        return "\n".join(lines)

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
            case "set_plan":
                tasks_arg = tc.args.get("tasks")
                steps = tc.args.get("steps", [])
                if tasks_arg:
                    # Hierarchical plan: tasks → subtasks
                    self._plan.clear()
                    self._tasks = tasks_arg  # raw list of {"name", "subtasks"}
                    self._task_ctx.set_tasks(tasks_arg)
                    # Also build flat plan for backward compat tracking
                    for t in tasks_arg:
                        for s in t.get("subtasks", []):
                            self._plan.append({"step": s, "done": False})
                    self._plan_step_idx = 0
                    self._plan_last_advance = step_num
                    self._context.set_plan_text(self._build_plan_status())
                    total_subtasks = sum(len(t.get("subtasks", [])) for t in tasks_arg)
                    focus = self._task_ctx.get_current_focus()
                    result = f"Plan created: {len(tasks_arg)} tasks, {total_subtasks} subtasks. {focus}"
                elif steps:
                    self._tasks = []
                    self._plan = [{"step": s, "done": False} for s in steps]
                    self._plan_step_idx = 0
                    self._plan_last_advance = step_num
                    self._context.set_plan_text(self._build_plan_status())
                    self._task_ctx.set_plan(steps)
                    result = f"Plan created with {len(steps)} steps. Now on step 1: {steps[0]}"
                else:
                    result = "Error: provide 'tasks' (preferred) or 'steps'."
            case "complete_plan_step":
                task_num = tc.args.get("task_number")
                subtask_num = tc.args.get("subtask_number")
                
                if task_num is not None and subtask_num is not None and self._tasks:
                    # Hierarchical completion
                    ti = task_num - 1
                    si = subtask_num - 1
                    if 0 <= ti < len(self._tasks):
                        task_data = self._tasks[ti]
                        subtasks = task_data.get("subtasks", [])
                        if 0 <= si < len(subtasks):
                            self._task_ctx.complete_subtask(ti, si)
                            self._plan_last_advance = step_num
                            self._context.set_plan_text(self._build_plan_status())
                            focus = self._task_ctx.get_current_focus()
                            result = f"Completed T{task_num}.{subtask_num}. {focus}"
                        else:
                            result = f"Invalid subtask number {subtask_num} for task {task_num}."
                    else:
                        result = f"Invalid task number {task_num}."
                elif not self._plan:
                    result = "No plan set. Call set_plan first."
                else:
                    # Flat plan completion (backward compat)
                    target = tc.args.get("step_number")
                    completed_idx: int | None = None
                    if target is not None:
                        idx = target - 1
                        if 0 <= idx < len(self._plan):
                            self._plan[idx]["done"] = True
                            completed_idx = idx
                            while (
                                self._plan_step_idx < len(self._plan)
                                and self._plan[self._plan_step_idx]["done"]
                            ):
                                self._plan_step_idx += 1
                        else:
                            result = f"Invalid step number: {target}. Plan has {len(self._plan)} steps."
                            self._write_audit_log(step_num, tc, result)
                            return result
                    else:
                        if self._plan_step_idx < len(self._plan):
                            completed_idx = self._plan_step_idx
                            self._plan[self._plan_step_idx]["done"] = True
                            self._plan_step_idx += 1
                    self._plan_last_advance = step_num
                    self._context.set_plan_text(self._build_plan_status())
                    if completed_idx is not None:
                        self._task_ctx.complete_step(completed_idx)
                    if self._plan_step_idx < len(self._plan):
                        next_step = self._plan[self._plan_step_idx]["step"]
                        result = f"Step completed. Now on step {self._plan_step_idx + 1}: {next_step}"
                    else:
                        result = "All plan steps completed! Call done() to finish the task."
            case "ask_user":
                question = tc.args.get("question", "")
                # Deduplication: if we already asked this exact question, return cached hint
                normalized_q = question.strip().lower()
                if normalized_q in self._asked_questions:
                    result = (
                        "You already asked this question. "
                        "Use recall() to retrieve the answer from memory, "
                        "or rephrase if you need different information."
                    )
                else:
                    self._asked_questions.add(normalized_q)
                    # Detect CAPTCHA/2FA keywords and emit event
                    _captcha_kw = {"captcha", "recaptcha", "2fa", "verification", "verify"}
                    if any(kw in normalized_q for kw in _captcha_kw):
                        self._emit(AgentEvent(
                            type=EventType.CAPTCHA_DETECTED,
                            data={"question": question},
                        ))
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
            case "mark_processed":
                item_id = tc.args.get("item_id", "")
                action = tc.args.get("action", "")
                self._task_ctx.mark_processed(item_id, action)
                self._executor._processed_items_ref = self._task_ctx.processed_items
                label = f"{item_id} ({action})" if action else item_id
                result = f"Marked as processed: {label}. Do NOT navigate to this item again."
            case "set_criteria":
                criteria = tc.args.get("criteria", [])
                if not criteria:
                    result = "Error: criteria list is empty. Provide measurable criteria."
                else:
                    self._task_ctx.set_criteria(criteria)
                    result = f"Completion criteria set ({len(criteria)} items). Mark each done with mark_criterion_done() as you verify them."
            case "mark_criterion_done":
                num = tc.args.get("criterion_number")
                if num is None:
                    result = "Error: criterion_number is required."
                else:
                    idx = num - 1
                    if 0 <= idx < len(self._task_ctx._criteria):
                        self._task_ctx.mark_criterion_done(idx)
                        text = self._task_ctx._criteria[idx]["text"]
                        result = f"Criterion {num} marked done: {text}"
                        if self._task_ctx.check_criteria():
                            result += "\n✅ ALL CRITERIA MET — call done() now!"
                    else:
                        result = f"Invalid criterion number: {num}."
            case _:
                self._emit(AgentEvent(type=EventType.TOOL_START, data={"name": tc.name, "args": tc.args}))

                # Hard-block revisits: navigating to a URL visited ≥1 time is denied
                if tc.name == "browser_navigate" and "url" in tc.args:
                    visit_count = self._count_url_visits(tc.args["url"])
                    if visit_count >= 1:
                        result = (
                            f"🚫 BLOCKED: URL already visited {visit_count} times. Navigation DENIED. "
                            "You already have the data from this page in your conversation history. "
                            "Use remember(key, value) with data from your PREVIOUS reads, then done()."
                        )
                        self._emit(AgentEvent(type=EventType.TOOL_RESULT, data={
                            "name": tc.name, "result": result[:200], "elapsed": 0, "is_error": True,
                        }))
                        self._write_audit_log(step_num, tc, result)
                        return result

                t0 = time.monotonic()
                try:
                    result = await self._executor.execute(tc)
                except Exception as exc:
                    logger.error("Tool %s failed: %s", tc.name, exc)
                    result = f"[ERROR] {exc}"
                elapsed = time.monotonic() - t0
                is_error = result.startswith("[ERROR]") if result else False
                self._tool_metrics.record(tc.name, elapsed, is_error)

                # Auto mark_processed after remember() — use last navigated URL
                if tc.name == "remember" and not is_error and self._nav_urls:
                    current_url = self._nav_urls[-1]
                    self._task_ctx.mark_processed(current_url, "data_collected")
                    self._executor._processed_items_ref = self._task_ctx.processed_items

                # Warn agent if navigating to already-visited URL
                if tc.name == "browser_navigate" and "url" in tc.args and not is_error:
                    result = self._check_revisit_warning(tc.args["url"], result)
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
            AUDIT_LOG_PATH.parent.mkdir(exist_ok=True)
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Failed to write audit log")

    def _check_revisit_warning(self, url: str, result: str) -> str:
        """Append warning if agent navigates to an already-visited URL."""
        current_norm = self._normalize_url(url)

        for prev_url in self._nav_urls:
            if self._normalize_url(prev_url) == current_norm:
                result += (
                    "\n🚫 REVISIT: You already visited this URL. "
                    "Use data from history. Navigate to a NEW URL or call done()."
                )
                return result

        return result

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for revisit comparison.

        Keeps scheme + host + path + meaningful query param ``page``.
        Strips all tracking/irrelevant query params to prevent bypass.
        """
        from urllib.parse import urlparse, parse_qs, urlencode

        try:
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                qs = parse_qs(parsed.query)
                # Keep only the 'page' param (pagination) — strip tracking params
                kept = {k: v for k, v in qs.items() if k == "page"}
                if kept:
                    base += "?" + urlencode(kept, doseq=True)
            return base
        except Exception:
            return url

    def _count_url_visits(self, url: str) -> int:
        """Count how many times the agent has visited a URL (normalized)."""
        target = self._normalize_url(url)
        count = 0
        for nav_url in self._nav_urls:
            if self._normalize_url(nav_url) == target:
                count += 1
        return count

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
