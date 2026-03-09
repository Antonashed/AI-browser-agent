from __future__ import annotations

CUSTOM_TOOLS: list[dict] = [
    {
        "name": "remember",
        "description": "Save a key-value pair to persistent memory for later use.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key to store the value under."},
                "value": {"type": "string", "description": "The value to store."},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "recall",
        "description": "Retrieve a value from persistent memory by key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key to look up."},
            },
            "required": ["key"],
        },
    },
    {
        "name": "ask_user",
        "description": "Ask the user a question and wait for their response.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask."},
            },
            "required": ["question"],
        },
    },
    {
        "name": "show_preview",
        "description": "Show a preview list of items to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title for the preview list."},
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of items to display.",
                },
            },
            "required": ["title", "items"],
        },
    },
    {
        "name": "confirm",
        "description": "Ask the user a yes/no confirmation before a destructive or important action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The yes/no question to ask."},
            },
            "required": ["question"],
        },
    },
    {
        "name": "done",
        "description": "Signal that the task is completed and provide a summary of results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary of what was accomplished."},
            },
            "required": ["summary"],
        },
    },
]

_CUSTOM_TOOL_NAMES: set[str] = {t["name"] for t in CUSTOM_TOOLS}


def get_custom_tool_names() -> list[str]:
    return [t["name"] for t in CUSTOM_TOOLS]


def merge_tools(mcp_tools: list[dict]) -> list[dict]:
    filtered = [t for t in mcp_tools if t["name"] not in _CUSTOM_TOOL_NAMES]
    return filtered + list(CUSTOM_TOOLS)
