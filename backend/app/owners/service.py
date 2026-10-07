"""Owner conversations: one handler for Telegram and for the web phone in the demo panel.

Everything a shop owner sees is an agent message addressed to `owner:<shop code>`; everything
they do comes in here:
- `handle_action`: a button press (`<kind>:<verb>:<ref>`, see `features.actions`),
- `handle_text`: a typed message, either an answer the agent asked for (changed quantities,
  what arrived) or free text the shop agent interprets ("out of eggs, need 30 now"),
- `handle_photo`: a photo, usually evidence for a claim.
Owner input is recorded as a message from `owner:<code>`, so the conversation reads the
same in Telegram, in the web phone and on the live board.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.agents.shop_agent import KEYWORDS
from app.clock import local_time, week_start
from app.db.app_state import get_state, set_state
from app.db.enums import ClaimType, ForecastStatus, GroupOrderStatus
from app.db.models import (
    AgentMessage,
    DemandForecast,
    GroupOrder,
    GroupOrderLine,
    Item,
    Shop,
    ShopOrder,
)
from app.features import (
    actions as act,
)
from app.features import (
    approvals,
    claims,
    delivery,
    emergency_borrow,
    flash_deals,
    savings,
    surplus_swap,
)
from app.features.context import Ctx
from app.features.neighbours import uses
from app.features.products import describe, wording
from app.money import rules
from app.money.engine import NeedsOwnerApproval
from app.paypal.errors import PayPalError

logger = logging.getLogger(__name__)

VERB_TEXT = {
    ("wn", "ok"): "Approve",
    ("wn", "chg"): "Change",
    ("wn", "skip"): "Skip",
    ("ol", "ok"): "Approve once",
    ("ol", "no"): "No",
    ("dl", "all"): "All arrived ✓",
    ("dl", "short"): "Something's missing",
    ("dl", "problem"): "Damaged / wrong item",
    ("sw", "yes"): "Yes, I'll take it",
    ("sw", "no"): "No thanks",
    ("ho", "done"): "Handed over ✓",
    ("em", "help"): "I can help",
    ("em", "no"): "Not now",
    ("fd", "buy"): "Buy",
    ("fd", "no"): "Skip",
    ("cl", "start"): "Report a problem",
    ("rp", "now"): "Show my savings",
}

HELP = (
    "I'm your Swarm agent. I'll message you on Monday with next week's order and keep you "
    "posted. You can also tell me things like:\n"
    '• "need extra oil this week"\n• "8 L milk expiring Sunday"\n'
    '• "out of eggs, need 1 tray now"\n• "report" for your savings'
)
FRIENDLY_ERRORS = (rules.RuleViolation, NeedsOwnerApproval, LookupError, PayPalError, ValueError)


def parse_changes(text: str) -> dict[str, int]:
    """'milk 40, eggs 0' -> {product: qty}."""
    found: dict[str, int] = {}
    for part in re.split(r"[,;\n]|\band\b", text.lower()):
        numbers = re.findall(r"\d+", part)
        product = next((p for p, words in KEYWORDS.items() if any(w in part for w in words)), None)
        if numbers and product:
            found[product] = int(numbers[0])
    return found


class OwnerService:
    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx

    # -- state ----------------------------------------------------------------------------

    async def _state(self, shop: Shop) -> dict[str, Any]:
        return await get_state(self.ctx.session, f"owner:{shop.code}") or {}

    async def _set_state(self, shop: Shop, value: dict[str, Any]) -> None:
        await set_state(self.ctx.session, f"owner:{shop.code}", value)
        await self.ctx.session.commit()

    async def _record(self, shop: Shop, text: str, payload: dict[str, Any] | None = None) -> None:
        await self.ctx.bus.publish(
            self.ctx.session,
            conversation_id=f"owner:{shop.code}",
            from_agent=f"owner:{shop.code}",
            to_agent=f"shop:{shop.code}",
            type="OWNER_REPLY",
            text=text,
            payload=payload or {},
        )

    async def _mark_answered(self, shop: Shop, action_id: str) -> None:
        rows = await self.ctx.session.scalars(
            select(AgentMessage)
            .where(AgentMessage.to_agent == f"owner:{shop.code}")
            .order_by(AgentMessage.seq.desc())
            .limit(40)
        )
        for message in rows:
            ids = [a.get("id") for a in message.payload.get("actions", [])]
            if action_id in ids:
                await self.ctx.session.execute(
                    update(AgentMessage)
                    .where(AgentMessage.id == message.id)
                    .values(payload={**message.payload, "answered": action_id})
                )
                await self.ctx.session.commit()
                return

    async def _say(self, shop: Shop, text: str, **kwargs: Any) -> None:
        await self.ctx.say_to_owner(shop, text, **kwargs)

    # -- buttons --------------------------------------------------------------------------

    async def handle_action(self, shop_code: str, action_id: str) -> None:
        shop = await self.ctx.shop(shop_code)
        parsed = act.parse_action(action_id)
        await self._record(
            shop, VERB_TEXT.get((parsed.kind, parsed.verb), parsed.verb), {"action": action_id}
        )
        await self._mark_answered(shop, action_id)
        try:
            await self._route_action(shop, parsed)
        except FRIENDLY_ERRORS as exc:
            await self._say(shop, _friendly(exc), kind="ERROR")

    async def _route_action(self, shop: Shop, parsed: act.ParsedAction) -> None:
        ref, kind, verb = parsed.ref, parsed.kind, parsed.verb
        ctx = self.ctx
        if kind == act.WEEKLY_NEEDS:
            if verb == "chg":
                await self._set_state(shop, {"awaiting": "weekly_changes"})
                await self._say(
                    shop, 'Sure. Send me the changes, like "milk 40, eggs 0".', kind="ASK"
                )
            else:
                await approvals.respond_weekly(
                    ctx, shop.code, "skip" if verb == "skip" else "approve"
                )
        elif kind == act.OVER_LIMIT and ref:
            await approvals.decide_over_limit(ctx, ref, verb == "ok", f"owner:{shop.code}")
        elif kind == act.DELIVERY and ref:
            if verb == "all":
                await delivery.confirm(ctx, ref, None)
            elif verb == "short":
                await self._set_state(shop, {"awaiting": "delivery_short", "ref": ref.hex})
                await self._say(
                    shop, 'What arrived? For example "milk 30" or "eggs 3, milk 30".', kind="ASK"
                )
            else:
                await self._set_state(shop, {"awaiting": "claim_photo", "ref": ref.hex})
                await self._say(
                    shop,
                    "Sorry about that. Send a photo and a few words about "
                    "what's wrong, and I'll sort out a refund.",
                    kind="ASK",
                )
        elif kind == act.SWAP_OFFER and ref:
            if verb == "yes":
                await surplus_swap.accept(ctx, ref, shop.code)
            else:
                await surplus_swap.decline(ctx, ref, shop.code)
        elif kind == act.HANDOVER and ref:
            await surplus_swap.handover(ctx, ref)
        elif kind == act.EMERGENCY and ref:
            if verb == "help":
                await emergency_borrow.accept(ctx, ref, shop.code)
            else:
                await self._say(shop, "No worries, I'll let them know.", kind="INFO")
        elif kind == act.FLASH_DEAL and ref:
            if verb == "buy":
                await flash_deals.buy(ctx, ref, shop.code)
            else:
                await self._say(shop, "Skipped.", kind="INFO")
        elif kind == act.CLAIM and ref:
            await self._set_state(shop, {"awaiting": "claim_photo", "ref": ref.hex})
            await self._say(shop, "Send a photo of the problem and a few words.", kind="ASK")
        elif kind == act.REPORT:
            await self.send_report(shop)

    # -- text -----------------------------------------------------------------------------

    async def handle_text(self, shop_code: str, text: str) -> None:
        shop = await self.ctx.shop(shop_code)
        text = text.strip()[:1000]
        if not text:
            return
        await self._record(shop, text)
        try:
            await self._route_text(shop, text)
        except FRIENDLY_ERRORS as exc:
            await self._say(shop, _friendly(exc), kind="ERROR")

    async def _route_text(self, shop: Shop, text: str) -> None:
        ctx = self.ctx
        state = await self._state(shop)
        awaiting = state.get("awaiting")
        lowered = text.lower().strip()
        if lowered in ("/help", "help", "/start"):
            await self._say(
                shop,
                HELP,
                kind="HELP",
                actions=[act.action(act.REPORT, "now", uuid.UUID(int=0), "Show my savings")],
            )
            return
        if lowered in ("/report", "report", "savings", "/savings"):
            await self.send_report(shop)
            return
        if awaiting == "weekly_changes":
            changes = parse_changes(text)
            if not changes:
                await self._say(shop, 'I couldn\'t read that. Try "milk 40, eggs 0".', kind="ASK")
                return
            await self._set_state(shop, {})
            await approvals.respond_weekly(ctx, shop.code, "approve", changes)
            return
        if awaiting == "delivery_short":
            so = await self._shop_order(state["ref"])
            delivered = delivery.parse_delivered(text, so)
            await self._set_state(shop, {})
            await delivery.confirm(ctx, so.id, delivered, note=text)
            return
        if awaiting == "claim_photo":
            if lowered in ("no photo", "none"):
                await self._file_claim(
                    shop, state["ref"], state.get("description", text), None, None
                )
                return
            await self._set_state(shop, {**state, "description": text})
            await self._say(shop, 'Thanks. Now send the photo (or type "no photo").', kind="ASK")
            return

        intent = await ctx.shop_agent(shop).interpret(text)
        if intent.intent == "skip_week":
            await approvals.respond_weekly(ctx, shop.code, "skip")
        elif intent.intent == "adjust_needs" and intent.product_code:
            await self._adjust_needs(shop, intent.product_code, intent.qty)
        elif intent.intent == "report_surplus" and intent.product_code:
            qty = intent.qty or max(1, uses(shop, intent.product_code) // 4)
            expires = local_time(ctx.now()).date() + timedelta(days=2)
            await surplus_swap.offer(ctx, shop.code, intent.product_code, qty, expires)
        elif intent.intent == "emergency_request" and intent.product_code:
            qty = intent.qty or 1
            if intent.product_code == "eggs-tray-30" and qty >= 30:
                qty = max(1, qty // 30)  # "30 eggs" means one tray
            await emergency_borrow.request(ctx, shop.code, intent.product_code, qty)
        elif intent.intent == "question":
            await self.send_report(shop)
        else:
            await self._say(shop, intent.note or HELP, kind="HELP")

    async def _adjust_needs(self, shop: Shop, product: str, qty: int | None) -> None:
        ctx = self.ctx
        week = week_start(ctx.now())
        row = await ctx.session.scalar(
            select(DemandForecast)
            .join(Item, Item.id == DemandForecast.item_id)
            .where(
                DemandForecast.shop_id == shop.id,
                DemandForecast.week_start == week,
                Item.product_code == product,
            )
        )
        group = await ctx.session.scalar(
            select(GroupOrder)
            .join(Item, Item.category == GroupOrder.category)
            .where(GroupOrder.week_start == week, Item.product_code == product)
        )
        locked = group is not None and group.status != GroupOrderStatus.COLLECTING
        if row is None or locked:
            await self._say(
                shop,
                f"This week's {wording(product).name} is already ordered. "
                "I'll plan for more next week.",
                kind="INFO",
            )
            return
        current = row.confirmed_qty if row.confirmed_qty is not None else row.predicted_qty
        new_qty = qty if qty is not None else round(current * 1.25) + 1
        row.confirmed_qty = new_qty
        if row.status == ForecastStatus.PROPOSED:
            row.predicted_qty = new_qty
        await ctx.session.commit()
        await self._say(
            shop,
            f"Done: {describe(product, new_qty)} this week (was {current}).",
            kind="NEEDS_UPDATED",
        )

    # -- photos ---------------------------------------------------------------------------

    async def handle_photo(
        self, shop_code: str, data: bytes, media_type: str, caption: str = ""
    ) -> None:
        shop = await self.ctx.shop(shop_code)
        await self._record(
            shop,
            f"📷 Photo{': ' + caption if caption else ''}",
            {"photo": True, "media_type": media_type},
        )
        state = await self._state(shop)
        try:
            if state.get("awaiting") == "claim_photo":
                description = caption or state.get("description", "")
                await self._file_claim(shop, state["ref"], description, data, media_type)
                return
            latest = await self.ctx.session.scalar(
                select(ShopOrder)
                .where(ShopOrder.shop_id == shop.id, ShopOrder.captured_amount_cents > 0)
                .order_by(ShopOrder.captured_at.desc())
            )
            if latest is None:
                await self._say(shop, "Thanks for the photo! Nothing to claim yet.", kind="INFO")
                return
            await self._set_state(
                shop, {"awaiting": "claim_photo", "ref": latest.id.hex, "pending_photo": True}
            )
            await self._file_claim(shop, latest.id.hex, caption, data, media_type)
        except FRIENDLY_ERRORS as exc:
            await self._say(shop, _friendly(exc), kind="ERROR")

    async def _file_claim(
        self, shop: Shop, ref: str, description: str, data: bytes | None, media_type: str | None
    ) -> None:
        so = await self._shop_order(ref)
        line = _pick_line(so, description)
        claim_type = _claim_type(description)
        qty = _first_number(description) or 1
        qty = min(qty, line.qty_delivered or line.qty_requested)
        await self._set_state(shop, {})
        await claims.file_claim(
            self.ctx, shop.code, line.id, claim_type, qty, description, data, media_type
        )

    async def _shop_order(self, ref: str) -> ShopOrder:
        so = await self.ctx.session.scalar(
            select(ShopOrder)
            .where(ShopOrder.id == uuid.UUID(hex=ref))
            .options(
                selectinload(ShopOrder.lines).selectinload(GroupOrderLine.item),
                selectinload(ShopOrder.shop),
                selectinload(ShopOrder.group_order),
            )
        )
        if so is None:
            raise LookupError("I couldn't find that order")
        return so

    # -- reports --------------------------------------------------------------------------

    async def send_report(self, shop: Shop) -> None:
        week = week_start(self.ctx.now())
        report = await savings.shop_week(self.ctx, shop, week)
        to_date = await savings.shop_to_date(self.ctx, shop)
        await self._say(
            shop,
            savings.report_text(report, to_date),
            kind="WEEKLY_REPORT",
            extra={"report": report.to_dict()},
        )


def _first_number(text: str) -> int | None:
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def _claim_type(text: str) -> ClaimType:
    lowered = text.lower()
    if any(w in lowered for w in ("expir", "expired", "past date", "off", "sour")):
        return ClaimType.EXPIRED
    if any(w in lowered for w in ("wrong", "not what", "different brand")):
        return ClaimType.WRONG_ITEM
    if any(w in lowered for w in ("missing", "short", "only got")):
        return ClaimType.SHORT
    return ClaimType.DAMAGED


def _pick_line(so: ShopOrder, text: str) -> Any:
    lowered = text.lower()
    for line in so.lines:
        if any(w in lowered for w in KEYWORDS.get(line.item.product_code, ())):
            return line
    return next(line for line in so.lines if (line.qty_delivered or 0) > 0)


def _friendly(exc: Exception) -> str:
    if isinstance(exc, NeedsOwnerApproval):
        return exc.message
    if isinstance(exc, rules.RuleViolation):
        return exc.message
    if isinstance(exc, PayPalError):
        return "PayPal didn't accept that just now. I've logged it and will retry."
    return str(exc) or "Something went wrong; I've logged it."
