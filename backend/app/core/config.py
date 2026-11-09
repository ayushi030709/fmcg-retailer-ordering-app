"""Application settings, loaded from environment variables (see .env.example).

Never commit real values. Every secret has an obviously-unsafe development
default so the app boots locally, and production refuses to start with it.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", description="development | test | production")
    database_url: str = "postgresql+psycopg://fmcg:fmcg@localhost:5432/fmcg_dev"

    jwt_secret_key: str = DEV_JWT_SECRET
    jwt_expires_minutes: int = 12 * 60

    # Comma-separated list of allowed browser origins for CORS.
    frontend_origin: str = "http://localhost:5173"

    # Demo mode: OTP is a fixed, documented reviewer code and is never delivered by SMS.
    demo_mode: bool = True
    demo_otp: str = "123456"
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5

    # AI provider. Any OpenAI-compatible chat-completions endpoint works; Groq is the default.
    ai_provider: str = "groq"
    ai_provider_api_key: str = ""
    ai_model: str = "llama-3.3-70b-versatile"
    ai_base_url: str = "https://api.groq.com/openai/v1"
    ai_timeout_seconds: float = 20.0
    ai_max_message_chars: int = 1000

    # Order validation limits.
    max_qty_per_line: int = 5000
    max_lines_per_order: int = 50

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Render/Heroku style URLs use postgres:// — SQLAlchemy needs an explicit driver.
        if v.startswith("postgres://"):
            v = "postgresql+psycopg://" + v[len("postgres://") :]
        elif v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_provider_api_key.strip()) and self.ai_provider != "fallback"

    def assert_safe_for_production(self) -> None:
        if self.app_env == "production" and self.jwt_secret_key == DEV_JWT_SECRET:
            raise RuntimeError("JWT_SECRET_KEY must be set to a strong random value in production.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
