"""Application settings, loaded from environment variables and the repo-root `.env` file.

Secrets never live in code or in the database. Rows that need credentials (for example a
supplier's PayPal app) store only an env-var prefix, resolved here via `env_value`.
"""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Typed view of the configuration. See `.env.example` for what each value means."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://swarm:swarm@localhost:5434/swarm"
    test_database_url: str = "postgresql+psycopg://swarm:swarm@localhost:5434/swarm_test"

    public_backend_url: str = "http://localhost:8000"
    public_frontend_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"

    paypal_env: Literal["sandbox", "live"] = "sandbox"
    paypal_currency: str = "SGD"
    paypal_platform_client_id: str | None = None
    paypal_platform_client_secret: SecretStr | None = None
    paypal_platform_email: str | None = None
    paypal_webhook_id: str | None = None
    platform_fee_bps: int = 200
    real_shop_codes: str = ""

    telegram_bot_token: SecretStr | None = None

    demo_mode: bool = True
    # The Monday the demo world starts on. Fixed, so the demo, the docs and the tests agree.
    demo_week: date = date(2026, 10, 12)
    # Seed the demo world on startup when the database is empty.
    auto_seed: bool = True
    demo_panel_key: SecretStr | None = None
    telegram_webhook_secret: SecretStr | None = None
    # Signs the links Swarm sends owners (connect PayPal). Required when DEMO_MODE=false.
    secret_key: SecretStr | None = None

    @field_validator("demo_week")
    @classmethod
    def _monday(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError("DEMO_WEEK must be a Monday")
        return value

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        """Hosting providers hand out `postgres://` / `postgresql://` URLs; the app talks to
        Postgres through psycopg 3."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    def production_problems(self) -> list[str]:
        """Configuration that is fine for a laptop demo but not for real owners."""
        problems = []
        if not self.demo_mode and (
            self.secret_key is None or not self.secret_key.get_secret_value()
        ):
            problems.append("SECRET_KEY is not set: owner invites and Connect PayPal links are off")
        if self.app_env == "production" and self.public_frontend_url.startswith("http://localhost"):
            problems.append("PUBLIC_FRONTEND_URL still points at localhost")
        if (
            self.app_env == "production"
            and self.telegram_bot_token
            and not self.telegram_webhook_secret
        ):
            problems.append(
                "TELEGRAM_WEBHOOK_SECRET is not set: the bot webhook is unauthenticated"
            )
        return problems

    @property
    def cors_origin_list(self) -> list[str]:
        return _split_csv(self.cors_origins)

    @property
    def real_shop_code_list(self) -> list[str]:
        return _split_csv(self.real_shop_codes)

    @property
    def paypal_base_url(self) -> str:
        if self.paypal_env == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def _env_file_values() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    return {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None}


def env_value(key: str) -> str | None:
    """Look up a raw env var by name: real environment first, then the `.env` file.

    Used for credentials referenced by name from the database (for example
    `PAYPAL_SUPPLIER_FRESHDAIRY` + `_CLIENT_ID`). Empty strings count as unset.
    """
    value = os.environ.get(key)
    if value is None:
        value = _env_file_values().get(key)
    return value or None
