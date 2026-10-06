"""Pricing math: tiers, splitting, delivery shares and fees."""

from __future__ import annotations

import pytest

from app.money import pricing
from app.money.pricing import DeliveryStop, InvalidPriceTiers, PriceTier

MILK = pricing.parse_tiers(
    [
        {"min_qty": 1, "unit_price_cents": 260},
        {"min_qty": 50, "unit_price_cents": 225},
        {"min_qty": 200, "unit_price_cents": 205},
    ]
)


@pytest.mark.parametrize(
    ("qty", "price"), [(1, 260), (49, 260), (50, 225), (199, 225), (200, 205), (5000, 205)]
)
def test_tier_unit_price(qty, price):
    assert pricing.tier_unit_price(MILK, qty) == price


def test_tiers_must_be_sane():
    with pytest.raises(InvalidPriceTiers):
        pricing.validate_tiers([])
    with pytest.raises(InvalidPriceTiers):
        pricing.validate_tiers([PriceTier(5, 100)])
    with pytest.raises(InvalidPriceTiers):
        pricing.validate_tiers([PriceTier(1, 100), PriceTier(10, 120)])  # more per unit
    with pytest.raises(InvalidPriceTiers):
        pricing.validate_tiers([PriceTier(1, 100), PriceTier(1, 90)])
    with pytest.raises(ValueError):
        pricing.tier_unit_price(MILK, 0)


def test_next_tier_for_the_price_ladder():
    assert pricing.next_tier(MILK, 120) == PriceTier(200, 205)
    assert pricing.next_tier(MILK, 250) is None


def test_allocate_is_exact_and_deterministic():
    shares = pricing.allocate(1000, {"a": 1, "b": 1, "c": 1})
    assert sum(shares.values()) == 1000
    assert shares == {"a": 334, "b": 333, "c": 333}
    assert pricing.allocate(1000, {"a": 0, "b": 0}) == {"a": 500, "b": 500}
    assert pricing.allocate(0, {}) == {}
    with pytest.raises(ValueError):
        pricing.allocate(5, {})
    with pytest.raises(ValueError):
        pricing.allocate(-1, {"a": 1})


@pytest.mark.parametrize("total", [1, 7, 3500, 4501, 99_999])
def test_allocate_never_loses_a_cent(total):
    weights = {f"shop-{i}": (i * 37) % 11 + 1 for i in range(12)}
    assert sum(pricing.allocate(total, weights).values()) == total


def test_delivery_split_by_weight_and_distance():
    stops = [
        DeliveryStop("near-heavy", 20_000, 1.2850, 103.8320),
        DeliveryStop("near-light", 10_000, 1.2850, 103.8320),
        DeliveryStop("far-light", 10_000, 1.2900, 103.8320),  # about 550 m north
    ]
    shares = pricing.split_delivery_fee(3500, stops)
    assert sum(shares.values()) == 3500
    assert shares["near-heavy"] > shares["near-light"]
    assert shares["far-light"] > shares["near-light"]


def test_delivered_share_shrinks_with_short_delivery():
    assert pricing.delivered_share(300, 10_000, 9_000) == 270
    assert pricing.delivered_share(300, 10_000, 10_000) == 300
    assert pricing.delivered_share(300, 10_000, 0) == 0
    with pytest.raises(ValueError):
        pricing.delivered_share(300, 10_000, 11_000)


def test_platform_fee_rounds_down():
    assert pricing.platform_fee(10_000, 200) == 200
    assert pricing.platform_fee(9_999, 200) == 199
    with pytest.raises(ValueError):
        pricing.platform_fee(100, 10_001)


def test_order_amount_and_savings():
    assert pricing.order_amount([(290, 205), (10, 840)], 150) == 290 * 205 + 8400 + 150
    assert pricing.percent_saved(80, 100) == 20.0
    assert pricing.percent_saved(80, 0) == 0.0


def test_haversine_is_roughly_right():
    # One degree of latitude is about 111 km.
    assert 110_000 < pricing.haversine_m(1.0, 103.8, 2.0, 103.8) < 112_000
