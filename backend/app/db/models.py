"""ORM models: the Swarm data model (SWARM_SPEC section 5, with the refinements noted below).

Money is always integer minor units (`*_cents`) plus a currency code; never floats.

Refinements to the spec's table list (see docs/architecture.md, "Data model"):
- `shop_orders` is one shop's part of a group order. It carries the PayPal hold, so a shop gets
  one authorization per group order rather than one per item; `group_order_lines` hold the
  per-item quantities and agreed prices beneath it. The spec's "line (per shop)" state machine
  lives on `shop_orders`.
- `purchase_history` stores the generated weekly orders from before Swarm (the baseline for
  "savings versus buying alone" and for demand prediction).
- `approval_requests` holds questions for owners (confirm needs, over the spending limit...).
- `app_state` is a small key/value store for the Swarm Clock and the simulator snapshot.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.enums import (
    ApprovalKind,
    ApprovalStatus,
    Category,
    ClaimDecision,
    ClaimType,
    FlashDealStatus,
    ForecastStatus,
    GroupOrderStatus,
    InvoiceCheckStatus,
    PaymentKind,
    PaymentStatus,
    PayPalModeEnum,
    QuoteStatus,
    ShopOrderStatus,
    ShopStatus,
    SwapKind,
    SwapStatus,
)

__all__ = ["Base"]


def enum_column(enum: type[StrEnum], **kwargs: Any) -> Any:
    return mapped_column(
        Enum(
            enum,
            native_enum=False,
            length=32,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        **kwargs,
    )


def money_check(*columns: str) -> list[CheckConstraint]:
    return [CheckConstraint(f"{column} >= 0", name=f"{column}_not_negative") for column in columns]


# ---------------------------------------------------------------------------------------
# The world
# ---------------------------------------------------------------------------------------


class Shop(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "shops"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    opening_hours: Mapped[dict[str, Any]] = mapped_column(default=dict)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    paypal_mode: Mapped[PayPalModeEnum] = enum_column(PayPalModeEnum)
    paypal_email: Mapped[str | None] = mapped_column(String(254))
    vault_id: Mapped[str | None] = mapped_column(String(255))
    weekly_spend_limit_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="SGD")
    preferences: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[ShopStatus] = enum_column(ShopStatus, default=ShopStatus.ACTIVE)

    __table_args__ = (CheckConstraint("weekly_spend_limit_cents >= 0", name="limit_not_negative"),)


class Supplier(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "suppliers"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    paypal_mode: Mapped[PayPalModeEnum] = enum_column(PayPalModeEnum)
    paypal_email: Mapped[str | None] = mapped_column(String(254))
    api_credentials_ref: Mapped[str] = mapped_column(String(80))
    delivery_days: Mapped[list[Any]] = mapped_column(default=list)
    delivery_fee_cents: Mapped[int] = mapped_column(Integer)
    platform_fee_bps: Mapped[int] = mapped_column(Integer, default=200)
    reliability_score: Mapped[int] = mapped_column(Integer, default=90)
    depot_latitude: Mapped[float] = mapped_column(Float)
    depot_longitude: Mapped[float] = mapped_column(Float)
    profile: Mapped[dict[str, Any]] = mapped_column(default=dict)

    items: Mapped[list[SupplierItem]] = relationship(back_populates="supplier")

    __table_args__ = (
        CheckConstraint("reliability_score BETWEEN 0 AND 100", name="reliability_range"),
        CheckConstraint("platform_fee_bps BETWEEN 0 AND 10000", name="fee_bps_range"),
        CheckConstraint("delivery_fee_cents >= 0", name="delivery_fee_not_negative"),
    )


class Item(UUIDPrimaryKey, Timestamps, Base):
    """A sellable SKU. Brand variants of the same product share `product_code`."""

    __tablename__ = "items"

    sku: Mapped[str] = mapped_column(String(60), unique=True)
    product_code: Mapped[str] = mapped_column(String(60), index=True)
    name: Mapped[str] = mapped_column(String(120))
    brand: Mapped[str] = mapped_column(String(80))
    category: Mapped[Category] = enum_column(Category)
    unit: Mapped[str] = mapped_column(String(40))
    unit_weight_grams: Mapped[int] = mapped_column(Integer)
    shelf_life_days: Mapped[int] = mapped_column(Integer)
    attributes: Mapped[dict[str, Any]] = mapped_column(default=dict)


class SupplierItem(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "supplier_items"

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    price_tiers: Mapped[list[Any]] = mapped_column()
    floor_price_cents: Mapped[int] = mapped_column(Integer)
    stock_limit: Mapped[int] = mapped_column(Integer)

    supplier: Mapped[Supplier] = relationship(back_populates="items")
    item: Mapped[Item] = relationship()

    __table_args__ = (
        UniqueConstraint("supplier_id", "item_id"),
        CheckConstraint("floor_price_cents > 0", name="floor_positive"),
        CheckConstraint("stock_limit >= 0", name="stock_not_negative"),
    )


class SalesHistory(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "sales_history"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    metrics: Mapped[dict[str, Any]] = mapped_column()

    __table_args__ = (UniqueConstraint("shop_id", "date"),)


class PurchaseHistory(UUIDPrimaryKey, Timestamps, Base):
    """What a shop bought on its own each week before Swarm (generated history)."""

    __tablename__ = "purchase_history"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    week_start: Mapped[date] = mapped_column(Date)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    delivery_fee_cents: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("shop_id", "week_start", "item_id"),)


class DemandForecast(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "demand_forecasts"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    week_start: Mapped[date] = mapped_column(Date)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    predicted_qty: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text)
    confirmed_qty: Mapped[int | None] = mapped_column(Integer)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ForecastStatus] = enum_column(ForecastStatus, default=ForecastStatus.PROPOSED)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (UniqueConstraint("shop_id", "week_start", "item_id"),)


# ---------------------------------------------------------------------------------------
# Group buying
# ---------------------------------------------------------------------------------------


class GroupOrder(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "group_orders"

    week_start: Mapped[date] = mapped_column(Date)
    category: Mapped[Category] = enum_column(Category)
    status: Mapped[GroupOrderStatus] = enum_column(GroupOrderStatus, default=GroupOrderStatus.DRAFT)
    awarded_supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    negotiation_rounds: Mapped[int] = mapped_column(Integer, default=0)
    delivery_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    platform_fee_bps: Mapped[int] = mapped_column(Integer, default=200)
    currency: Mapped[str] = mapped_column(String(3), default="SGD")
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)

    awarded_supplier: Mapped[Supplier | None] = relationship()
    shop_orders: Mapped[list[ShopOrder]] = relationship(
        back_populates="group_order",
        order_by="ShopOrder.created_at",
        cascade="all, delete-orphan",
    )

    __table_args__ = (UniqueConstraint("week_start", "category"),)


class ShopOrder(UUIDPrimaryKey, Timestamps, Base):
    """One shop's share of a group order. Carries the PayPal hold (authorization)."""

    __tablename__ = "shop_orders"

    group_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group_orders.id", ondelete="CASCADE")
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    status: Mapped[ShopOrderStatus] = enum_column(ShopOrderStatus, default=ShopOrderStatus.PENDING)
    delivery_share_cents: Mapped[int] = mapped_column(Integer, default=0)
    hold_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    captured_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    refunded_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    authorization_id: Mapped[str | None] = mapped_column(String(64))
    original_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capture_id: Mapped[str | None] = mapped_column(String(64))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paypal_mode: Mapped[PayPalModeEnum] = enum_column(PayPalModeEnum)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_note: Mapped[str | None] = mapped_column(Text)

    group_order: Mapped[GroupOrder] = relationship(back_populates="shop_orders")
    shop: Mapped[Shop] = relationship()
    lines: Mapped[list[GroupOrderLine]] = relationship(
        back_populates="shop_order",
        order_by="GroupOrderLine.created_at",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("group_order_id", "shop_id"),
        CheckConstraint("captured_amount_cents <= hold_amount_cents", name="capture_within_hold"),
        CheckConstraint(
            "refunded_amount_cents <= captured_amount_cents", name="refund_within_capture"
        ),
        *money_check(
            "delivery_share_cents",
            "hold_amount_cents",
            "captured_amount_cents",
            "refunded_amount_cents",
        ),
    )


class GroupOrderLine(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "group_order_lines"

    group_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group_orders.id", ondelete="CASCADE")
    )
    shop_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="CASCADE")
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"))
    qty_requested: Mapped[int] = mapped_column(Integer)
    qty_delivered: Mapped[int | None] = mapped_column(Integer)
    agreed_unit_price_cents: Mapped[int | None] = mapped_column(Integer)
    alone_unit_price_cents: Mapped[int | None] = mapped_column(Integer)

    shop_order: Mapped[ShopOrder] = relationship(back_populates="lines")
    item: Mapped[Item] = relationship()

    __table_args__ = (
        UniqueConstraint("shop_order_id", "item_id"),
        CheckConstraint("qty_requested > 0", name="qty_requested_positive"),
        CheckConstraint(
            "qty_delivered IS NULL OR (qty_delivered >= 0 AND qty_delivered <= qty_requested)",
            name="qty_delivered_range",
        ),
    )


class Quote(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "quotes"

    group_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group_orders.id", ondelete="CASCADE")
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"))
    round: Mapped[int] = mapped_column(Integer)
    line_prices: Mapped[dict[str, Any]] = mapped_column()
    total_cents: Mapped[int] = mapped_column(Integer)
    delivery_fee_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[QuoteStatus] = enum_column(QuoteStatus)
    message: Mapped[str | None] = mapped_column(Text)

    supplier: Mapped[Supplier] = relationship()

    __table_args__ = (UniqueConstraint("group_order_id", "supplier_id", "round"),)


# ---------------------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------------------


class Payment(UUIDPrimaryKey, Timestamps, Base):
    """Every PayPal money call, written *before* the call (PENDING) and updated after."""

    __tablename__ = "payments"

    kind: Mapped[PaymentKind] = enum_column(PaymentKind)
    status: Mapped[PaymentStatus] = enum_column(PaymentStatus, default=PaymentStatus.PENDING)
    paypal_mode: Mapped[PayPalModeEnum] = enum_column(PayPalModeEnum)
    account: Mapped[str] = mapped_column(String(60))
    paypal_id: Mapped[str | None] = mapped_column(String(64), index=True)
    related_type: Mapped[str] = mapped_column(String(40))
    related_id: Mapped[uuid.UUID] = mapped_column(index=True)
    shop_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shops.id", ondelete="SET NULL"), index=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    idempotency_key: Mapped[str] = mapped_column(String(108), unique=True)
    error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (CheckConstraint("amount_cents >= 0", name="amount_not_negative"),)


class Invoice(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "invoices"

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"))
    group_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("group_orders.id"))
    paypal_invoice_id: Mapped[str | None] = mapped_column(String(64))
    invoice_number: Mapped[str] = mapped_column(String(25), unique=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    line_items: Mapped[list[Any]] = mapped_column()
    total_cents: Mapped[int] = mapped_column(Integer)
    check_status: Mapped[InvoiceCheckStatus] = enum_column(
        InvoiceCheckStatus, default=InvoiceCheckStatus.PENDING
    )
    check_report: Mapped[dict[str, Any]] = mapped_column(default=dict)
    paid_payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    paypal_mode: Mapped[PayPalModeEnum] = enum_column(
        PayPalModeEnum, default=PayPalModeEnum.SIMULATED
    )
    paypal_status: Mapped[str | None] = mapped_column(String(32))
    issued_via: Mapped[str | None] = mapped_column(String(32))

    supplier: Mapped[Supplier] = relationship()


class Claim(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "claims"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    shop_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_orders.id"))
    group_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("group_order_lines.id")
    )
    type: Mapped[ClaimType] = enum_column(ClaimType)
    qty_affected: Mapped[int] = mapped_column(Integer, default=0)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(500))
    ai_assessment: Mapped[dict[str, Any]] = mapped_column(default=dict)
    decision: Mapped[ClaimDecision] = enum_column(ClaimDecision, default=ClaimDecision.PENDING)
    refund_payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class SwapOffer(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "swap_offers"

    kind: Mapped[SwapKind] = enum_column(SwapKind)
    # SURPLUS offers start with a seller and no buyer; EMERGENCY requests the other way round.
    from_shop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shops.id"))
    to_shop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shops.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"))
    qty: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="SGD")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[SwapStatus] = enum_column(SwapStatus, default=SwapStatus.OPEN)
    authorization_id: Mapped[str | None] = mapped_column(String(64))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    payout_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    food_saved_grams: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("price_cents >= 0", name="price_not_negative"),
        CheckConstraint("from_shop_id IS NOT NULL OR to_shop_id IS NOT NULL", name="has_a_party"),
    )


class FlashDeal(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "flash_deals"

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"))
    qty_available: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[FlashDealStatus] = enum_column(FlashDealStatus, default=FlashDealStatus.OPEN)
    list_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    taken_qty: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="SGD")
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (CheckConstraint("taken_qty <= qty_available", name="not_oversold"),)


class LedgerEntry(UUIDPrimaryKey, Base):
    """One leg of a double-entry transaction. Every `txn_group_id` balances to zero."""

    __tablename__ = "ledger_entries"

    txn_group_id: Mapped[uuid.UUID] = mapped_column(index=True)
    account: Mapped[str] = mapped_column(String(120), index=True)
    debit_cents: Mapped[int] = mapped_column(Integer, default=0)
    credit_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3))
    memo: Mapped[str] = mapped_column(String(255))
    event: Mapped[str] = mapped_column(String(40))
    related_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)

    __table_args__ = (
        CheckConstraint("debit_cents >= 0 AND credit_cents >= 0", name="legs_not_negative"),
        CheckConstraint("(debit_cents = 0) <> (credit_cents = 0)", name="one_sided_leg"),
    )


# ---------------------------------------------------------------------------------------
# Agents, events, audit
# ---------------------------------------------------------------------------------------


class AgentMessage(UUIDPrimaryKey, Base):
    __tablename__ = "agent_messages"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    conversation_id: Mapped[str] = mapped_column(String(80), index=True)
    from_agent: Mapped[str] = mapped_column(String(80))
    to_agent: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRequest(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "approval_requests"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    kind: Mapped[ApprovalKind] = enum_column(ApprovalKind)
    status: Mapped[ApprovalStatus] = enum_column(ApprovalStatus, default=ApprovalStatus.PENDING)
    related_id: Mapped[uuid.UUID | None] = mapped_column()
    question: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(80))


class WebhookEvent(UUIDPrimaryKey, Base):
    __tablename__ = "webhook_events"

    paypal_event_id: Mapped[str] = mapped_column(String(80), unique=True)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column()
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(255))


class AuditLog(UUIDPrimaryKey, Base):
    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MediaBlob(UUIDPrimaryKey, Base):
    """Uploaded photos (claims, delivery checks). Stored in Postgres: hosting disks are
    ephemeral and the files are small."""

    __tablename__ = "media_blobs"

    content_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    shop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shops.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramChat(Base):
    """A Telegram chat linked to a shop (in demo mode one chat can act as any shop)."""

    __tablename__ = "telegram_chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    shop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shops.id", ondelete="SET NULL"))
    username: Mapped[str | None] = mapped_column(String(80))
    first_name: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppState(Base):
    """Small key/value store (Swarm Clock position, simulator snapshot)."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
