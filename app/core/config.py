"""Application settings loaded from environment variables via pydantic-settings.

A single ``settings`` singleton is created at import time so that the entire
application shares one configuration object.  Every other module should import
``from app.core.config import settings`` rather than reading os.environ directly.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings sourced from the environment (or a .env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        # Ignore extra keys so that docker-compose env_file extras don't cause failures
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str

    # ── JWT / Auth ────────────────────────────────────────────────────────────
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Internal service key ──────────────────────────────────────────────────
    INTERNAL_API_KEY: str

    # ── App runtime ───────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"

    # ── Derived / computed ────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _validate_secret_key_length(self) -> "Settings":
        """Prevent accidentally running with a trivially short secret key."""
        if len(self.SECRET_KEY) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters long. "
                "Generate one with: openssl rand -hex 32"
            )
        return self

    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.ENVIRONMENT.lower() == "production"


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------
settings = Settings()
