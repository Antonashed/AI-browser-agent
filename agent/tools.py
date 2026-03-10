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

COMPOUND_TOOLS: list[dict] = [
    {
        "name": "page_overview",
        "description": "Get a compact overview of the current page structure: semantic zones (banner, navigation, main, etc.) with element counts. Use this first on complex/unknown pages instead of browser_snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_zone",
        "description": "Get the accessibility tree for a specific page zone. Use after page_overview to read a particular zone (e.g. 'main', 'navigation'). Pass 'all' for the full snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "description": "Zone name: 'banner', 'navigation', 'main', 'contentinfo', 'complementary', 'search', 'form', 'region', 'page', or 'all'.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default: 6000).",
                },
            },
            "required": ["zone"],
        },
    },
]

_CUSTOM_TOOL_NAMES: set[str] = {t["name"] for t in CUSTOM_TOOLS}
_COMPOUND_TOOL_NAMES: set[str] = {t["name"] for t in COMPOUND_TOOLS}
_ALL_LOCAL_NAMES: set[str] = _CUSTOM_TOOL_NAMES | _COMPOUND_TOOL_NAMES

# MCP tools actually used by the agent. Others are stripped to save tokens.
_MCP_TOOL_WHITELIST: set[str] = {
    "browser_navigate",
    "browser_click",
    "browser_snapshot",
    "browser_type",
    "browser_tab_list",
    "browser_tab_close",
    "browser_go_back",
    "browser_wait",
    "browser_hover",
    "browser_select_option",
    "browser_press_key",
    "browser_drag",
    "browser_take_screenshot",
}


def get_custom_tool_names() -> list[str]:
    return [t["name"] for t in CUSTOM_TOOLS]


def merge_tools(mcp_tools: list[dict]) -> list[dict]:
    filtered = [t for t in mcp_tools if t["name"] not in _ALL_LOCAL_NAMES]
    return filtered + list(CUSTOM_TOOLS)


def get_all_tools(mcp_tools: list[dict]) -> list[dict]:
    """Merge MCP, custom, and compound tools into one list for the LLM."""
    filtered = [
        t for t in mcp_tools
        if t["name"] not in _ALL_LOCAL_NAMES
        and t["name"] in _MCP_TOOL_WHITELIST
    ]
    return filtered + list(CUSTOM_TOOLS) + list(COMPOUND_TOOLS)
