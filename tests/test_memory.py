from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent.memory import Memory


class TestSaveAndLoad:
    def test_save_and_load(self, tmp_path: Path) -> None:
        fp = tmp_path / "mem.json"
        mem = Memory(filepath=fp)
        mem.save("city", "Moscow")
        assert mem.load("city") == "Moscow"

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        fp = tmp_path / "mem.json"
        mem = Memory(filepath=fp)
        assert mem.load("nonexistent") is None


class TestHasAndDelete:
    def test_has_key(self, tmp_path: Path) -> None:
        fp = tmp_path / "mem.json"
        mem = Memory(filepath=fp)
        assert mem.has("x") is False
        mem.save("x", "1")
        assert mem.has("x") is True

    def test_delete_key(self, tmp_path: Path) -> None:
        fp = tmp_path / "mem.json"
        mem = Memory(filepath=fp)
        mem.save("key", "value")
        mem.delete("key")
        assert mem.has("key") is False
        assert mem.load("key") is None


class TestListKeys:
    def test_list_keys(self, tmp_path: Path) -> None:
        fp = tmp_path / "mem.json"
        mem = Memory(filepath=fp)
        mem.save("a", "1")
        mem.save("b", "2")
        mem.save("c", "3")
        assert sorted(mem.list_keys()) == ["a", "b", "c"]


class TestPersistence:
    def test_data_survives_restart(self, tmp_path: Path) -> None:
        fp = tmp_path / "mem.json"
        mem1 = Memory(filepath=fp)
        mem1.save("login", "admin")

        mem2 = Memory(filepath=fp)
        assert mem2.load("login") == "admin"


class TestEnvDefaults:
    def test_loads_env_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fp = tmp_path / "mem.json"
        monkeypatch.setenv("USER_FULL_NAME", "Ivan Petrov")
        monkeypatch.setenv("USER_EMAIL", "ivan@example.com")

        mem = Memory(filepath=fp, load_env_defaults=True)
        assert mem.load("user_full_name") == "Ivan Petrov"
        assert mem.load("user_email") == "ivan@example.com"

    def test_env_defaults_do_not_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fp = tmp_path / "mem.json"
        # Pre-populate with existing value
        fp.write_text(json.dumps({"user_full_name": "Original Name"}), encoding="utf-8")

        monkeypatch.setenv("USER_FULL_NAME", "New Name")
        mem = Memory(filepath=fp, load_env_defaults=True)
        assert mem.load("user_full_name") == "Original Name"
