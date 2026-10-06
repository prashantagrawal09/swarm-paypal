"""Enumerations stored in the database (as plain strings with CHECK constraints)."""

from __future__ import annotations

from enum import StrEnum


class PayPalModeEnum(StrEnum):
    REAL = "REAL"
    SIMULATED = "SIMULATED"


class ShopStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class Category(StrEnum):
    """Each group order covers one category, so one supplier can deliver all of it."""

    DAIRY = "DAIRY"
    PANTRY = "PANTRY"
    PRODUCE = "PRODUCE"
    PACKAGING = "PACKAGING"


class ForecastStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    SKIPPED = "SKIPPED"


class GroupOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    COLLECTING = "COLLECTING"
    NEGOTIATING = "NEGOTIATING"
    AWARDED = "AWARDED"
    HELD = "HELD"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
    CANCELLED = "CANCELLED"


class ShopOrderStatus(StrEnum):
    """One shop's part of a group order: the unit that gets one PayPal hold."""

    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class QuoteStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    FINAL = "FINAL"
    AWARDED = "AWARDED"
    LOST = "LOST"


class PaymentKind(StrEnum):
    AUTHORIZATION = "AUTHORIZATION"
    CAPTURE = "CAPTURE"
    VOID = "VOID"
    REAUTHORIZATION = "REAUTHORIZATION"
    REFUND = "REFUND"
    PAYOUT = "PAYOUT"
    SWAP_PAYMENT = "SWAP_PAYMENT"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class InvoiceCheckStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimType(StrEnum):
    SHORT = "SHORT"
    DAMAGED = "DAMAGED"
    EXPIRED = "EXPIRED"
    WRONG_ITEM = "WRONG_ITEM"


class ClaimDecision(StrEnum):
    PENDING = "PENDING"
    AUTO_REFUNDED = "AUTO_REFUNDED"
    REFUNDED = "REFUNDED"
    ESCALATED_SUPPLIER = "ESCALATED_SUPPLIER"
    ESCALATED_OPERATOR = "ESCALATED_OPERATOR"
    REJECTED = "REJECTED"


class SwapKind(StrEnum):
    SURPLUS = "SURPLUS"
    EMERGENCY = "EMERGENCY"


class SwapStatus(StrEnum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class FlashDealStatus(StrEnum):
    OPEN = "OPEN"
    SOLD_OUT = "SOLD_OUT"
    EXPIRED = "EXPIRED"


class ApprovalKind(StrEnum):
    WEEKLY_NEEDS = "WEEKLY_NEEDS"
    OVER_LIMIT = "OVER_LIMIT"
    SUBSTITUTION = "SUBSTITUTION"
    SWAP = "SWAP"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
