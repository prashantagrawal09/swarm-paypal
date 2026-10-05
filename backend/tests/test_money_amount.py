"""Tests for the Money value type."""

from __future__ import annotations

import pytest

from app.money.amount import Money


def test_renders_paypal_decimal_strings():
    assert Money(205).to_paypal_value() == "2.05"
    assert Money(7250).to_paypal() == {"currency_code": "SGD", "value": "72.50"}
    assert Money(100, "JPY").to_paypal_value() == "100"


def test_payouts_use_currency_not_currency_code():
    assert Money(300).to_payouts() == {"currency": "SGD", "value": "3.00"}


def test_parses_paypal_strings_exactly():
    assert Money.from_paypal("2.05", "SGD") == Money(205)
    assert Money.from_paypal("10", "SGD") == Money(1000)
    assert Money.from_paypal_amount({"currency": "SGD", "value": "0.10"}) == Money(10)
    with pytest.raises(ValueError):
        Money.from_paypal("2.051", "SGD")
    with pytest.raises(ValueError):
        Money.from_paypal("1.5", "JPY")


def test_arithmetic_is_currency_safe():
    assert Money(200) + Money(55) == Money(255)
    assert Money(205) * 290 == Money(59450)
    assert Money(500) - Money(600) == Money(-100)
    with pytest.raises(ValueError):
        Money(100, "SGD") + Money(100, "USD")
    with pytest.raises(TypeError):
        Money(100) * 1.5  # type: ignore[operator]


def test_rejects_floats_and_bad_currencies():
    with pytest.raises(TypeError):
        Money(2.05)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Money(100, "sgd")


def test_formats_for_people():
    assert Money(7250).format() == "S$72.50"
    assert Money(-205).format() == "-S$2.05"
