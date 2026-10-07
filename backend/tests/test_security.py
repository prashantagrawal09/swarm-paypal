"""Signed owner links: Telegram invites and Connect PayPal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.security import LinkError, parse_invite, sign, telegram_invite, verify

NOW = datetime(2026, 10, 12, 8, tzinfo=UTC)
SETTINGS = Settings(secret_key=SecretStr("test-secret"))


def test_tokens_verify_only_for_their_shop_purpose_and_lifetime():
    token = sign(SETTINGS, "cafe-mei", NOW, "connect")
    verify(SETTINGS, "cafe-mei", token, NOW + timedelta(hours=1), "connect")
    with pytest.raises(LinkError, match="valid"):
        verify(SETTINGS, "bakery-lim", token, NOW, "connect")
    with pytest.raises(LinkError, match="valid"):
        verify(SETTINGS, "cafe-mei", token, NOW, "telegram")
    with pytest.raises(LinkError, match="expired"):
        verify(SETTINGS, "cafe-mei", token, NOW + timedelta(days=3), "connect")
    other = Settings(secret_key=SecretStr("another-secret"))
    with pytest.raises(LinkError, match="valid"):
        verify(other, "cafe-mei", token, NOW, "connect")
    for broken in (None, "", "abc", "123_", "_deadbeef"):
        with pytest.raises(LinkError):
            verify(SETTINGS, "cafe-mei", broken, NOW, "connect")


def test_invites_fit_telegram_and_round_trip():
    payload = telegram_invite(SETTINGS, "auntie-rose-kitchen", NOW)
    assert len(payload) <= 64
    assert all(c.isalnum() or c in "-_" for c in payload)
    assert parse_invite(SETTINGS, payload, NOW) == "auntie-rose-kitchen"
    forged = payload.replace("auntie-rose-kitchen", "cafe-mei")
    with pytest.raises(LinkError):
        parse_invite(SETTINGS, forged, NOW)


def test_links_are_off_without_a_secret():
    with pytest.raises(LinkError, match="SECRET_KEY"):
        sign(Settings(secret_key=None), "cafe-mei", NOW, "connect")
