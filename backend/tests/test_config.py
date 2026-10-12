"""Tests for settings helpers."""

from __future__ import annotations

from app.config import Settings, env_value


def test_csv_settings_are_split_and_trimmed():
    settings = Settings(
        real_shop_codes=" cafe-mei, bakery-lim ,,", cors_origins="http://a,http://b"
    )
    assert settings.real_shop_code_list == ["cafe-mei", "bakery-lim"]
    assert settings.cors_origin_list == ["http://a", "http://b"]


def test_paypal_base_url_defaults_to_sandbox():
    assert Settings().paypal_base_url == "https://api-m.sandbox.paypal.com"


def test_env_value_prefers_process_env_and_treats_empty_as_unset(monkeypatch):
    monkeypatch.setenv("SWARM_TEST_KEY", "from-env")
    assert env_value("SWARM_TEST_KEY") == "from-env"
    monkeypatch.setenv("SWARM_TEST_KEY", "")
    assert env_value("SWARM_TEST_KEY") is None


def test_hosting_database_urls_use_the_psycopg_driver():
    for url in ("postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d"):
        assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h:5432/d"
    already = "postgresql+psycopg://u:p@h/d"
    assert Settings(database_url=already).database_url == already


def test_production_problems_are_reported():
    from pydantic import SecretStr

    settings = Settings(
        app_env="production",
        demo_mode=False,
        secret_key=None,
        public_frontend_url="http://localhost:3000",
        telegram_bot_token=SecretStr("t"),
        telegram_webhook_secret=None,
    )
    problems = " ".join(settings.production_problems())
    assert "SECRET_KEY" in problems and "localhost" in problems and "WEBHOOK_SECRET" in problems
    assert Settings(demo_mode=True).production_problems() == []


def test_demo_week_is_a_fixed_monday():
    import pytest
    from pydantic import ValidationError

    assert Settings().demo_week.isoformat() == "2026-10-12"
    with pytest.raises(ValidationError, match="Monday"):
        Settings(demo_week="2026-10-13")
