"""Temporary per-task context file for tracking goal, plan, progress, and key data."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class TaskContext:
    """Manages a temporary markdown file that tracks task execution state.

    The file contains: goal, plan with checkboxes, completed steps log,
    key data collected during execution, and current phase.
    Deleted after done() unless preserved via /preset.
    """

    _DEFAULT_DIR = Path("data")

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or self._DEFAULT_DIR
        self._path: Path | None = None
        self._goal: str = ""
        self._plan: list[dict] = []  # flat list for backward compat
        self._tasks: list[dict] = []  # hierarchical: [{name, subtasks: [{step, done}], done}]
        self._completed_log: list[str] = []
        self._key_data: dict[str, str] = {}
        self._phase: str = "init"
        self._processed_items: list[str] = []
        self._criteria: list[dict[str, str | bool]] = []

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def processed_items(self) -> list[str]:
        return list(self._processed_items)

    def create(self, session_id: str, task: str) -> Path:
        """Create a new task context file and return its path."""
        self._goal = task
        self._phase = "init"
        self._plan.clear()
        self._tasks.clear()
        self._completed_log.clear()
        self._key_data.clear()
        self._processed_items.clear()
        self._criteria.clear()
        self._dir.mkdir(exist_ok=True)
        self._path = self._dir / f"task_context_{session_id[:8]}.md"
        self._write()
        return self._path

    def set_plan(self, steps: list[str]) -> None:
        """Set or replace the plan steps (flat, backward-compatible)."""
        self._plan = [{"step": s, "done": False} for s in steps]
        if self._phase == "init":
            self._phase = "planning"
        self._write()

    def set_tasks(self, tasks: list[dict]) -> None:
        """Set hierarchical plan: tasks with subtasks.

        Args:
            tasks: list of {"name": str, "subtasks": [str, ...]}
        """
        self._tasks = []
        for t in tasks:
            self._tasks.append({
                "name": t["name"],
                "subtasks": [{"step": s, "done": False} for s in t.get("subtasks", [])],
                "done": False,
            })
        # Also populate flat plan for backward compat
        self._plan = []
        for t in self._tasks:
            for st in t["subtasks"]:
                self._plan.append({"step": st["step"], "done": False})
        if self._phase == "init":
            self._phase = "planning"
        self._write()

    def complete_subtask(self, task_idx: int, subtask_idx: int, notes: str = "") -> None:
        """Mark a subtask as completed (0-based indices)."""
        if 0 <= task_idx < len(self._tasks):
            task = self._tasks[task_idx]
            if 0 <= subtask_idx < len(task["subtasks"]):
                task["subtasks"][subtask_idx]["done"] = True
                label = f"T{task_idx + 1}.{subtask_idx + 1}: {task['subtasks'][subtask_idx]['step']}"
                entry = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] ✅ {label}"
                if notes:
                    entry += f" — {notes}"
                self._completed_log.append(entry)
                # Auto-complete task if all subtasks done
                if all(st["done"] for st in task["subtasks"]):
                    task["done"] = True
                self._write()

    def get_current_focus(self) -> str:
        """Return the current task and subtask the agent should focus on."""
        for ti, task in enumerate(self._tasks):
            if task["done"]:
                continue
            for si, st in enumerate(task["subtasks"]):
                if not st["done"]:
                    return (
                        f"FOCUS: Task {ti + 1} \"{task['name']}\" → "
                        f"subtask {si + 1} \"{st['step']}\". "
                        "Complete ALL subtasks of this task before moving on."
                    )
            # All subtasks done but task not marked — mark it
            task["done"] = True
        return "All tasks completed. Call done()."

    def complete_step(self, step_index: int, notes: str = "") -> None:
        """Mark a plan step as completed (0-based index)."""
        if 0 <= step_index < len(self._plan):
            self._plan[step_index]["done"] = True
            label = self._plan[step_index]["step"]
            entry = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] ✅ Step {step_index + 1}: {label}"
            if notes:
                entry += f" — {notes}"
            self._completed_log.append(entry)
            self._write()

    def add_data(self, key: str, value: str) -> None:
        """Store a key piece of data (URL, form value, result, etc.)."""
        self._key_data[key] = value
        self._write()

    def mark_processed(self, item_id: str, action: str = "") -> None:
        """Mark an item (URL, vacancy, etc.) as fully processed."""
        entry = f"{item_id} ({action})" if action else item_id
        if entry not in self._processed_items:
            self._processed_items.append(entry)
            self._write()

    def set_criteria(self, items: list[str]) -> None:
        """Set measurable completion criteria extracted from the task."""
        self._criteria = [{"text": item, "done": False} for item in items]
        self._write()

    def mark_criterion_done(self, index: int) -> None:
        """Mark a completion criterion as satisfied (0-based index)."""
        if 0 <= index < len(self._criteria):
            self._criteria[index]["done"] = True
            self._write()

    def check_criteria(self) -> bool:
        """Return True if all completion criteria are met (and at least one exists)."""
        return bool(self._criteria) and all(c["done"] for c in self._criteria)

    def set_phase(self, phase: str) -> None:
        """Update the current task phase (e.g. 'search', 'apply', 'done')."""
        self._phase = phase
        self._write()

    def get_summary(self) -> str:
        """Return a compact summary for LLM context injection."""
        lines: list[str] = []
        lines.append(f"Task: {self._goal} | Phase: {self._phase}")

        if self._criteria:
            done_count = sum(1 for c in self._criteria if c["done"])
            remaining = [c["text"] for c in self._criteria if not c["done"]]
            if remaining:
                lines.append(f"Criteria {done_count}/{len(self._criteria)}: TODO: {'; '.join(remaining)}")
            else:
                lines.append(f"Criteria: ALL {len(self._criteria)} MET")

        if self._tasks:
            # Hierarchical plan
            focus = self.get_current_focus()
            lines.append(focus)
            for ti, task in enumerate(self._tasks):
                done_st = sum(1 for st in task["subtasks"] if st["done"])
                total_st = len(task["subtasks"])
                marker = "✅" if task["done"] else "▶" if not task["done"] and (ti == 0 or self._tasks[ti - 1]["done"]) else "○"
                lines.append(f"T{ti + 1}. {marker} {task['name']} ({done_st}/{total_st})")
        elif self._plan:
            parts = []
            for item in self._plan:
                marker = "✅" if item["done"] else "○"
                parts.append(f"{marker} {item['step']}")
            lines.append(f"Plan: {' | '.join(parts)}")

        if self._key_data:
            kv = [f"{k}={v}" for k, v in self._key_data.items()]
            lines.append(f"Key Data: {', '.join(kv)}")

        if self._processed_items:
            lines.append(f"Processed Items (DO NOT revisit): {', '.join(self._processed_items)}")

        return "\n".join(lines)

    def cleanup(self) -> None:
        """Delete the task context file."""
        if self._path and self._path.exists():
            self._path.unlink()
        self._path = None

    def _write(self) -> None:
        """Write current state to the markdown file."""
        if self._path is None:
            return

        lines: list[str] = []
        lines.append(f"# Task Context")
        lines.append(f"**Goal:** {self._goal}")
        lines.append(f"**Phase:** {self._phase}")
        lines.append("")

        if self._criteria:
            done_count = sum(1 for c in self._criteria if c["done"])
            lines.append(f"## Completion Criteria ({done_count}/{len(self._criteria)})")
            for i, c in enumerate(self._criteria):
                check = "x" if c["done"] else " "
                lines.append(f"- [{check}] {i + 1}. {c['text']}")
            lines.append("")

        if self._tasks:
            lines.append("## Tasks")
            for ti, task in enumerate(self._tasks):
                check = "x" if task["done"] else " "
                lines.append(f"### [{check}] Task {ti + 1}: {task['name']}")
                for si, st in enumerate(task["subtasks"]):
                    stcheck = "x" if st["done"] else " "
                    lines.append(f"  - [{stcheck}] {si + 1}. {st['step']}")
            lines.append("")
        elif self._plan:
            lines.append("## Plan")
            for i, item in enumerate(self._plan):
                check = "x" if item["done"] else " "
                lines.append(f"- [{check}] {i + 1}. {item['step']}")
            lines.append("")

        if self._completed_log:
            lines.append("## Completed Steps")
            for entry in self._completed_log:
                lines.append(entry)
            lines.append("")

        if self._key_data:
            lines.append("## Key Data")
            for k, v in self._key_data.items():
                lines.append(f"- **{k}:** {v}")
            lines.append("")

        if self._processed_items:
            lines.append("## Processed Items")
            for item in self._processed_items:
                lines.append(f"- ✅ {item}")
            lines.append("")

        content = "\n".join(lines)
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent, suffix=".tmp"
        )
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = -1
            Path(tmp_path).replace(self._path)
        except BaseException:
            if fd >= 0:
                os.close(fd)
            Path(tmp_path).unlink(missing_ok=True)
            raise
