"""Credential lookup by env prefix and the gateway registry."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.paypal.accounts import (
    GatewayRegistry,
    credentials_for_prefix,
    missing_credential_keys,
    shop_email_key,
)
from app.paypal.client import PayPalClient
from app.paypal.errors import PayPalConfigError
from app.paypal.simulated import SimulatedPayPalClient


def test_credentials_resolve_from_prefix(monkeypatch):
    monkeypatch.setenv("PAYPAL_SUPPLIER_TEST_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_SUPPLIER_TEST_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PAYPAL_SUPPLIER_TEST_EMAIL", "supplier@example.com")
    creds = credentials_for_prefix("PAYPAL_SUPPLIER_TEST")
    assert creds is not None
    assert creds.label == "supplier_test"
    assert creds.email == "supplier@example.com"
    assert "secret" not in repr(creds)


def test_missing_credentials_are_reported_by_name(monkeypatch):
    monkeypatch.setenv("PAYPAL_SUPPLIER_NONE_CLIENT_ID", "")
    assert credentials_for_prefix("PAYPAL_SUPPLIER_NONE") is None
    assert missing_credential_keys("PAYPAL_SUPPLIER_NONE") == [
        "PAYPAL_SUPPLIER_NONE_CLIENT_ID",
        "PAYPAL_SUPPLIER_NONE_CLIENT_SECRET",
    ]


def test_shop_email_key():
    assert shop_email_key("cafe-mei") == "PAYPAL_SHOP_CAFE_MEI_EMAIL"


async def test_registry_builds_one_gateway_per_account_and_mode(monkeypatch):
    monkeypatch.setenv("PAYPAL_SUPPLIER_TEST_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_SUPPLIER_TEST_CLIENT_SECRET", "secret")
    registry = GatewayRegistry(Settings())
    real = registry.gateway("PAYPAL_SUPPLIER_TEST", "REAL")
    assert isinstance(real, PayPalClient)
    assert registry.gateway("PAYPAL_SUPPLIER_TEST", "REAL") is real
    sim = registry.gateway("PAYPAL_SUPPLIER_TEST", "SIMULATED")
    assert isinstance(sim, SimulatedPayPalClient)
    assert sim.state is registry.sim_state
    await registry.aclose()


def test_real_mode_without_credentials_fails_loudly(monkeypatch):
    monkeypatch.setenv("PAYPAL_SUPPLIER_GHOST_CLIENT_ID", "")
    registry = GatewayRegistry(Settings())
    with pytest.raises(PayPalConfigError, match="PAYPAL_SUPPLIER_GHOST_CLIENT_ID"):
        registry.gateway("PAYPAL_SUPPLIER_GHOST", "REAL")


def test_live_environment_is_refused():
    registry = GatewayRegistry(Settings(paypal_env="live"))
    with pytest.raises(PayPalConfigError):
        registry.platform("REAL")
