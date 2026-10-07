"""Everything a feature needs for one unit of work: a database session plus the runtime
(Swarm Clock, PayPal gateways, message bus, language model) and agents built on them."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bus import MessageBus
from app.agents.claims_agent import ClaimsAgent
from app.agents.coordinator import Coordinator
from app.agents.shop_agent import ShopAgent
from app.agents.supplier_agent import SupplierAgent
from app.clock import Clock
from app.db.models import ApprovalRequest, Shop, Supplier
from app.features.actions import OVER_LIMIT, action
from app.llm.client import LLM
from app.money.engine import MoneyEngine
from app.runtime import Runtime


class _EngineEvents:
    """The engine's event sink: everything goes on the live stream, and questions for owners
    become owner messages with buttons."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx

    async def emit(self, kind: str, payload: dict[str, Any]) -> None:
        await self.ctx.bus.emit(kind, payload)
        if kind == "approval_needed" and payload.get("approval_id"):
            await self.ctx.ask_owner_to_approve(str(payload["approval_id"]))


@dataclass
class Ctx:
    session: AsyncSession
    runtime: Runtime
    _engine: MoneyEngine | None = field(default=None, init=False, repr=False)

    @property
    def clock(self) -> Clock:
        return self.runtime.clock

    @property
    def bus(self) -> MessageBus:
        return self.runtime.bus

    @property
    def llm(self) -> LLM:
        return self.runtime.llm

    def now(self) -> datetime:
        return self.runtime.clock.now()

    @property
    def engine(self) -> MoneyEngine:
        if self._engine is None:
            self._engine = MoneyEngine(
                self.session, self.runtime.registry, self.runtime.clock, _EngineEvents(self)
            )
        return self._engine

    async def ask_owner_to_approve(self, approval_id: str) -> None:
        """Send an over-limit question to the owner once, with Approve / No buttons."""
        approval = await self.session.get(ApprovalRequest, uuid.UUID(approval_id))
        if approval is None or approval.payload.get("notified"):
            return
        approval.payload = {**approval.payload, "notified": True}
        await self.session.commit()
        shop = await self.session.get(Shop, approval.shop_id)
        if shop is None:
            return
        await self.say_to_owner(
            shop,
            f"💰 {approval.question}",
            kind="APPROVAL",
            ref=approval.id.hex,
            actions=[
                action(OVER_LIMIT, "ok", approval.id, "Approve once", "primary"),
                action(OVER_LIMIT, "no", approval.id, "No, skip it"),
            ],
        )

    # -- agents -------------------------------------------------------------------------

    def shop_agent(self, shop: Shop) -> ShopAgent:
        return ShopAgent(shop, llm=self.llm, bus=self.bus, clock=self.clock)

    def supplier_agent(self, supplier: Supplier) -> SupplierAgent:
        return SupplierAgent(supplier, None, llm=self.llm, bus=self.bus, clock=self.clock)

    def coordinator(self) -> Coordinator:
        return Coordinator(llm=self.llm, bus=self.bus, clock=self.clock)

    def claims_agent(self) -> ClaimsAgent:
        return ClaimsAgent(llm=self.llm, bus=self.bus, clock=self.clock)

    # -- lookups ------------------------------------------------------------------------

    async def shop(self, code: str) -> Shop:
        shop = await self.session.scalar(select(Shop).where(Shop.code == code))
        if shop is None:
            raise LookupError(f"No shop called {code!r}")
        return shop

    async def supplier(self, code: str) -> Supplier:
        supplier = await self.session.scalar(select(Supplier).where(Supplier.code == code))
        if supplier is None:
            raise LookupError(f"No supplier called {code!r}")
        return supplier

    async def say_to_owner(
        self,
        shop: Shop,
        text: str,
        *,
        kind: str = "INFO",
        actions: list[dict[str, str]] | None = None,
        ref: str | None = None,
        conversation: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """A message from the shop's agent to its owner (Telegram and the web phone)."""
        payload: dict[str, object] = {"kind": kind, **(extra or {})}
        if actions:
            payload["actions"] = actions
        if ref:
            payload["ref"] = ref
        await self.bus.publish(
            self.session,
            conversation_id=conversation or f"owner:{shop.code}",
            from_agent=f"shop:{shop.code}",
            to_agent=f"owner:{shop.code}",
            type=kind,
            text=text,
            payload=payload,
        )
