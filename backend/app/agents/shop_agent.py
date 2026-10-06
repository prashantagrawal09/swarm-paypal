"""Shop agent: one per shop. Talks to the owner and speaks for the shop in the swarm.

Phase 3 capabilities (Telegram wiring arrives in phase 4):
- `weekly_proposal`: Monday's "next week you need about ..." message plus an approval
  request the owner answers with Approve / Change / Skip.
- `confirm_needs` / `skip_week`: record the owner's answer (quantities validated in code).
- `interpret`: turn a free-text owner message into one allowed intent; the product and
  quantity are checked against the catalog before anything uses them.
- `explain_award`: tell the owner what was agreed, any brand substitution, and the saving.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Action, Agent, Verdict
from app.agents.bus import MessageBus
from app.agents.prompting import wrap_untrusted
from app.clock import Clock
from app.db.enums import ApprovalKind, ApprovalStatus
from app.db.models import ApprovalRequest, DemandForecast, GroupOrder, Item, Shop
from app.features import demand, group_buy
from app.features.demand import ProductForecast
from app.features.products import describe_all, wording
from app.llm.client import LLM
from app.money.amount import Money

MAX_FACTOR_WITHOUT_ASKING = 3  # more than 3x the usual quantity needs an explicit owner change

Intent = Literal[
    "adjust_needs", "skip_week", "report_surplus", "emergency_request", "question", "other"
]


class OwnerNote(BaseModel):
    message: str


class OwnerIntent(BaseModel):
    intent: Intent
    product_code: str | None = None
    qty: int | None = None
    note: str = ""


KEYWORDS = {
    "milk-full-cream-1l": ("milk",),
    "eggs-tray-30": ("egg",),
    "butter-250g": ("butter",),
    "coffee-beans-1kg": ("bean", "coffee"),
    "cooking-oil-2l": ("oil",),
    "paper-cups-12oz-50": ("cup",),
    "lids-50": ("lid",),
    "takeaway-box-50": ("box", "takeaway"),
    "napkins-100": ("napkin", "tissue"),
    "tomatoes-1kg": ("tomato",),
    "lettuce-1kg": ("lettuce", "salad"),
}


class ShopAgent(Agent):
    kind = "shop"
    prompt_name = "shop_agent"
    tools = frozenset(
        {
            "get_forecast",
            "confirm_weekly_needs",
            "join_group_order",
            "request_owner_approval",
            "check_invoice_lines",
            "get_savings_report",
        }
    )

    def __init__(self, shop: Shop, *, llm: LLM, bus: MessageBus, clock: Clock) -> None:
        super().__init__(
            code=shop.code,
            display_name=shop.name,
            owner=shop.owner_name,
            mandate={
                "weekly_spend_limit_cents": shop.weekly_spend_limit_cents,
                "usual_weekly": shop.preferences.get("usual_weekly", {}),
                "accepted_brands": shop.preferences.get("accepted_brands", {}),
                "allow_substitutes": shop.preferences.get("allow_substitutes", True),
            },
            llm=llm,
            bus=bus,
            clock=clock,
        )
        self.shop = shop

    @property
    def owner_channel(self) -> str:
        return f"owner:{self.shop.code}"

    def prompt_values(self) -> dict[str, object]:
        prefs = []
        for product, brands in self.mandate["accepted_brands"].items():
            prefs.append(f"{wording(product).name}: only {', '.join(brands)}")
        if not prefs:
            prefs.append("any brand with the same specification")
        return {
            "shop_name": self.shop.name,
            "shop_kind": self.shop.opening_hours.get("kind", "food business"),
            "owner_name": self.shop.owner_name,
            "preferences": "; ".join(prefs),
            "spend_limit": Money(self.shop.weekly_spend_limit_cents).format(),
        }

    # -- gate ---------------------------------------------------------------------------

    def check(self, action: Action) -> Verdict:
        if action.tool == "confirm_weekly_needs":
            usual: dict[str, int] = self.mandate["usual_weekly"]
            for product, qty in action.args.get("quantities", {}).items():
                if qty < 0:
                    return Verdict.deny("NEGATIVE_QTY", "Quantities cannot be negative")
                limit = max(usual.get(product, 0) * MAX_FACTOR_WITHOUT_ASKING, 10)
                if qty > limit and not action.args.get("owner_changed"):
                    return Verdict.deny(
                        "UNUSUAL_QTY", f"{qty} of {product} is far above usual; ask the owner"
                    )
        return Verdict.allow()

    # -- Monday -------------------------------------------------------------------------

    async def weekly_proposal(
        self, session: AsyncSession, week: date
    ) -> tuple[ApprovalRequest, list[ProductForecast]]:
        await self.require(session, Action("get_forecast", {"week": str(week)}))
        forecasts = await demand.forecast_shop(session, self.shop, week)
        await demand.propose_week(session, week)
        listing = describe_all({f.product_code: f.predicted_qty for f in forecasts})
        fallback = f"Next week you'll need about {listing}. Same as usual?"
        facts = (
            "Write the Monday message asking the owner to confirm next week's order.\n"
            + "\n".join(
                f"- {f.item_name}: {f.predicted_qty} x {f.unit} ({f.explanation})"
                for f in forecasts
            )
        )
        note, source = await self.ask(
            task="weekly_needs",
            content=facts,
            schema=OwnerNote,
            fallback=lambda: OwnerNote(message=fallback),
        )
        text = note.message.strip()[:600] if source == "llm" and note.message.strip() else fallback
        await self.require(session, Action("request_owner_approval", {"kind": "WEEKLY_NEEDS"}))
        approval = await session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.shop_id == self.shop.id,
                ApprovalRequest.kind == ApprovalKind.WEEKLY_NEEDS,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        )
        if approval is None:
            approval = ApprovalRequest(
                shop_id=self.shop.id,
                kind=ApprovalKind.WEEKLY_NEEDS,
                question=text,
                payload={
                    "week": str(week),
                    "items": [
                        {
                            "item_id": str(f.item_id),
                            "product": f.product_code,
                            "qty": f.predicted_qty,
                            "unit": f.unit,
                            "name": f.item_name,
                        }
                        for f in forecasts
                    ],
                },
            )
            session.add(approval)
            await session.commit()
        await self.say(
            session,
            conversation_id=f"owner:{self.shop.code}:{week}",
            to=self.owner_channel,
            type="WEEKLY_NEEDS",
            text=text,
            payload={"approval_id": str(approval.id), "buttons": ["Approve", "Change", "Skip"]},
        )
        return approval, forecasts

    async def confirm_needs(
        self,
        session: AsyncSession,
        week: date,
        changes: dict[str, int] | None = None,
        *,
        owner_changed: bool = False,
    ) -> list[DemandForecast]:
        """Owner approved (optionally with changed quantities per product code)."""
        rows = list(
            await session.scalars(
                select(DemandForecast).where(
                    DemandForecast.shop_id == self.shop.id, DemandForecast.week_start == week
                )
            )
        )
        items = {i.id: i for i in await session.scalars(select(Item))}
        quantities = {items[row.item_id].product_code: row.predicted_qty for row in rows} | (
            changes or {}
        )
        await self.require(
            session,
            Action(
                "confirm_weekly_needs", {"quantities": quantities, "owner_changed": owner_changed}
            ),
        )
        overrides = {row.item_id: quantities[items[row.item_id].product_code] for row in rows}
        confirmed = await demand.confirm_week(
            session, self.shop.id, week, self.clock.now(), overrides
        )
        await self._close_weekly_approval(session, ApprovalStatus.APPROVED)
        await self.require(session, Action("join_group_order", {"week": str(week)}))
        joined = describe_all(quantities)
        await self.say(
            session,
            conversation_id=f"pool:{week}",
            to="coordinator:swarm",
            type="JOIN",
            text=f"{self.shop.name} is in this week: {joined}.",
            payload={"quantities": quantities},
        )
        return confirmed

    async def skip_week(self, session: AsyncSession, week: date) -> None:
        await demand.skip_week(session, self.shop.id, week, self.clock.now())
        await self._close_weekly_approval(session, ApprovalStatus.REJECTED)
        await self.say(
            session,
            conversation_id=f"pool:{week}",
            to="coordinator:swarm",
            type="SKIP",
            text=f"{self.shop.name} is sitting this week out.",
        )

    async def _close_weekly_approval(self, session: AsyncSession, status: ApprovalStatus) -> None:
        approval = await session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.shop_id == self.shop.id,
                ApprovalRequest.kind == ApprovalKind.WEEKLY_NEEDS,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        )
        if approval is not None:
            approval.status = status
            approval.decided_at = self.clock.now()
            approval.decided_by = f"owner:{self.shop.code}"
            await session.commit()

    # -- free text from the owner -------------------------------------------------------

    async def interpret(self, text: str) -> OwnerIntent:
        content = (
            "Classify the owner's message into one intent. Products: "
            + ", ".join(KEYWORDS)
            + ".\n"
            + wrap_untrusted([(self.owner_channel, "TEXT", text)], tag="owner_message")
        )
        intent, _ = await self.ask(
            task="interpret",
            content=content,
            schema=OwnerIntent,
            fallback=lambda: keyword_intent(text),
        )
        return self._validated(intent)

    def _validated(self, intent: OwnerIntent) -> OwnerIntent:
        product = intent.product_code if intent.product_code in KEYWORDS else None
        qty = intent.qty if intent.qty is not None and 0 < intent.qty <= 500 else None
        if intent.intent in ("adjust_needs", "report_surplus", "emergency_request") and not product:
            return OwnerIntent(intent="other", note="I couldn't tell which product you meant.")
        return OwnerIntent(
            intent=intent.intent, product_code=product, qty=qty, note=intent.note[:200]
        )

    # -- after the award ----------------------------------------------------------------

    async def explain_award(self, session: AsyncSession, group: GroupOrder) -> str:
        savings = {s.shop_code: s for s in group_buy.savings_for_group(group)}
        mine = savings.get(self.shop.code)
        excluded = [e for e in group.summary.get("excluded", []) if e["shop"] == self.shop.code]
        supplier = group.awarded_supplier.name if group.awarded_supplier else "the supplier"
        parts = []
        if mine:
            parts.append(
                f"Your {group.category.lower()} order is with {supplier}: {Money(mine.paid_cents)} "
                f"including delivery, {Money(mine.saved_cents)} less than buying alone."
            )
        for entry in excluded:
            parts.append(
                f"I left out {wording(entry['product']).name}: the winning brand is "
                f"{entry['brand']} and you only take your usual brand."
            )
        fallback = " ".join(parts) or f"You're not in this week's {group.category.lower()} order."
        note, source = await self.ask(
            task="explain_award",
            content="Rewrite for the owner, keep every number:\n" + fallback,
            schema=OwnerNote,
            fallback=lambda: OwnerNote(message=fallback),
        )
        text = note.message.strip()[:600] if source == "llm" and note.message.strip() else fallback
        await self.say(
            session,
            conversation_id=f"owner:{self.shop.code}:{group.week_start}",
            to=self.owner_channel,
            type="AWARD_NEWS",
            text=text,
            payload={
                "group_order_id": str(group.id),
                "saved_cents": mine.saved_cents if mine else 0,
            },
        )
        return text


def keyword_intent(text: str) -> OwnerIntent:
    """Deterministic fallback parser for owner messages."""
    lowered = text.lower()
    product = next(
        (code for code, words in KEYWORDS.items() if any(word in lowered for word in words)), None
    )
    match = re.search(r"\b(\d{1,3})\b", lowered)
    qty = int(match.group(1)) if match else None
    if any(word in lowered for word in ("skip", "closed", "no order", "holiday this week")):
        return OwnerIntent(intent="skip_week")
    if any(word in lowered for word in ("out of", "ran out", "urgent", "need now", "emergency")):
        return OwnerIntent(intent="emergency_request", product_code=product, qty=qty)
    if any(
        word in lowered for word in ("expiring", "expire", "surplus", "too much", "extra stock")
    ):
        return OwnerIntent(intent="report_surplus", product_code=product, qty=qty)
    if product and any(
        word in lowered for word in ("need", "more", "extra", "add", "less", "fewer")
    ):
        return OwnerIntent(intent="adjust_needs", product_code=product, qty=qty)
    if lowered.strip().endswith("?"):
        return OwnerIntent(intent="question")
    return OwnerIntent(intent="other")


__all__ = ["OwnerIntent", "ShopAgent", "keyword_intent"]
