"""Agent event system for streaming UI updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    ASK_USER = "ask_user"
    CONFIRM = "confirm"
    SHOW_PREVIEW = "show_preview"
    CAPTCHA_DETECTED = "captcha_detected"
    DONE = "done"
    ERROR = "error"
    STATUS = "status"


@dataclass
class AgentEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
