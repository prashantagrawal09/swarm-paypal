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
