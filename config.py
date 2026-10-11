from typing import Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Grocy Instance
    grocy_url: str = "http://localhost:9283"
    grocy_api_key: str = ""

    # Grocy MCP Transport ("stdio" or "http")
    grocy_mcp_transport: str = "stdio"
    grocy_mcp_http_url: str = "http://localhost:8000/mcp"

    # Gemini AI
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_max_rpm: int = 60
    gemini_min_interval: float = 0.2

    # Discord Bot
    discord_bot_token: str = ""
    discord_channel_id: Optional[int] = None

    # Google Calendar & Scheduling (Milestone 5)
    google_calendar_credentials_path: Optional[str] = "credentials.json"
    google_calendar_id: str = "primary"
    timezone: str = "America/New_York"

    @field_validator("discord_channel_id", mode="before")
    @classmethod
    def parse_discord_channel_id(cls, v: Any) -> Optional[int]:
        if v is None:
            return None
        v_str = str(v).strip()
        if not v_str or not v_str.isdigit():
            return None
        return int(v_str)


settings = Settings()
