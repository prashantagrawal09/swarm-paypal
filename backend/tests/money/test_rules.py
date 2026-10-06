"""Hard money rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.money import rules

T0 = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)


def test_spend_limit():
    ok = rules.check_spend_limit(30000, 25000, 5000)
    assert ok.allowed and ok.remaining_cents == 5000 and ok.over_by_cents == 0
    over = rules.check_spend_limit(30000, 25000, 5001)
    assert not over.allowed and over.over_by_cents == 1
    approved = rules.check_spend_limit(30000, 25000, 5001, approved_extra_cents=1)
    assert approved.allowed
    with pytest.raises(ValueError):
        rules.check_spend_limit(-1, 0, 0)


def test_floor_clamp(caplog):
    assert rules.clamp_to_floor(190, 192) == (192, True)
    assert rules.clamp_to_floor(200, 192) == (200, False)
    assert "Clamped" in caplog.text


def test_stock_capture_and_refund_limits():
    rules.check_stock(10, 10)
    with pytest.raises(rules.RuleViolation) as exc:
        rules.check_stock(11, 10)
    assert exc.value.code == "OUT_OF_STOCK"
    rules.ensure_capture_within_hold(1000, 1000)
    with pytest.raises(rules.RuleViolation):
        rules.ensure_capture_within_hold(1001, 1000)
    with pytest.raises(rules.RuleViolation):
        rules.ensure_capture_within_hold(-1, 1000)
    rules.ensure_refund_within_capture(400, 1000, 600)
    with pytest.raises(rules.RuleViolation):
        rules.ensure_refund_within_capture(401, 1000, 600)
    with pytest.raises(rules.RuleViolation):
        rules.ensure_refund_within_capture(0, 1000, 0)


def test_honor_period_and_reauthorization_window():
    assert not rules.needs_reauthorization(T0, T0 + timedelta(days=2, hours=23))
    assert rules.needs_reauthorization(T0, T0 + timedelta(days=3))
    assert not rules.can_reauthorize(T0, T0 + timedelta(days=2))
    assert rules.can_reauthorize(T0, T0 + timedelta(days=3))
    assert rules.can_reauthorize(T0, T0 + timedelta(days=29))
    assert not rules.can_reauthorize(T0, T0 + timedelta(days=29, seconds=1))
    assert rules.authorization_expired(T0, T0 + timedelta(days=30))
