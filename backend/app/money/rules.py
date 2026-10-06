"""Hard money rules, enforced in code regardless of what any agent or model suggests.

- Spending limit: a shop's committed total for a week never exceeds its weekly limit unless
  the owner approved the excess.
- Supplier floor: no price below the supplier's floor; proposals below it are clamped.
- Stock: no quote for more than the supplier can deliver.
- Captures never exceed the hold; refunds never exceed the capture.
- Holds: capture inside the 3-day honor period; otherwise reauthorize first, which PayPal
  allows from day 3 to day 29 after the original authorization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

HONOR_PERIOD = timedelta(days=3)
AUTHORIZATION_VALIDITY = timedelta(days=29)


class RuleViolation(Exception):
    """A money rule would be broken. `code` is stable and safe to show to agents."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SpendCheck:
    allowed: bool
    limit_cents: int
    committed_cents: int
    requested_cents: int

    @property
    def remaining_cents(self) -> int:
        return max(self.limit_cents - self.committed_cents, 0)

    @property
    def over_by_cents(self) -> int:
        return max(self.committed_cents + self.requested_cents - self.limit_cents, 0)


def check_spend_limit(
    limit_cents: int, committed_cents: int, requested_cents: int, approved_extra_cents: int = 0
) -> SpendCheck:
    """Would committing `requested_cents` more keep the shop inside its weekly limit?

    `approved_extra_cents` is how far over the limit the owner explicitly approved.
    """
    if min(limit_cents, committed_cents, requested_cents, approved_extra_cents) < 0:
        raise ValueError("Amounts must not be negative")
    allowed = committed_cents + requested_cents <= limit_cents + approved_extra_cents
    return SpendCheck(allowed, limit_cents, committed_cents, requested_cents)


def clamp_to_floor(proposed_cents: int, floor_cents: int, *, context: str = "") -> tuple[int, bool]:
    """Return (price, clamped). Prices below the floor are raised to it and logged."""
    if proposed_cents < floor_cents:
        logger.warning(
            "Clamped proposed price %s to floor %s %s", proposed_cents, floor_cents, context
        )
        return floor_cents, True
    return proposed_cents, False


def check_stock(requested_qty: int, stock_limit: int) -> None:
    if requested_qty > stock_limit:
        raise RuleViolation(
            "OUT_OF_STOCK", f"Requested {requested_qty} but only {stock_limit} in stock"
        )


def ensure_capture_within_hold(capture_cents: int, hold_cents: int) -> None:
    if capture_cents < 0:
        raise RuleViolation("NEGATIVE_CAPTURE", "Capture amount cannot be negative")
    if capture_cents > hold_cents:
        raise RuleViolation(
            "CAPTURE_EXCEEDS_HOLD", f"Capture {capture_cents} is more than the hold {hold_cents}"
        )


def ensure_refund_within_capture(
    refund_cents: int, captured_cents: int, refunded_cents: int
) -> None:
    if refund_cents <= 0:
        raise RuleViolation("INVALID_REFUND", "Refund amount must be positive")
    if refunded_cents + refund_cents > captured_cents:
        raise RuleViolation(
            "REFUND_EXCEEDS_CAPTURE",
            f"Refund {refund_cents} would exceed the remaining {captured_cents - refunded_cents}",
        )


def needs_reauthorization(authorized_at: datetime, now: datetime) -> bool:
    """True once the current authorization's 3-day honor period has passed."""
    return now - authorized_at >= HONOR_PERIOD


def can_reauthorize(original_authorized_at: datetime, now: datetime) -> bool:
    age = now - original_authorized_at
    return HONOR_PERIOD <= age <= AUTHORIZATION_VALIDITY


def authorization_expired(original_authorized_at: datetime, now: datetime) -> bool:
    return now - original_authorized_at > AUTHORIZATION_VALIDITY
