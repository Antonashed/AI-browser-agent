"""Tests for PresetManager — preset save, load, match, create_from_session."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from agent.presets import Preset, PresetManager, _slugify


@pytest.fixture
def pm(tmp_path: Path) -> PresetManager:
    return PresetManager(directory=tmp_path / "presets")


class TestSaveAndLoad:
    def test_save_creates_file(self, pm: PresetManager) -> None:
        preset = Preset(name="hh job search", trigger_keywords=["hh.ru", "вакансии"])
        path = pm.save(preset)
        assert path.exists()
        assert path.suffix == ".json"

    def test_save_sets_timestamps(self, pm: PresetManager) -> None:
        preset = Preset(name="test")
        pm.save(preset)
        loaded = pm.load("test")
        assert loaded is not None
        assert loaded.created_at != ""
        assert loaded.updated_at != ""

    def test_load_existing(self, pm: PresetManager) -> None:
        preset = Preset(
            name="hh job search",
            trigger_keywords=["hh.ru", "вакансии", "AI engineer"],
            plan_template=["Search", "Apply", "Report"],
            key_data={"site": "hh.ru"},
        )
        pm.save(preset)
        loaded = pm.load("hh job search")
        assert loaded is not None
        assert loaded.name == "hh job search"
        assert loaded.trigger_keywords == ["hh.ru", "вакансии", "AI engineer"]
        assert loaded.plan_template == ["Search", "Apply", "Report"]
        assert loaded.key_data == {"site": "hh.ru"}

    def test_load_nonexistent(self, pm: PresetManager) -> None:
        assert pm.load("nope") is None

    def test_load_corrupt_json(self, pm: PresetManager) -> None:
        pm.directory.mkdir(parents=True, exist_ok=True)
        (pm.directory / "bad.json").write_text("{invalid", encoding="utf-8")
        assert pm.load("bad") is None


class TestListPresets:
    def test_empty(self, pm: PresetManager) -> None:
        assert pm.list_presets() == []

    def test_lists_names(self, pm: PresetManager) -> None:
        pm.save(Preset(name="Alpha"))
        pm.save(Preset(name="Beta"))
        names = pm.list_presets()
        assert "Alpha" in names
        assert "Beta" in names
        assert len(names) == 2


class TestMatch:
    def test_match_by_keyword(self, pm: PresetManager) -> None:
        pm.save(Preset(name="hh search", trigger_keywords=["hh.ru", "вакансии", "AI engineer"]))
        pm.save(Preset(name="kwork", trigger_keywords=["kwork", "фриланс"]))

        result = pm.match("Найди вакансии AI engineer на hh.ru")
        assert result is not None
        assert result.name == "hh search"

    def test_match_no_keywords(self, pm: PresetManager) -> None:
        pm.save(Preset(name="kwork", trigger_keywords=["kwork", "фриланс"]))
        result = pm.match("Закажи пиццу")
        assert result is None

    def test_match_empty_dir(self, pm: PresetManager) -> None:
        assert pm.match("anything") is None

    def test_match_prefers_higher_score(self, pm: PresetManager) -> None:
        pm.save(Preset(name="generic", trigger_keywords=["вакансии"]))
        pm.save(Preset(name="specific", trigger_keywords=["hh.ru", "вакансии", "AI engineer"]))
        result = pm.match("Найди 3 вакансии AI engineer на hh.ru")
        assert result is not None
        assert result.name == "specific"


class TestCreateFromSession:
    def test_creates_and_saves(self, pm: PresetManager) -> None:
        preset = pm.create_from_session(
            name="Job Application",
            task="Найди 3 вакансии AI engineer на hh.ru и откликнись",
            plan=["Search hh.ru", "Open vacancies", "Apply", "Report"],
            key_data={"site": "hh.ru"},
            phase_hints=["Stop searching after 3 vacancies"],
        )
        assert preset.name == "Job Application"
        assert len(preset.trigger_keywords) > 0
        assert "hh" not in preset.trigger_keywords  # too short (len <= 2)
        assert "вакансии" in preset.trigger_keywords
        assert preset.plan_template == ["Search hh.ru", "Open vacancies", "Apply", "Report"]

        loaded = pm.load("Job Application")
        assert loaded is not None
        assert loaded.plan_template == preset.plan_template


class TestPresetPromptInjection:
    def test_to_prompt_injection(self) -> None:
        preset = Preset(
            name="test",
            plan_template=["Step 1", "Step 2"],
            key_data={"url": "https://example.com"},
            phase_hints=["Stop after 3 items"],
            max_search_steps=10,
        )
        text = preset.to_prompt_injection()
        assert "Recommended Plan" in text
        assert "Step 1" in text
        assert "Known Data" in text
        assert "https://example.com" in text
        assert "Phase Hints" in text
        assert "Max search steps: 10" in text


class TestSlugify:
    def test_basic(self) -> None:
        assert _slugify("Hello World") == "hello_world"

    def test_cyrillic(self) -> None:
        result = _slugify("Поиск вакансий")
        assert "поиск" in result
        assert "вакансий" in result

    def test_special_chars(self) -> None:
        assert _slugify("test!@#name") == "testname"

    def test_empty(self) -> None:
        assert _slugify("!!!") == "preset"
