"""Application configuration using Pydantic Settings."""

from enum import Enum
from functools import lru_cache

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvMode(str, Enum):
    """Application environment mode."""

    dev = "dev"
    prod = "prod"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    # Application
    APP_NAME: str = "CIBIL Dashboard"
    DEBUG: bool = False
    ENV: EnvMode = EnvMode.dev

    # CORS (comma-separated origins, e.g. "http://localhost:3000,https://app.example.com")
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Password reset — frontend page URL; token appended as ?token=...
    RESET_LINK_BASE_URL: str = "http://localhost:3000/reset-password"

    # SMTP (required when ENV=prod; ignored in dev mode where reset link is returned in API response)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: str | None = None
    SMTP_USE_TLS: bool = True

    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    try:
        return Settings()
    except ValidationError as e:
        missing = [
            ".".join(str(part) for part in err.get("loc", ()))
            for err in e.errors()
            if err.get("type") == "missing"
        ]
        if missing:
            missing_sorted = ", ".join(sorted(set(missing)))
            raise RuntimeError(
                f"Missing required environment variable(s): {missing_sorted}. "
                "Set them in the environment or in the .env file."
            ) from e
        raise
