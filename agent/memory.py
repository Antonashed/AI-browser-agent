from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class Memory:
    """Persistent key-value store backed by a JSON file."""

    _DEFAULT_PATH = Path("data") / "memory.json"

    def __init__(self, filepath: Path = _DEFAULT_PATH, load_env_defaults: bool = False) -> None:
        self._filepath = filepath
        self._filepath.parent.mkdir(exist_ok=True)
        self._data: dict[str, str] = {}
        self._load_from_file()
        if load_env_defaults:
            self._apply_env_defaults()

    def save(self, key: str, value: str) -> None:
        self._data[key] = value
        self._persist()

    def load(self, key: str) -> str | None:
        return self._data.get(key)

    def has(self, key: str) -> bool:
        return key in self._data

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._persist()

    def list_keys(self) -> list[str]:
        return list(self._data.keys())

    def _persist(self) -> None:
        data = json.dumps(self._data, ensure_ascii=False, indent=2)
        fd, tmp_path = tempfile.mkstemp(
            dir=self._filepath.parent, suffix=".tmp"
        )
        try:
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            fd = -1
            Path(tmp_path).replace(self._filepath)
        except BaseException:
            if fd >= 0:
                os.close(fd)
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def _load_from_file(self) -> None:
        if self._filepath.exists():
            text = self._filepath.read_text(encoding="utf-8")
            self._data = json.loads(text) if text.strip() else {}

    def _apply_env_defaults(self) -> None:
        import os
        env_keys = {
            "USER_FULL_NAME": "user_full_name",
            "USER_PHONE": "user_phone",
            "USER_EMAIL": "user_email",
            "DELIVERY_ADDRESS": "delivery_address",
        }
        changed = False
        for env_key, mem_key in env_keys.items():
            value = os.environ.get(env_key, "").strip()
            if value and not self.has(mem_key):
                self._data[mem_key] = value
                changed = True
        if changed:
            self._persist()
