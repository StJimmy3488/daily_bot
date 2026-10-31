from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    owner_id: int
    # Local dev default; docker-compose points this at its own Postgres service.
    database_url: str = "postgresql+asyncpg://planner:planner@localhost:5432/planner"
    timezone: str = "Europe/Riga"

    # AI is optional: without a key every flow falls back to the regex parser.
    anthropic_api_key: str | None = None
    ai_model: str = "claude-haiku-5-5"
    # Stronger model for the smart day plan.
    ai_plan_model: str = "claude-opus-5-5"

    # Local speech-to-text (faster-whisper): tiny | base | small | medium | large-v3
    whisper_model: str = "small"

    # Public HTTPS address (Caddy terminates TLS) and the in-container web port.
    # PUBLIC_URL defaults to https://<DOMAIN>, so setting DOMAIN is enough.
    domain: str | None = None
    public_url: str = ""
    web_port: int = 8080

    # Google Calendar (optional): OAuth client of type "Web application".
    google_client_id: str | None = None
    google_client_secret: str | None = None

    @model_validator(mode="after")
    def _default_public_url(self) -> "Settings":
        if not self.public_url:
            self.public_url = f"https://{self.domain}" if self.domain else f"http://localhost:{self.web_port}"
        self.public_url = self.public_url.rstrip("/")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
