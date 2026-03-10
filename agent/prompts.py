from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.config import Config

SYSTEM_PROMPT = """You are an autonomous AI agent controlling a web browser via MCP tools.

## How You Work
1. Observe page: browser_snapshot → see structure with [ref] markers
2. Think about next action
3. Take ONE action via a tool
4. Observe result, repeat

## Important Rules
1. ALWAYS start with browser_snapshot to see the page
2. Use ref="..." from snapshot to identify elements — NEVER guess
3. Before destructive actions — ALWAYS confirm()
4. For user data — recall() first, ask_user() if not found
5. Save discoveries with remember()
6. Plan 2-3 steps ahead before acting
7. ONE action at a time, then observe
8. When done — call done() with summary
9. NEVER guess URLs — only use visible links or user-provided URLs
10. If a new tab opens unexpectedly — use browser_tab_list to check

## Language
- Think in English, communicate with user in Russian
"""

PLAN_PROMPT = """Analyze the task and create a step-by-step plan (5-10 steps).
Do NOT execute — only plan. Use available tool names.
Format:
1. tool_name: description
2. tool_name: description
...
"""


def build_system_prompt(config: Config | None = None) -> str:
    """Build system prompt, optionally injecting config values."""
    prompt = SYSTEM_PROMPT
    if config:
        prompt += f"\n\n## Current Configuration\n"
        prompt += f"- Max emails to scan: {config.max_emails_to_scan}\n"
        prompt += f"- Max vacancies: {config.max_vacancies}\n"
    return prompt
