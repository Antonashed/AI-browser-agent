import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Prevent load_dotenv from loading .env file during tests."""
    monkeypatch.setattr("agent.config.load_dotenv", lambda **kwargs: None)
