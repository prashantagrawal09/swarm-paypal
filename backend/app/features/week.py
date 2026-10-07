"""The Swarm week, step by step.

| Step        | When (Singapore)  | What happens |
|-------------|-------------------|--------------|
| forecasts   | Mon 09:00 | each shop agent proposes next week's order; owners approve |
| negotiation | Tue 10:00 | orders pooled; coordinator negotiates; owners get the award |
| holds       | Wed 09:00 | PayPal holds on every shop; a supplier flash deal goes out |
| delivery    | Thu 08:00 | trucks arrive; owners confirm what came |
| settlement  | Thu 14:00 | capture what arrived; invoices checked (and corrected); suppliers paid |
| surplus     | Fri 16:00 | expiring stock goes to a neighbour |
| emergency   | Sat 11:00 | someone runs out; a neighbour helps within minutes |
| report      | Sun 18:00 | weekly savings report for every owner |

Steps are idempotent and remember they ran (`app_state["week:<monday>"]`). In demo mode the
Swarm Clock jumps to each step's time, and simulated owners answer straight away using
their preferences; real owners answer on Telegram (a real shop that has not replied by
Tuesday gets its usual order, if its preferences allow).

The demo scenario (`app_state["demo:scenario"]`) supplies the week's surprises: a short
delivery, a wrong-price invoice, a flash deal, a surplus offer and an emergency.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.clock import SwarmClock, at_local
from app.db.app_state import get_state, set_state
from app.db.enums import (
    ApprovalKind,
    ApprovalStatus,
    GroupOrderStatus,
    PayPalModeEnum,
    ShopOrderStatus,
    ShopStatus,
)
from app.db.models import ApprovalRequest, AuditLog, GroupOrder, Shop
from app.features import (
    approvals,
    delivery,
    emergency_borrow,
    flash_deals,
    group_buy,
    invoice_checker,
    savings,
    surplus_swap,
)
from app.features.context import Ctx
from app.features.products import describe_all
from app.money import rules
from app.money.amount import Money
from app.money.engine import NeedsOwnerApproval
from app.paypal.errors import PayPalError

logger = logging.getLogger(__name__)

SCENARIO_KEY = "demo:scenario"
AUTO_APPROVE_OVER_LIMIT_SHARE = 0.25

DEFAULT_SCENARIO: dict[str, Any] = {
    "short_delivery": {
        "shop": "cafe-mei",
        "category": "DAIRY",
        "product": "milk-full-cream-1l",
        "fraction": 0.9,
    },
    "wrong_price_invoice": {
        "category": "DAIRY",
        "product": "milk-full-cream-1l",
        "markup_cents": 25,
    },
    "flash_deal": {
        "supplier": "johorfarm",
        "sku": "LETTUCE-1KG-CAMERON",
        "qty": 30,
        "discount_pct": 35,
    },
    "surplus": {"shop": "cafe-mei", "product": "milk-full-cream-1l", "qty": 8, "days_left": 2},
    "emergency": {"shop": "kopi-corner", "product": "eggs-tray-30", "qty": 1},
}


@dataclass(frozen=True)
class Step:
    key: str
    day: int
    hour: int
    minute: int
    title: str
    description: str


STEPS: tuple[Step, ...] = (
    Step(
        "forecasts",
        0,
        9,
        0,
        "Monday: forecasts",
        "Each shop agent proposes next week's order; owners approve",
    ),
    Step(
        "negotiation",
        1,
        10,
        0,
        "Tuesday: negotiation",
        "Twelve orders become one; three supplier agents compete",
    ),
    Step(
        "holds",
        2,
        9,
        0,
        "Wednesday: PayPal holds",
        "Money is reserved on every shop's PayPal, not taken",
    ),
    Step("delivery", 3, 8, 0, "Thursday: delivery", "Trucks arrive; owners confirm what came"),
    Step(
        "settlement",
        3,
        14,
        0,
        "Thursday: settlement",
        "Pay only for what arrived; invoices checked; suppliers paid",
    ),
    Step("surplus", 4, 16, 0, "Friday: surplus swap", "Expiring stock goes to a neighbour"),
    Step("emergency", 5, 11, 0, "Saturday: emergency", "Out of eggs? A neighbour helps"),
    Step("report", 6, 18, 0, "Sunday: savings report", "What Swarm saved every shop"),
)
STEP_KEYS = tuple(step.key for step in STEPS)


async def scenario(ctx: Ctx) -> dict[str, Any]:
    stored = await get_state(ctx.session, SCENARIO_KEY)
    return stored if stored is not None else dict(DEFAULT_SCENARIO)


async def save_scenario(ctx: Ctx, value: dict[str, Any]) -> None:
    await set_state(ctx.session, SCENARIO_KEY, value)
    await ctx.session.commit()


class WeekRunner:
    def __init__(self, ctx: Ctx, week: date) -> None:
        if week.weekday() != 0:
            raise ValueError("A Swarm week starts on a Monday")
        self.ctx = ctx
        self.week = week
        self._key = f"week:{week}"

    # -- state ----------------------------------------------------------------------------

    async def state(self) -> dict[str, Any]:
        return await get_state(self.ctx.session, self._key) or {"done": {}, "results": {}}

    async def _mark(self, key: str, result: dict[str, Any]) -> None:
        state = await self.state()
        state["done"][key] = self.ctx.now().isoformat()
        state["results"][key] = result
        await set_state(self.ctx.session, self._key, state)
        self.ctx.session.add(
            AuditLog(
                actor="swarm:week",
                action=key,
                details={"week": str(self.week), **result},
                created_at=self.ctx.now(),
            )
        )
        await self.ctx.session.commit()

    def time_of(self, step: Step) -> datetime:
        return at_local(self.week + timedelta(days=step.day), step.hour, step.minute)

    async def next_step(self) -> Step | None:
        done = (await self.state())["done"]
        return next((step for step in STEPS if step.key not in done), None)

    # -- running --------------------------------------------------------------------------

    async def run(self, key: str) -> dict[str, Any]:
        step = next(s for s in STEPS if s.key == key)
        state = await self.state()
        if key in state["done"]:
            return {"skipped": True, **state["results"].get(key, {})}
        clock = self.ctx.clock
        if isinstance(clock, SwarmClock) and clock.now() < self.time_of(step):
            clock.set(self.time_of(step))
            await set_state(self.ctx.session, "swarm_clock", clock.to_dict())
            await self.ctx.session.commit()
        await self.ctx.bus.emit(
            "step_started", {"step": key, "title": step.title, "week": str(self.week)}
        )
        handlers: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
            "forecasts": self._forecasts,
            "negotiation": self._negotiation,
            "holds": self._holds,
            "delivery": self._delivery,
            "settlement": self._settlement,
            "surplus": self._surplus,
            "emergency": self._emergency,
            "report": self._report,
        }
        result = await handlers[key]()
        await self._mark(key, result)
        await self.ctx.bus.emit(
            "step_finished",
            {"step": key, "title": step.title, "week": str(self.week), "result": result},
        )
        return result

    async def run_next(self) -> tuple[Step | None, dict[str, Any]]:
        step = await self.next_step()
        if step is None:
            return None, {}
        return step, await self.run(step.key)

    # -- helpers ----------------------------------------------------------------------------

    async def _shops(self) -> list[Shop]:
        return list(
            await self.ctx.session.scalars(
                select(Shop).where(Shop.status == ShopStatus.ACTIVE).order_by(Shop.code)
            )
        )

    async def _groups(self, *statuses: GroupOrderStatus) -> list[GroupOrder]:
        query = select(GroupOrder).where(GroupOrder.week_start == self.week)
        if statuses:
            query = query.where(GroupOrder.status.in_(statuses))
        return list(await self.ctx.session.scalars(query.order_by(GroupOrder.category)))

    # -- steps ------------------------------------------------------------------------------

    async def _forecasts(self) -> dict[str, Any]:
        proposed = confirmed = 0
        for shop in await self._shops():
            agent = self.ctx.shop_agent(shop)
            await agent.weekly_proposal(self.ctx.session, self.week)
            proposed += 1
            if shop.paypal_mode == PayPalModeEnum.SIMULATED:
                await agent.confirm_needs(self.ctx.session, self.week)
                confirmed += 1
        return {
            "proposed": proposed,
            "auto_confirmed": confirmed,
            "waiting_for_owners": proposed - confirmed,
        }

    async def _negotiation(self) -> dict[str, Any]:
        for shop in await self._shops():
            waiting = await approvals.pending(self.ctx, shop, ApprovalKind.WEEKLY_NEEDS)
            if not waiting:
                continue
            agent = self.ctx.shop_agent(shop)
            if shop.preferences.get("auto_confirm_usual", True):
                await agent.confirm_needs(self.ctx.session, self.week)
                await self.ctx.say_to_owner(
                    shop,
                    "No reply yesterday, so I've put in your usual order. "
                    "Tell me if anything should change.",
                    kind="AUTO_CONFIRMED",
                )
            else:
                await agent.skip_week(self.ctx.session, self.week)
        groups = await group_buy.pool_week(
            self.ctx.session, self.week, self.ctx.now(), self.ctx.runtime.settings.platform_fee_bps
        )
        coordinator = self.ctx.coordinator()
        outcomes = {}
        for group in groups:
            if group.status in (GroupOrderStatus.COLLECTING, GroupOrderStatus.NEGOTIATING):
                result = await coordinator.negotiate(self.ctx.session, group.id)
                outcomes[group.category.value] = {
                    "supplier": result.winner.supplier_code if result.winner else None,
                    "rounds": result.rounds,
                    "opening_cents": result.opening_best_landed_cents,
                    "final_cents": result.final_landed_cents,
                }
        await self._award_digests()
        return {"groups": outcomes}

    async def _award_digests(self) -> None:
        """One message per shop with every order it's in this week."""
        lines: dict[str, list[str]] = {}
        totals: dict[str, int] = {}
        shops: dict[str, Shop] = {}
        for group in await self._groups(GroupOrderStatus.AWARDED):
            group = await group_buy.load_group(self.ctx.session, group.id)
            supplier = group.awarded_supplier.name if group.awarded_supplier else ""
            for saving in group_buy.savings_for_group(group):
                so = next(s for s in group.shop_orders if s.shop.code == saving.shop_code)
                shops[saving.shop_code] = so.shop
                qty = {line.item.product_code: line.qty_requested for line in so.lines}
                lines.setdefault(saving.shop_code, []).append(
                    f"• {group.category.title()} from {supplier}: {describe_all(qty)}, "
                    f"{Money(saving.paid_cents)} incl. delivery "
                    f"(alone: {Money(saving.alone_cents)})"
                )
                totals[saving.shop_code] = totals.get(saving.shop_code, 0) + saving.saved_cents
        for code, entries in lines.items():
            await self.ctx.say_to_owner(
                shops[code],
                "🤝 This week's group deals:\n"
                + "\n".join(entries)
                + f"\nThat's {Money(totals[code])} less than buying alone. "
                "I'll hold the money on your PayPal tomorrow.",
                kind="AWARD_DIGEST",
                extra={"saved_cents": totals[code]},
            )

    async def _holds(self) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for group in await self._groups(GroupOrderStatus.AWARDED):
            result = await self.ctx.engine.place_holds(group.id)
            summary[group.category.value] = {
                "held": result.count(ShopOrderStatus.AUTHORIZED),
                "failed": result.count(ShopOrderStatus.FAILED),
                "needs_approval": result.count("NEEDS_APPROVAL"),
            }
        decided = await self._simulated_over_limit_answers()
        for group in await self._groups(GroupOrderStatus.AWARDED):
            group = await group_buy.load_group(self.ctx.session, group.id)
            if not any(so.status == ShopOrderStatus.AUTHORIZED for so in group.shop_orders):
                await self.ctx.engine.cancel_group_order(group.id, reason="Nobody could be held")
        deal = (await scenario(self.ctx)).get("flash_deal")
        posted = None
        if deal:
            if isinstance(self.ctx.clock, SwarmClock):
                self.ctx.clock.advance(hours=5)  # the deal goes out early afternoon
            try:
                posted = await flash_deals.post(
                    self.ctx, deal["supplier"], deal["sku"], deal["qty"], deal["discount_pct"]
                )
            except (rules.RuleViolation, PayPalError) as exc:
                logger.warning("Flash deal not posted: %s", exc)
        return {
            "groups": summary,
            "over_limit_decisions": decided,
            "flash_deal": str(posted.id) if posted else None,
        }

    async def _simulated_over_limit_answers(self) -> dict[str, str]:
        """Simulated owners answer over-limit questions from their limit: a modest excess is
        approved, a big one is refused."""
        decided = {}
        rows = await self.ctx.session.scalars(
            select(ApprovalRequest)
            .join(Shop, Shop.id == ApprovalRequest.shop_id)
            .where(
                ApprovalRequest.kind == ApprovalKind.OVER_LIMIT,
                ApprovalRequest.status == ApprovalStatus.PENDING,
                Shop.paypal_mode == PayPalModeEnum.SIMULATED,
            )
        )
        for approval in list(rows):
            shop = await self.ctx.session.get(Shop, approval.shop_id)
            assert shop is not None
            over = int(approval.payload.get("over_by_cents", 0))
            approve = over <= shop.weekly_spend_limit_cents * AUTO_APPROVE_OVER_LIMIT_SHARE
            await self.ctx.bus.publish(
                self.ctx.session,
                conversation_id=f"owner:{shop.code}",
                from_agent=f"owner:{shop.code}",
                to_agent=f"shop:{shop.code}",
                type="OWNER_REPLY",
                text="Approve once 👍" if approve else "No, skip it this week",
                payload={"approval_id": str(approval.id), "simulated_owner": True},
            )
            try:
                await approvals.decide_over_limit(
                    self.ctx, approval.id, approve, f"owner:{shop.code}"
                )
                decided[shop.code] = "approved" if approve else "declined"
            except (rules.RuleViolation, NeedsOwnerApproval, PayPalError) as exc:
                decided[shop.code] = f"error: {exc}"
        return decided

    async def _delivery(self) -> dict[str, Any]:
        injected = (await scenario(self.ctx)).get("short_delivery")
        summary: dict[str, Any] = {}
        for group in await self._groups(GroupOrderStatus.HELD):
            notified = await delivery.dispatch(self.ctx, group.id)
            group = await group_buy.load_group(self.ctx.session, group.id)
            shorts = []
            for so in group.shop_orders:
                if (
                    so.status != ShopOrderStatus.AUTHORIZED
                    or so.shop.paypal_mode != PayPalModeEnum.SIMULATED
                ):
                    continue
                delivered = None
                if (
                    injected
                    and injected.get("shop") == so.shop.code
                    and injected.get("category") == group.category.value
                ):
                    product = injected["product"]
                    line = next((ln for ln in so.lines if ln.item.product_code == product), None)
                    if line is not None:
                        qty = int(line.qty_requested * float(injected.get("fraction", 0.9)))
                        delivered = {product: qty}
                        shorts.append(
                            {
                                "shop": so.shop.code,
                                "product": product,
                                "delivered": qty,
                                "ordered": line.qty_requested,
                            }
                        )
                await self.ctx.bus.publish(
                    self.ctx.session,
                    conversation_id=f"owner:{so.shop.code}",
                    from_agent=f"owner:{so.shop.code}",
                    to_agent=f"shop:{so.shop.code}",
                    type="OWNER_REPLY",
                    text="All arrived ✓"
                    if delivered is None
                    else f"Only {describe_all(delivered)} arrived",
                    payload={"shop_order_id": str(so.id), "simulated_owner": True},
                )
                await delivery.confirm(self.ctx, so.id, delivered)
            summary[group.category.value] = {"notified": notified, "short": shorts}
        return summary

    async def _settlement(self) -> dict[str, Any]:
        wrong = (await scenario(self.ctx)).get("wrong_price_invoice")
        summary: dict[str, Any] = {}
        for group in await self._groups(GroupOrderStatus.HELD, GroupOrderStatus.OUT_FOR_DELIVERY):
            captured = await delivery.finalize(self.ctx, group.id)
            markup = None
            if wrong and wrong.get("category") == group.category.value:
                markup = {wrong["product"]: int(wrong.get("markup_cents", 25))}
            invoices = await invoice_checker.run_cycle(self.ctx, group.id, markup=markup)
            summary[group.category.value] = {
                "captured": captured.count(ShopOrderStatus.CAPTURED),
                "invoices": [
                    {
                        "number": inv.invoice_number,
                        "status": inv.check_status.value,
                        "overcharge_cents": inv.check_report.get("overcharge_cents", 0),
                    }
                    for inv in invoices
                ],
            }
        return summary

    async def _surplus(self) -> dict[str, Any]:
        config = (await scenario(self.ctx)).get("surplus")
        if not config:
            return {"skipped": "no surplus in the scenario"}
        expires = self.ctx.now().date() + timedelta(days=int(config.get("days_left", 2)))
        swap = await surplus_swap.offer(
            self.ctx, config["shop"], config["product"], int(config["qty"]), expires
        )
        return {"swap_id": str(swap.id), "status": swap.status.value}

    async def _emergency(self) -> dict[str, Any]:
        config = (await scenario(self.ctx)).get("emergency")
        if not config:
            return {"skipped": "no emergency in the scenario"}
        swap = await emergency_borrow.request(
            self.ctx, config["shop"], config["product"], int(config["qty"])
        )
        return {
            "swap_id": str(swap.id),
            "status": swap.status.value,
            "seconds_to_sorted": swap.details.get("seconds_to_sorted"),
        }

    async def _report(self) -> dict[str, Any]:
        sent = await savings.send_reports(self.ctx, self.week)
        summary = await savings.platform_summary(self.ctx)
        await self.ctx.bus.emit("week_summary", {"week": str(self.week), **summary})
        return {"reports_sent": sent, "saved_cents": summary["saved_cents"]}
