"""Pricing math: tier prices, line totals, delivery-fee splitting and platform fees.

All functions are pure and work in integer cents. Splits use the largest-remainder method,
so the parts always add up exactly to the whole and no cent is created or lost.

Delivery split (documented formula). One truck drops the whole group order in the
neighbourhood. Each shop's share of the delivery fee is proportional to

    weight_grams x (DISTANCE_BASE_M + distance_m)

where `distance_m` is how far the shop is from the drop point (the centre of all stops).
A shop 500 m away pays twice as much per kilo as one at the drop point; a shop ordering
twice the weight pays twice as much. On short delivery the share shrinks in proportion to
the weight that actually arrived.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, TypeVar

K = TypeVar("K", bound=Hashable)

DISTANCE_BASE_M = 500
BPS_DENOMINATOR = 10_000


# ---------------------------------------------------------------------------------------
# Tier prices
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class PriceTier:
    min_qty: int
    unit_price_cents: int


class InvalidPriceTiers(ValueError):
    pass


def parse_tiers(raw: Sequence[Mapping[str, Any]]) -> list[PriceTier]:
    """Parse and validate `[{min_qty, unit_price_cents}, ...]` from the database."""
    tiers = sorted(PriceTier(int(t["min_qty"]), int(t["unit_price_cents"])) for t in raw)
    validate_tiers(tiers)
    return tiers


def validate_tiers(tiers: Sequence[PriceTier]) -> None:
    if not tiers:
        raise InvalidPriceTiers("At least one price tier is required")
    if tiers[0].min_qty != 1:
        raise InvalidPriceTiers("The first tier must start at quantity 1")
    for lower, upper in pairwise(tiers):
        if upper.min_qty <= lower.min_qty:
            raise InvalidPriceTiers("Tier quantities must strictly increase")
        if upper.unit_price_cents > lower.unit_price_cents:
            raise InvalidPriceTiers("Buying more must never cost more per unit")
    if any(tier.unit_price_cents <= 0 for tier in tiers):
        raise InvalidPriceTiers("Unit prices must be positive")


def tier_unit_price(tiers: Sequence[PriceTier], qty: int) -> int:
    """Unit price for buying `qty` units: the tier with the highest min_qty <= qty."""
    if qty <= 0:
        raise ValueError("Quantity must be positive")
    price = tiers[0].unit_price_cents
    for tier in tiers:
        if qty >= tier.min_qty:
            price = tier.unit_price_cents
    return price


def next_tier(tiers: Sequence[PriceTier], qty: int) -> PriceTier | None:
    """The next cheaper tier above `qty`, if any (for the live price ladder)."""
    for tier in tiers:
        if tier.min_qty > qty:
            return tier
    return None


def line_total(unit_price_cents: int, qty: int) -> int:
    if unit_price_cents < 0 or qty < 0:
        raise ValueError("Price and quantity must not be negative")
    return unit_price_cents * qty


# ---------------------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------------------


def allocate(total_cents: int, weights: Mapping[K, int]) -> dict[K, int]:
    """Split `total_cents` in proportion to integer `weights` (largest remainder).

    Deterministic: ties on the remainder go to the key that sorts first (by str()).
    If every weight is zero, the total is split as evenly as possible.
    """
    if total_cents < 0:
        raise ValueError("Cannot allocate a negative amount")
    if any(weight < 0 for weight in weights.values()):
        raise ValueError("Weights must not be negative")
    keys = sorted(weights, key=str)
    if not keys:
        if total_cents:
            raise ValueError("Cannot allocate a non-zero amount to nobody")
        return {}
    weight_sum = sum(weights[key] for key in keys)
    effective = {key: (weights[key] if weight_sum else 1) for key in keys}
    weight_sum = sum(effective.values())

    shares = {key: total_cents * effective[key] // weight_sum for key in keys}
    remainders = {key: total_cents * effective[key] % weight_sum for key in keys}
    leftover = total_cents - sum(shares.values())
    for key in sorted(keys, key=lambda k: (-remainders[k], str(k)))[:leftover]:
        shares[key] += 1
    return shares


@dataclass(frozen=True)
class DeliveryStop:
    key: str
    weight_grams: int
    latitude: float
    longitude: float


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def drop_point(stops: Sequence[DeliveryStop]) -> tuple[float, float]:
    """Centre of the stops (good enough at neighbourhood scale)."""
    return (
        sum(stop.latitude for stop in stops) / len(stops),
        sum(stop.longitude for stop in stops) / len(stops),
    )


def delivery_weights(stops: Sequence[DeliveryStop]) -> dict[str, int]:
    if not stops:
        return {}
    centre_lat, centre_lon = drop_point(stops)
    weights = {}
    for stop in stops:
        distance = round(haversine_m(stop.latitude, stop.longitude, centre_lat, centre_lon))
        weights[stop.key] = stop.weight_grams * (DISTANCE_BASE_M + distance)
    return weights


def split_delivery_fee(fee_cents: int, stops: Sequence[DeliveryStop]) -> dict[str, int]:
    """Each stop's share of one delivery fee (see module docstring for the formula)."""
    return allocate(fee_cents, delivery_weights(stops))


def delivered_share(original_share_cents: int, requested_grams: int, delivered_grams: int) -> int:
    """Delivery share after a short delivery: shrinks with the weight that arrived (floor)."""
    if requested_grams <= 0:
        return 0
    if not 0 <= delivered_grams <= requested_grams:
        raise ValueError("Delivered weight must be between 0 and the requested weight")
    return original_share_cents * delivered_grams // requested_grams


# ---------------------------------------------------------------------------------------
# Totals and fees
# ---------------------------------------------------------------------------------------


def platform_fee(amount_cents: int, fee_bps: int) -> int:
    """Platform fee in cents, rounded down (the supplier keeps the fraction)."""
    if not 0 <= fee_bps <= BPS_DENOMINATOR:
        raise ValueError("Fee must be between 0 and 10000 basis points")
    return amount_cents * fee_bps // BPS_DENOMINATOR


def order_amount(lines: Sequence[tuple[int, int]], delivery_share_cents: int) -> int:
    """Sum of qty x unit price over `(qty, unit_price_cents)` lines, plus the delivery share."""
    return sum(line_total(price, qty) for qty, price in lines) + delivery_share_cents


def percent_saved(paid_cents: int, alone_cents: int) -> float:
    if alone_cents <= 0:
        return 0.0
    return round(100 * (alone_cents - paid_cents) / alone_cents, 1)
