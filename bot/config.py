from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    owner_id: int
    database_url: str = "sqlite+aiosqlite:///./planner.db"
    timezone: str = "Europe/Riga"

    # AI is optional: without a key every flow falls back to the regex parser.
    anthropic_api_key: str | None = None
    ai_model: str = "claude-haiku-5-5"

    # Local speech-to-text (faster-whisper): tiny | base | small | medium | large-v3
    whisper_model: str = "small"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
