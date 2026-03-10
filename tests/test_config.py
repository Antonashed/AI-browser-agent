import os
import pytest
from agent.config import Config, load_config


class TestLoadConfig:
    """Tests for load_config() and Config dataclass."""

    def test_loads_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        cfg = load_config()
        assert cfg.anthropic_api_key == "sk-test-key"

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            load_config()

    def test_default_values(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        cfg = load_config()
        assert cfg.llm_model == "claude-sonnet-4-20250514"
        assert cfg.llm_max_tokens == 4096
        assert cfg.max_agent_steps == 50
        assert cfg.screenshot_enabled is True
        assert cfg.mcp_browser_command == "npx"
        assert cfg.mcp_browser_args == "@playwright/mcp"
        assert cfg.browser_headless is False
        assert cfg.browser_viewport_width == 1280
        assert cfg.browser_viewport_height == 900
        assert cfg.max_emails_to_scan == 20
        assert cfg.max_vacancies == 5

    def test_custom_values_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-custom")
        monkeypatch.setenv("LLM_MODEL", "claude-opus-4-20250514")
        monkeypatch.setenv("LLM_MAX_TOKENS", "8192")
        monkeypatch.setenv("MAX_AGENT_STEPS", "100")
        monkeypatch.setenv("SCREENSHOT_ENABLED", "false")
        monkeypatch.setenv("MCP_BROWSER_COMMAND", "node")
        monkeypatch.setenv("MCP_BROWSER_ARGS", "@playwright/mcp@latest")
        monkeypatch.setenv("BROWSER_HEADLESS", "true")
        monkeypatch.setenv("BROWSER_VIEWPORT_WIDTH", "1920")
        monkeypatch.setenv("BROWSER_VIEWPORT_HEIGHT", "1080")
        monkeypatch.setenv("MAX_EMAILS_TO_SCAN", "50")
        monkeypatch.setenv("MAX_VACANCIES", "10")
        cfg = load_config()
        assert cfg.anthropic_api_key == "sk-custom"
        assert cfg.llm_model == "claude-opus-4-20250514"
        assert cfg.llm_max_tokens == 8192
        assert cfg.max_agent_steps == 100
        assert cfg.screenshot_enabled is False
        assert cfg.mcp_browser_command == "node"
        assert cfg.mcp_browser_args == "@playwright/mcp@latest"
        assert cfg.browser_headless is True
        assert cfg.browser_viewport_width == 1920
        assert cfg.browser_viewport_height == 1080
        assert cfg.max_emails_to_scan == 50
        assert cfg.max_vacancies == 10


class TestIntValidation:
    """Tests for numeric env var validation."""

    def test_invalid_int_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("LLM_MAX_TOKENS", "not_a_number")
        with pytest.raises(ValueError, match="LLM_MAX_TOKENS must be an integer"):
            load_config()

    def test_invalid_viewport_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("BROWSER_VIEWPORT_WIDTH", "wide")
        with pytest.raises(ValueError, match="BROWSER_VIEWPORT_WIDTH must be an integer"):
            load_config()
