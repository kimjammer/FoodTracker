from config import Settings


def test_settings_defaults():
    settings = Settings()
    assert settings.grocy_url == "http://localhost:9283"
    assert settings.grocy_mcp_transport == "stdio"
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.gemini_max_rpm == 60
    assert settings.gemini_min_interval == 0.2


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("GROCY_URL", "http://grocy.internal:80")
    monkeypatch.setenv("GROCY_API_KEY", "test_key_123")
    monkeypatch.setenv("GROCY_MCP_TRANSPORT", "http")
    monkeypatch.setenv("GEMINI_MAX_RPM", "120")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL", "0.1")

    settings = Settings()
    assert settings.grocy_url == "http://grocy.internal:80"
    assert settings.grocy_api_key == "test_key_123"
    assert settings.grocy_mcp_transport == "http"
    assert settings.gemini_max_rpm == 120
    assert settings.gemini_min_interval == 0.1
