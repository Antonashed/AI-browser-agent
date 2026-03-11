"""Preset system for reusable task templates.

A preset stores a successful task execution pattern (plan, key data, phase hints)
so similar tasks can be executed faster on subsequent runs.
Presets are stored as JSON files in the presets/ directory.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Preset:
    """A reusable task execution template."""

    name: str
    trigger_keywords: list[str] = field(default_factory=list)
    plan_template: list[str] = field(default_factory=list)
    key_data: dict[str, str] = field(default_factory=dict)
    phase_hints: list[str] = field(default_factory=list)
    max_search_steps: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_prompt_injection(self) -> str:
        """Format preset as text for LLM system note injection."""
        lines: list[str] = []
        lines.append(f"## Preset: {self.name}")
        if self.plan_template:
            lines.append("\n### Recommended Plan")
            for i, step in enumerate(self.plan_template, 1):
                lines.append(f"{i}. {step}")
        if self.key_data:
            lines.append("\n### Known Data")
            for k, v in self.key_data.items():
                lines.append(f"- {k}: {v}")
        if self.phase_hints:
            lines.append("\n### Phase Hints")
            for hint in self.phase_hints:
                lines.append(f"- {hint}")
        if self.max_search_steps:
            lines.append(f"\nMax search steps: {self.max_search_steps}")
        return "\n".join(lines)


class PresetManager:
    """Manages preset files in a directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or Path("presets")

    @property
    def directory(self) -> Path:
        return self._dir

    def save(self, preset: Preset) -> Path:
        """Save a preset to a JSON file. Returns the file path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        if not preset.created_at:
            preset.created_at = now
        preset.updated_at = now
        filename = _slugify(preset.name) + ".json"
        path = self._dir / filename
        path.write_text(
            json.dumps(asdict(preset), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, name: str) -> Preset | None:
        """Load a preset by name (filename without .json). Returns None if not found."""
        path = self._dir / f"{_slugify(name)}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Preset(**{k: v for k, v in data.items() if k in Preset.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return None

    def list_presets(self) -> list[str]:
        """Return names of all available presets."""
        if not self._dir.exists():
            return []
        presets: list[str] = []
        for f in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                presets.append(data.get("name", f.stem))
            except (json.JSONDecodeError, KeyError):
                presets.append(f.stem)
        return presets

    def match(self, task: str) -> Preset | None:
        """Find the best-matching preset for a task description.

        Uses keyword overlap scoring: more matching keywords = better match.
        Returns the best match or None if no preset has any keyword overlap.
        """
        if not self._dir.exists():
            return None

        task_lower = task.lower()
        task_words = set(re.findall(r"\w+", task_lower))
        best: Preset | None = None
        best_score = 0

        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                preset = Preset(**{k: v for k, v in data.items() if k in Preset.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                continue

            score = 0
            for kw in preset.trigger_keywords:
                kw_lower = kw.lower()
                # Exact substring match in task
                if kw_lower in task_lower:
                    score += 2
                # Word-level overlap
                elif set(kw_lower.split()) & task_words:
                    score += 1

            if score > best_score:
                best_score = score
                best = preset

        return best if best_score > 0 else None

    def create_from_session(
        self,
        name: str,
        task: str,
        plan: list[str],
        key_data: dict[str, str] | None = None,
        phase_hints: list[str] | None = None,
    ) -> Preset:
        """Create a preset from a completed session's data."""
        # Extract keywords from task
        words = re.findall(r"\w+", task.lower())
        # Filter common stop words
        stop_words = {"на", "и", "в", "по", "для", "не", "что", "как", "мне", "the", "a", "to", "for", "and", "is", "of", "my"}
        keywords = [w for w in words if len(w) > 2 and w not in stop_words]

        preset = Preset(
            name=name,
            trigger_keywords=keywords,
            plan_template=plan,
            key_data=key_data or {},
            phase_hints=phase_hints or [],
        )
        self.save(preset)
        return preset


def _slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug[:80] or "preset"
