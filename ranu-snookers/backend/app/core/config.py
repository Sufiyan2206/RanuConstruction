"""Application configuration.

Every tunable value comes from environment variables (12-factor). Nothing in
here is a secret default that is safe for production: `JWT_SECRET` must be set
explicitly when `ENVIRONMENT=production` (validated at startup).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general ---------------------------------------------------------
    APP_NAME: str = "RANU Club Management Platform"
    ENVIRONMENT: str = "development"  # development | test | staging | production
    LOG_LEVEL: str = "INFO"
    API_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:8080"
    PUBLIC_BASE_URL: str = "http://localhost:8080"

    # --- persistence -----------------------------------------------------
    # postgresql+psycopg://user:pass@host/db  |  mysql+pymysql://user:pass@host/db  |  sqlite:///./dev.db
    DATABASE_URL: str = "sqlite:///./ranu_dev.db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False
    REDIS_URL: str | None = None

    # --- auth ------------------------------------------------------------
    JWT_SECRET: str = "change-me-dev-only-secret-key-please-32b"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 14
    COOKIE_SECURE: bool = False
    COOKIE_DOMAIN: str | None = None

    # --- rate limiting -----------------------------------------------------
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PUBLIC_PER_MINUTE: int = 60
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10

    # --- payments ----------------------------------------------------------
    PAYMENT_PROVIDER: str = "mock"  # mock | razorpay | stripe
    PAYMENT_KEY: str = ""
    PAYMENT_SECRET: str = ""
    PAYMENT_WEBHOOK_SECRET: str = "dev-webhook-secret"
    CURRENCY: str = "INR"

    # --- object storage (receipts, exports) -------------------------------
    STORAGE_BUCKET: str = ""
    STORAGE_ENDPOINT: str = ""
    STORAGE_ACCESS_KEY: str = ""
    STORAGE_SECRET_KEY: str = ""

    # --- notifications -----------------------------------------------------
    EMAIL_PROVIDER: str = "console"  # console | smtp
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@ranusnookers.local"
    SMS_PROVIDER: str = "console"  # console | http
    SMS_HTTP_URL: str = ""
    SMS_API_KEY: str = ""
    WHATSAPP_PROVIDER: str = "console"  # console | meta
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_ID: str = ""

    # --- devices -------------------------------------------------------------
    DEVICE_SIGNATURE_TOLERANCE_SECONDS: int = 300
    DEVICE_OFFLINE_AFTER_SECONDS: int = 90

    # --- workers ---------------------------------------------------------------
    WORKER_TICK_SECONDS: int = 15
    RUN_EMBEDDED_WORKER: bool = False  # true => run scheduler inside API process (single-node/dev)

    SEED_DEMO_DATA: bool = False

    trusted_proxies: list[str] = Field(default_factory=list)

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        """Managed hosts hand out `postgres://` / `postgresql://`; SQLAlchemy needs the psycopg 3 driver name."""
        if isinstance(v, str):
            v = v.strip()
            for old in ("postgres://", "postgresql://"):
                if v.startswith(old):
                    return "postgresql+psycopg://" + v[len(old):]
        return v

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.ENVIRONMENT == "production":
            if self.JWT_SECRET.startswith("change-me") or len(self.JWT_SECRET) < 32:
                raise ValueError("JWT_SECRET must be set to a strong value (>=32 chars) in production")
            if self.DATABASE_URL.startswith("sqlite"):
                raise ValueError("SQLite is not supported in production; use PostgreSQL or MySQL")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
