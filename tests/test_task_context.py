"""Tests for TaskContext — temporary per-task context tracking."""

from __future__ import annotations

import pytest
from pathlib import Path

from agent.task_context import TaskContext


@pytest.fixture
def ctx(tmp_path: Path) -> TaskContext:
    return TaskContext(directory=tmp_path)


class TestCreate:
    def test_creates_file(self, ctx: TaskContext, tmp_path: Path) -> None:
        path = ctx.create("abc12345-session", "Find 3 vacancies")
        assert path.exists()
        assert path.name == "task_context_abc12345.md"
        assert path.parent == tmp_path

    def test_file_contains_goal(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "Order pizza")
        content = ctx.path.read_text(encoding="utf-8")
        assert "Order pizza" in content

    def test_initial_phase(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        assert ctx.phase == "init"

    def test_create_resets_state(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "first task")
        ctx.add_data("key1", "val1")
        ctx.mark_processed("item1")
        ctx.create("sess0002", "second task")
        assert ctx.processed_items == []
        summary = ctx.get_summary()
        assert "key1" not in summary
        assert "item1" not in summary


class TestPlan:
    def test_set_plan(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.set_plan(["Step A", "Step B", "Step C"])
        summary = ctx.get_summary()
        assert "Step A" in summary
        assert "Step B" in summary
        assert "Step C" in summary

    def test_set_plan_updates_phase(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.set_plan(["Step A"])
        assert ctx.phase == "planning"

    def test_complete_step(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.set_plan(["Step A", "Step B"])
        ctx.complete_step(0, notes="found 3 items")
        summary = ctx.get_summary()
        assert "✅" in summary
        content = ctx.path.read_text(encoding="utf-8")
        assert "[x]" in content

    def test_complete_step_out_of_range(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.set_plan(["Step A"])
        ctx.complete_step(5)  # should not crash
        content = ctx.path.read_text(encoding="utf-8")
        assert "Step A" in content


class TestKeyData:
    def test_add_data(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.add_data("vacancy_url", "https://hh.ru/vacancy/123")
        summary = ctx.get_summary()
        assert "vacancy_url" in summary
        assert "https://hh.ru/vacancy/123" in summary

    def test_overwrite_data(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.add_data("count", "1")
        ctx.add_data("count", "2")
        summary = ctx.get_summary()
        assert "2" in summary


class TestProcessedItems:
    def test_mark_processed(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.mark_processed("https://hh.ru/vacancy/123", "applied")
        assert len(ctx.processed_items) == 1
        summary = ctx.get_summary()
        assert "DO NOT revisit" in summary
        assert "https://hh.ru/vacancy/123" in summary

    def test_no_duplicates(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.mark_processed("item1", "done")
        ctx.mark_processed("item1", "done")
        assert len(ctx.processed_items) == 1

    def test_multiple_items(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.mark_processed("item1")
        ctx.mark_processed("item2")
        assert len(ctx.processed_items) == 2


class TestPhase:
    def test_set_phase(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        ctx.set_phase("applying")
        assert ctx.phase == "applying"
        summary = ctx.get_summary()
        assert "applying" in summary


class TestGetSummary:
    def test_summary_structure(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "Search vacancies")
        ctx.set_plan(["Search", "Apply", "Report"])
        ctx.add_data("found", "3")
        ctx.mark_processed("v1", "applied")
        ctx.set_phase("apply")

        summary = ctx.get_summary()
        assert "Search vacancies" in summary
        assert "apply" in summary
        assert "Plan" in summary
        assert "Key Data" in summary
        assert "Processed Items" in summary

    def test_summary_empty_plan(self, ctx: TaskContext) -> None:
        ctx.create("sess0001", "task")
        summary = ctx.get_summary()
        assert "Plan" not in summary


class TestCleanup:
    def test_cleanup_removes_file(self, ctx: TaskContext, tmp_path: Path) -> None:
        path = ctx.create("sess0001", "task")
        assert path.exists()
        ctx.cleanup()
        assert not path.exists()
        assert ctx.path is None

    def test_cleanup_no_file(self, ctx: TaskContext) -> None:
        ctx.cleanup()  # should not crash
