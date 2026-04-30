"""
core/config.py — Application settings for LogistiQ AI backend.

All values are read from environment variables or the ``.env`` file.
Use ``.env.example`` as the reference for all required keys.

ALLOWED_ORIGINS is read as a raw string (comma-separated or JSON array):
  CSV:   ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
  JSON:  ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
  Empty or absent → uses the built-in dev defaults below.
"""

from __future__ import annotations

import json
import warnings

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://logistiq:dev_secret_123@localhost:5432/logistiq"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── Security ──────────────────────────────────────────────
    SECRET_KEY: str = "your_secret_key"  # noqa: S105
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── CORS ──────────────────────────────────────────────────
    # Stored as a plain string so pydantic-settings never tries json.loads() on
    # it. Accepts comma-separated or JSON-array format in .env.
    # Access as a list via settings.cors_origins (used in main.py CORSMiddleware).
    ALLOWED_ORIGINS: str = "http://localhost,http://localhost:3000,http://localhost:5173"

    @computed_field  # type: ignore[misc]
    @property
    def cors_origins(self) -> list[str]:
        """Parse ALLOWED_ORIGINS into a list, accepting CSV or JSON-array format."""
        raw = (self.ALLOWED_ORIGINS or "").strip()
        if not raw:
            return ["http://localhost", "http://localhost:3000", "http://localhost:5173"]
        if raw.startswith("["):
            return json.loads(raw)
        return [o.strip() for o in raw.split(",") if o.strip()]

    # ── Razorpay (Billing) ────────────────────────────────────
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_WEBHOOK_SECRET: str | None = None
    RAZORPAY_STARTER_PLAN_ID: str | None = None
    RAZORPAY_PRO_PLAN_ID: str | None = None
    RAZORPAY_ENTERPRISE_PLAN_ID: str | None = None

    # ── External data sources ─────────────────────────────────
    NASA_FIRMS_KEY: str | None = None
    ORS_API_KEY: str | None = None
    FIREBASE_CREDENTIALS_JSON: str | None = None

    # ── Gemini / AI ───────────────────────────────────────────
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # ── Agent configuration ───────────────────────────────────
    PHASE_2_ENABLED: bool = False  # Feature flag to isolate Phase 2 autonomous agents
    RISK_THRESHOLD_DELAY: float = 0.70  # mark DELAYED above this risk score
    RISK_THRESHOLD_CRITICAL: float = 0.85  # trigger emergency reroute above this
    SENTINEL_POLL_INTERVAL_MINUTES: int = 5  # how often sentinel polls shipments
    GDELT_POLL_INTERVAL_MINUTES: int = 10  # how often GDELT news scan runs
    SIMULATION_DEMO_SPEED_MULTIPLIER: float = 100.0
    SIMULATION_DEMO_TICK_SECONDS: float = 1.0

    # ── Environment ───────────────────────────────────────────
    ENVIRONMENT: str = "development"

    # ── Testing ───────────────────────────────────────────────
    # Set TESTING=true in .env or via os.environ in conftest to suppress
    # production-only startup checks (DB ping, Redis ping, engine.dispose).
    TESTING: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in ("production", "prod")

    def model_post_init(self, __context: object) -> None:
        """Warn loudly if obviously insecure defaults are used in production."""
        if self.is_production and self.SECRET_KEY == "your_secret_key":  # noqa: S105
            warnings.warn(
                "SECRET_KEY is the default insecure value in a production environment! "
                "Set a strong random SECRET_KEY in your .env file.",
                stacklevel=2,
            )


settings = Settings()
