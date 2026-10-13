"""Supplier agent: quotes and counter-offers for one supplier.

How a price is chosen (AI suggests, code decides):
1. Code builds a short menu of legal pricing options for this round: hold, a small
   concession, the minimum needed to beat the best competing price, a deep concession,
   and (in the final round only) the floor. Every option is at or above the supplier's
   secret floor, never above its previous quote, and within stock.
2. The model picks one label and writes the message, in the supplier's own style.
   Without a model (or if it answers with anything off the menu) a deterministic policy
   picks instead, using the same style.
3. `validate()` checks the chosen prices again before the quote is stored and sent.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Action, Agent, Verdict
from app.agents.bus import MessageBus
from app.agents.prompting import wrap_untrusted
from app.clock import Clock
from app.db.enums import QuoteStatus
from app.db.models import Quote, Supplier
from app.features.group_buy import SupplierOffer
from app.features.products import describe_all, per_unit
from app.llm.client import LLM
from app.money.amount import Money

logger = logging.getLogger(__name__)

Strategy = Literal["hold", "small", "beat", "deep", "floor"]
CONCESSION = {"hold": 0.0, "small": 0.25, "deep": 0.6, "floor": 1.0}
BEAT_MARGIN_BPS = 50  # undercut the best rival by 0.5%, not by a cent


@dataclass(frozen=True)
class RFQ:
    group_order_id: uuid.UUID
    category: str
    round: int
    final: bool
    quantities: dict[str, int]
    shops: int
    delivery_window: str
    best_competing_landed_cents: int | None = None
    target_landed_cents: int | None = None
    coordinator_message: str = ""


@dataclass(frozen=True)
class PricedOption:
    label: str
    unit_prices: dict[str, int]
    items_total_cents: int
    landed_total_cents: int


@dataclass
class SupplierQuote:
    supplier_id: uuid.UUID
    supplier_code: str
    supplier_name: str
    reliability: int
    round: int
    declined: bool = False
    decline_reason: str = ""
    strategy: str = ""
    unit_prices: dict[str, int] = field(default_factory=dict)
    quantities: dict[str, int] = field(default_factory=dict)
    delivery_fee_cents: int = 0
    items_total_cents: int = 0
    message: str = ""
    source: str = ""
    quote_id: uuid.UUID | None = None

    @property
    def landed_total_cents(self) -> int:
        return self.items_total_cents + self.delivery_fee_cents


class SupplierMove(BaseModel):
    strategy: Strategy
    message: str


class SupplierAgent(Agent):
    kind = "supplier"
    prompt_name = "supplier_agent"
    tools = frozenset({"submit_quote", "counter_offer", "decline_rfq"})

    def __init__(
        self,
        supplier: Supplier,
        offer: SupplierOffer | None,
        *,
        llm: LLM,
        bus: MessageBus,
        clock: Clock,
        decline_reason: str = "",
    ) -> None:
        mandate = {
            "floors": {p: si.floor_price_cents for p, si in (offer.items.items() if offer else [])},
            "stock": {p: si.stock_limit for p, si in (offer.items.items() if offer else [])},
            "delivery_fee_cents": supplier.delivery_fee_cents,
        }
        super().__init__(
            code=supplier.code,
            display_name=supplier.name,
            owner=supplier.name,
            mandate=mandate,
            llm=llm,
            bus=bus,
            clock=clock,
        )
        self.supplier = supplier
        self.offer = offer
        self.decline_reason = decline_reason
        self.previous: dict[str, int] | None = None

    # -- prompt ---------------------------------------------------------------------------

    def prompt_values(self) -> dict[str, object]:
        return {
            "supplier_name": self.supplier.name,
            "supplier_tagline": self.supplier.profile.get("tagline", ""),
            "style": self.supplier.profile.get("style", "professional"),
            "reliability": self.supplier.reliability_score,
            "delivery_fee": Money(self.supplier.delivery_fee_cents).format(),
        }

    @property
    def style(self) -> str:
        text = str(self.supplier.profile.get("style", "")).lower()
        if "hungry" in text or "hard" in text:
            return "hungry"
        if "volume" in text:
            return "volume"
        return "steady"

    # -- options --------------------------------------------------------------------------

    def _priced(
        self, label: str, prices: dict[str, int], quantities: dict[str, int]
    ) -> PricedOption:
        items = sum(prices[p] * qty for p, qty in quantities.items())
        return PricedOption(label, prices, items, items + self.supplier.delivery_fee_cents)

    def list_prices(self, quantities: dict[str, int]) -> dict[str, int]:
        assert self.offer is not None
        return {p: self.offer.list_price(p, qty) for p, qty in quantities.items()}

    def options(self, rfq: RFQ) -> list[PricedOption]:
        floors: dict[str, int] = self.mandate["floors"]
        current = self.previous or self.list_prices(rfq.quantities)
        options: list[PricedOption] = []
        for label in ("hold", "small", "deep", "floor"):
            if label == "floor" and not rfq.final:
                continue
            share = CONCESSION[label]
            prices = {
                p: max(floors[p], current[p] - math.floor((current[p] - floors[p]) * share))
                for p in rfq.quantities
            }
            options.append(self._priced(label, prices, rfq.quantities))
        beat = self._beat_option(rfq, current)
        if beat is not None:
            options.insert(2, beat)
        unique: dict[tuple[tuple[str, int], ...], PricedOption] = {}
        for option in options:
            unique.setdefault(tuple(sorted(option.unit_prices.items())), option)
        return list(unique.values())

    def _beat_option(self, rfq: RFQ, current: dict[str, int]) -> PricedOption | None:
        """The smallest concession that makes this supplier's landed total the cheapest."""
        best = rfq.best_competing_landed_cents
        if best is None:
            return None
        floors: dict[str, int] = self.mandate["floors"]
        mine = self._priced("beat", current, rfq.quantities)
        goal = best * (10_000 - BEAT_MARGIN_BPS) // 10_000
        needed = mine.landed_total_cents - goal
        if needed <= 0:
            return None
        room = {p: (current[p] - floors[p]) * qty for p, qty in rfq.quantities.items()}
        total_room = sum(room.values())
        if total_room < needed:
            return None
        prices = {}
        for p, qty in rfq.quantities.items():
            cut = math.ceil(needed * room[p] / total_room / qty) if total_room else 0
            prices[p] = max(floors[p], current[p] - cut)
        option = self._priced("beat", prices, rfq.quantities)
        return option if option.landed_total_cents < best else None

    def policy(self, rfq: RFQ, options: list[PricedOption]) -> str:
        """Deterministic choice, in the supplier's style, when no model is available."""
        labels = {option.label for option in options}
        current_landed = next(o.landed_total_cents for o in options if o.label == "hold")
        behind = (
            rfq.best_competing_landed_cents is not None
            and current_landed > rfq.best_competing_landed_cents
        )

        def pick(*preferences: str) -> str:
            return next((label for label in preferences if label in labels), "hold")

        if rfq.round == 1:
            return "hold" if self.style == "steady" else pick("small")
        if behind:
            if rfq.final:
                return pick("beat", "floor" if self.style == "hungry" else "deep", "deep")
            return pick("beat", "deep" if self.style == "hungry" else "small")
        if rfq.final:
            return pick("small")
        return "hold" if self.style == "steady" else pick("small")

    # -- the gate -------------------------------------------------------------------------

    def check(self, action: Action) -> Verdict:
        if action.tool == "decline_rfq":
            return Verdict.allow()
        prices: dict[str, int] = action.args.get("unit_prices", {})
        quantities: dict[str, int] = action.args.get("quantities", {})
        floors: dict[str, int] = self.mandate["floors"]
        stock: dict[str, int] = self.mandate["stock"]
        if set(prices) != set(quantities):
            return Verdict.deny("INCOMPLETE_QUOTE", "A quote must price every pooled product")
        for product, price in prices.items():
            if product not in floors:
                return Verdict.deny("NOT_STOCKED", f"We do not sell {product}")
            if price < floors[product]:
                return Verdict.deny("BELOW_FLOOR", f"{product} below the owner's floor")
            if quantities[product] > stock[product]:
                return Verdict.deny("OUT_OF_STOCK", f"Not enough {product} in stock")
            if self.previous and price > self.previous[product]:
                return Verdict.deny("PRICE_RAISED", f"{product} higher than our last quote")
        passed = [
            "Every product asked for is priced",
            "Everything quoted is something we sell",
            "No price is below the owner's floor",
            "There is enough stock for the whole order",
        ]
        if self.previous:
            passed.append("No price is higher than in our last quote")
        return Verdict.allow(tuple(passed))

    # -- responding -------------------------------------------------------------------------

    async def respond(self, session: AsyncSession, rfq: RFQ, conversation_id: str) -> SupplierQuote:
        quote = SupplierQuote(
            supplier_id=self.supplier.id,
            supplier_code=self.supplier.code,
            supplier_name=self.supplier.name,
            reliability=self.supplier.reliability_score,
            round=rfq.round,
            quantities=dict(rfq.quantities),
            delivery_fee_cents=self.supplier.delivery_fee_cents,
        )
        reason = self.decline_reason or self._stock_problem(rfq)
        if reason:
            await self.require(session, Action("decline_rfq", {"reason": reason}))
            quote.declined, quote.decline_reason = True, reason
            quote.message = f"Thanks for thinking of us, but we'll pass on this one: {reason}."
            await self.say(
                session,
                conversation_id=conversation_id,
                to="coordinator:swarm",
                type="DECLINE",
                text=quote.message,
                payload={"round": rfq.round, "reason": reason},
            )
            return quote

        options = self.options(rfq)
        by_label = {option.label: option for option in options}
        move, source = await self.ask(
            task="final" if rfq.final else ("quote" if rfq.round == 1 else "counter"),
            content=self._task(rfq, options),
            schema=SupplierMove,
            fallback=lambda: SupplierMove(strategy=self.policy(rfq, options), message=""),
        )
        label = move.strategy if move.strategy in by_label else self.policy(rfq, options)
        if label != move.strategy:
            logger.warning("%s chose an option not on the menu (%s)", self.agent_id, move.strategy)
            source = "fallback"
        chosen = by_label[label]
        tool = "submit_quote" if rfq.round == 1 else "counter_offer"
        verdict = await self.require(
            session, Action(tool, {"unit_prices": chosen.unit_prices, "quantities": rfq.quantities})
        )

        quote.strategy = label
        quote.unit_prices = dict(chosen.unit_prices)
        quote.items_total_cents = chosen.items_total_cents
        quote.source = source
        quote.message = (
            move.message.strip()[:400]
            if source == "llm" and move.message.strip()
            else self._template(rfq, chosen)
        )
        row = Quote(
            group_order_id=rfq.group_order_id,
            supplier_id=self.supplier.id,
            round=rfq.round,
            line_prices=chosen.unit_prices,
            total_cents=chosen.items_total_cents,
            delivery_fee_cents=self.supplier.delivery_fee_cents,
            status=QuoteStatus.FINAL if rfq.final else QuoteStatus.SUBMITTED,
            message=quote.message,
        )
        session.add(row)
        await session.flush()
        quote.quote_id = row.id
        self.previous = dict(chosen.unit_prices)
        said = await self.say(
            session,
            conversation_id=conversation_id,
            to="coordinator:swarm",
            type="FINAL_QUOTE" if rfq.final else "QUOTE",
            text=quote.message,
            payload={
                "round": rfq.round,
                "unit_prices": chosen.unit_prices,
                "items_total_cents": chosen.items_total_cents,
                "delivery_fee_cents": self.supplier.delivery_fee_cents,
                "landed_total_cents": chosen.landed_total_cents,
                "strategy": label,
                "decided_by": source,
            },
        )
        await self.decided(
            session,
            said,
            "quote",
            {
                "round": rfq.round,
                # Code priced every option from the owner's floors; the choice was only
                # ever between these.
                "options": [
                    {"label": option.label, "landed_total_cents": option.landed_total_cents}
                    for option in options
                ],
                "chosen": label,
                "chosen_by": source,
                "checked": list(verdict.checked),
            },
        )
        return quote

    def _stock_problem(self, rfq: RFQ) -> str:
        stock: dict[str, int] = self.mandate["stock"]
        for product, qty in rfq.quantities.items():
            if qty > stock.get(product, 0):
                return f"we only have {describe_all({product: stock.get(product, 0)})} this week"
        return ""

    def _task(self, rfq: RFQ, options: list[PricedOption]) -> str:
        lines = [
            f"Round {rfq.round}{' (best and final)' if rfq.final else ''} for a "
            f"{rfq.category.lower()} group order from {rfq.shops} shops, "
            f"delivery {rfq.delivery_window}.",
            "Quantities: " + describe_all(rfq.quantities) + ".",
        ]
        if rfq.best_competing_landed_cents is not None:
            lines.append(f"Best competing landed price: {Money(rfq.best_competing_landed_cents)}.")
        if rfq.target_landed_cents is not None:
            lines.append(
                f"The coordinator's target landed price: {Money(rfq.target_landed_cents)}."
            )
        lines.append("Your options (choose one label):")
        for option in options:
            prices = ", ".join(
                f"{Money(price)}{per_unit(p)}" for p, price in option.unit_prices.items()
            )
            lines.append(f"- {option.label}: {prices}; landed {Money(option.landed_total_cents)}")
        if rfq.coordinator_message:
            lines.append("Coordinator's message:")
            lines.append(wrap_untrusted([("coordinator:swarm", "RFQ", rfq.coordinator_message)]))
        return "\n".join(lines)

    def _template(self, rfq: RFQ, option: PricedOption) -> str:
        prices = ", ".join(
            f"{Money(price)}{per_unit(p)}" for p, price in option.unit_prices.items()
        )
        landed = Money(option.landed_total_cents)
        if rfq.round == 1:
            fee = Money(self.supplier.delivery_fee_cents)
            return f"{self.supplier.name}: {prices}, delivered for {fee}. Landed {landed}."
        if option.label == "hold":
            return (
                f"{self.supplier.name}: we're holding at {landed} landed. "
                "That's already a sharp price for this volume."
            )
        if rfq.final:
            return f"{self.supplier.name}, best and final: {prices}. Landed {landed}."
        return f"{self.supplier.name}: we can sharpen to {prices}. Landed {landed}."


async def latest_quotes(session: AsyncSession, group_order_id: uuid.UUID) -> list[Quote]:
    rows = await session.scalars(
        select(Quote).where(Quote.group_order_id == group_order_id).order_by(Quote.round)
    )
    latest: dict[uuid.UUID, Quote] = {}
    for row in rows:
        latest[row.supplier_id] = row
    return list(latest.values())
