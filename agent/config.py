from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Config:
    anthropic_api_key: str
    llm_model: str = "claude-sonnet-4-20250514"
    llm_max_tokens: int = 4096
    max_agent_steps: int = 50
    screenshot_enabled: bool = True
    mcp_browser_command: str = "npx"
    mcp_browser_args: str = "@playwright/mcp"
    browser_headless: bool = False
    browser_viewport_width: int = 1280
    browser_viewport_height: int = 900
    browser_storage_path: str = ""
    cdp_endpoint: str = "http://localhost:9222"
    max_emails_to_scan: int = 20
    max_vacancies: int = 5


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def _parse_int(value: str, name: str, default: int) -> int:
    stripped = value.strip()
    if not stripped:
        return default
    try:
        return int(stripped)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got: {value!r}")


def _parse_cdp_endpoint(value: str) -> str:
    """Return empty string for 'none' (= MCP launches own browser), otherwise the endpoint URL."""
    stripped = value.strip()
    if stripped.lower() == "none":
        return ""
    return stripped


def load_config() -> Config:
    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set or empty")

    return Config(
        anthropic_api_key=api_key,
        llm_model=os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514"),
        llm_max_tokens=_parse_int(os.environ.get("LLM_MAX_TOKENS", "4096"), "LLM_MAX_TOKENS", 4096),
        max_agent_steps=_parse_int(os.environ.get("MAX_AGENT_STEPS", "50"), "MAX_AGENT_STEPS", 50),
        screenshot_enabled=_parse_bool(os.environ.get("SCREENSHOT_ENABLED", "true")),
        mcp_browser_command=os.environ.get("MCP_BROWSER_COMMAND", "npx"),
        mcp_browser_args=os.environ.get("MCP_BROWSER_ARGS", "@playwright/mcp"),
        browser_headless=_parse_bool(os.environ.get("BROWSER_HEADLESS", "false")),
        browser_viewport_width=_parse_int(os.environ.get("BROWSER_VIEWPORT_WIDTH", "1280"), "BROWSER_VIEWPORT_WIDTH", 1280),
        browser_viewport_height=_parse_int(os.environ.get("BROWSER_VIEWPORT_HEIGHT", "900"), "BROWSER_VIEWPORT_HEIGHT", 900),
        browser_storage_path=os.environ.get("BROWSER_STORAGE_PATH", "").strip(),
        cdp_endpoint=_parse_cdp_endpoint(os.environ.get("CDP_ENDPOINT", "http://localhost:9222")),
        max_emails_to_scan=_parse_int(os.environ.get("MAX_EMAILS_TO_SCAN", "20"), "MAX_EMAILS_TO_SCAN", 20),
        max_vacancies=_parse_int(os.environ.get("MAX_VACANCIES", "5"), "MAX_VACANCIES", 5),
    )
