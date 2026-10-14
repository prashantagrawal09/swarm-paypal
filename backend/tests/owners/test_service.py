"""Owner conversations: buttons, typed answers, free text and photos."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.agents.claims_agent import ClaimAssessment
from app.db.enums import ApprovalKind, ClaimDecision, ForecastStatus, ShopOrderStatus, SwapStatus
from app.db.models import (
    AgentMessage,
    ApprovalRequest,
    Claim,
    DemandForecast,
    Item,
    ShopOrder,
    SwapOffer,
)
from app.features.week import WeekRunner
from app.llm.client import ScriptedLLM
from app.owners.service import OwnerService, parse_changes
from tests.conftest import DEMO_WEEK
from tests.helpers import shops_by_code

pytestmark = pytest.mark.db


async def owner_messages(db, code):
    rows = await db.scalars(
        select(AgentMessage)
        .where(AgentMessage.to_agent == f"owner:{code}")
        .order_by(AgentMessage.seq)
    )
    return list(rows)


def test_parse_changes():
    assert parse_changes("milk 40, eggs 0 and 3 butter") == {
        "milk-full-cream-1l": 40,
        "eggs-tray-30": 0,
        "butter-250g": 3,
    }


async def test_weekly_change_flow(db, world, ctx):
    shop = (await shops_by_code(db))["cafe-mei"]
    await ctx.shop_agent(shop).weekly_proposal(db, DEMO_WEEK)
    message = (await owner_messages(db, "cafe-mei"))[-1]
    change = next(a["id"] for a in message.payload["actions"] if a["label"] == "Change")
    service = OwnerService(ctx)
    await service.handle_action("cafe-mei", change)
    await service.handle_text("cafe-mei", "milk 40, oil 0")
    rows = list(await db.scalars(select(DemandForecast).where(DemandForecast.shop_id == shop.id)))
    assert {r.status for r in rows} == {ForecastStatus.CONFIRMED}
    replies = [m.text for m in await owner_messages(db, "cafe-mei")]
    assert any("Send me the changes" in t for t in replies) and any(
        "Confirmed" in t for t in replies
    )
    answered = await db.get(AgentMessage, message.id, populate_existing=True)
    assert answered.payload["answered"] == change


async def test_skip_and_free_text_intents(db, world, ctx):
    shop = (await shops_by_code(db))["teh-time"]
    await ctx.shop_agent(shop).weekly_proposal(db, DEMO_WEEK)
    service = OwnerService(ctx)
    await service.handle_text("teh-time", "need extra milk this week")
    milk = await db.scalar(
        select(DemandForecast)
        .where(DemandForecast.shop_id == shop.id)
        .order_by(DemandForecast.predicted_qty.desc())
    )
    assert "Done:" in (await owner_messages(db, "teh-time"))[-1].text
    await service.handle_text("teh-time", "we're closed, skip this week")
    statuses = set(
        await db.scalars(select(DemandForecast.status).where(DemandForecast.shop_id == shop.id))
    )
    assert statuses == {ForecastStatus.SKIPPED}
    approval = await db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.kind == ApprovalKind.WEEKLY_NEEDS)
    )
    assert approval.status.value == "REJECTED"
    assert milk is not None


def test_expiry_follows_the_owners_words():
    from datetime import date

    from app.owners.service import expiry_from

    sunday = date(2026, 10, 18)
    assert expiry_from("10 L milk expiring tomorrow", sunday) == date(2026, 10, 19)
    assert expiry_from("lettuce going bad today", sunday) == sunday
    assert expiry_from("8 L milk expiring Sunday", sunday) == sunday
    assert expiry_from("eggs expire wed", sunday) == date(2026, 10, 21)
    assert expiry_from("butter expires thurs", sunday) == date(2026, 10, 22)
    assert expiry_from("butter expires in 3 days", sunday) == date(2026, 10, 21)
    assert expiry_from("too much lettuce", sunday) == date(2026, 10, 20)


def test_quantity_arithmetic():
    from app.owners.service import adjusted

    assert adjusted(38, 4, "less") == 34
    assert adjusted(38, None, "less") == 28  # a quarter less when no number is given
    assert adjusted(3, 9, "less") == 0  # never below nothing
    assert adjusted(38, 4, "more") == 42
    assert adjusted(38, None, "more") == 48
    assert adjusted(38, 30, "set") == 30
    assert adjusted(38, None, None) == 48
    assert adjusted(38, None, "half") == 19
    assert adjusted(38, None, "double") == 76
    assert adjusted(38, 0, "set") == 0
    assert adjusted(38, None, "set") == 38  # a total without a number changes nothing


async def test_less_means_less_and_units_are_never_guessed(db, world, ctx):
    shop = (await shops_by_code(db))["cafe-mei"]
    await ctx.shop_agent(shop).weekly_proposal(db, DEMO_WEEK)
    service = OwnerService(ctx)

    async def milk() -> int:
        row = await db.scalar(
            select(DemandForecast)
            .join(Item, Item.id == DemandForecast.item_id)
            .where(DemandForecast.shop_id == shop.id, Item.product_code == "milk-full-cream-1l")
            .execution_options(populate_existing=True)
        )
        return row.confirmed_qty if row.confirmed_qty is not None else row.predicted_qty

    before = await milk()
    await service.handle_text("cafe-mei", "4 L less milk")
    assert await milk() == before - 4
    assert (await owner_messages(db, "cafe-mei"))[-1].text == (
        f"Done: {before - 4} L milk this week (was {before} L)."
    )

    # "No X" is a total of nothing, not "a bit more".
    await service.handle_text("cafe-mei", "no milk this week")
    assert await milk() == 0
    assert (await owner_messages(db, "cafe-mei"))[-1].text == (
        f"Done: no milk this week (was {before - 4} L)."
    )
    await service.handle_text("cafe-mei", "milk 30")
    assert await milk() == 30

    # A crate isn't a unit milk is ordered in: ask, change nothing.
    await service.handle_text("cafe-mei", "2 crates of milk less")
    assert await milk() == 30
    reply = (await owner_messages(db, "cafe-mei"))[-1].text
    assert "can't tell how much 2 crates is" in reply and "Tell me in L" in reply


async def test_what_is_in_my_order_and_products_the_shop_never_buys(db, world, ctx):
    shop = (await shops_by_code(db))["teh-time"]
    service = OwnerService(ctx)
    await service.handle_text("teh-time", "what is in my order")
    assert "Nothing is planned yet" in (await owner_messages(db, "teh-time"))[-1].text

    await ctx.shop_agent(shop).weekly_proposal(db, DEMO_WEEK)
    await service.handle_text("teh-time", "what is in my order")
    reply = (await owner_messages(db, "teh-time"))[-1].text
    assert reply.startswith("This week's order: ") and "L milk" in reply
    assert reply.endswith("Waiting for your OK.")

    # A tea house that never orders butter has no butter to cut.
    await service.handle_text("teh-time", "cut the butter")
    reply = (await owner_messages(db, "teh-time"))[-1].text
    assert reply == (
        "Butter isn't part of your usual weekly order, so there's nothing to change from here."
    )


async def test_after_delivery_the_order_summary_says_what_arrived(db, world, ctx):
    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds"):
        await runner.run(key)
    service = OwnerService(ctx)
    await service.handle_text("cafe-mei", "what's in my order?")
    held = (await owner_messages(db, "cafe-mei"))[-1].text
    assert held.startswith("This week's order: ") and "38 L milk" in held
    assert held.endswith("Held on your PayPal until it's delivered.")

    for key in ("delivery", "settlement"):
        await runner.run(key)
    await service.handle_text("cafe-mei", "what's in my order?")
    got = (await owner_messages(db, "cafe-mei"))[-1].text
    # Café Mei's milk came short: the summary is what arrived, not what was planned.
    assert got.startswith("This week you received: ") and "34 L milk" in got
    assert got.endswith("Delivered, and you paid for what arrived.")


async def test_a_change_after_the_order_is_placed_promises_nothing(db, world, ctx):
    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation"):
        await runner.run(key)
    await OwnerService(ctx).handle_text("cafe-mei", "4 L less milk")
    reply = (await owner_messages(db, "cafe-mei"))[-1].text
    assert "already ordered" in reply and "next week" in reply
    assert "plan for more" not in reply


async def test_delivery_short_by_text_then_emergency_then_photo_claim(db, world, ctx, runtime):
    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds"):
        await runner.run(key)
    from app.db.models import GroupOrder
    from app.features import delivery
    from app.features.group_buy import load_group

    dairy = await db.scalar(select(GroupOrder).where(GroupOrder.category == "DAIRY"))
    await delivery.dispatch(ctx, dairy.id)
    message = next(
        m for m in reversed(await owner_messages(db, "toast-and-co")) if m.type == "DELIVERY"
    )
    short = next(a["id"] for a in message.payload["actions"] if "missing" in a["label"])
    service = OwnerService(ctx)
    await service.handle_action("toast-and-co", short)
    await service.handle_text("toast-and-co", "milk 20")
    await delivery.finalize(ctx, dairy.id)
    group = await load_group(db, dairy.id)
    toast = next(so for so in group.shop_orders if so.shop.code == "toast-and-co")
    milk = next(line for line in toast.lines if line.item.product_code == "milk-full-cream-1l")
    assert milk.qty_delivered == 20 and toast.status == ShopOrderStatus.CAPTURED

    await service.handle_text("kopi-corner", "Out of eggs, need 30 now")
    emergency = await db.scalar(select(SwapOffer))
    assert emergency.status == SwapStatus.COMPLETED and emergency.qty == 1

    runtime.llm = ScriptedLLM(
        {
            "claims_agent.assess": ClaimAssessment(
                issue_type="DAMAGED",
                claim_supported=True,
                confidence=0.9,
                qty_affected=1,
                evidence="Leaking carton",
            )
        }
    )
    await service.handle_photo(
        "toast-and-co", b"jpeg", "image/jpeg", "milk carton leaking, 1 damaged"
    )
    claim = await db.scalar(select(Claim))
    assert claim.decision == ClaimDecision.AUTO_REFUNDED


async def test_help_and_report(db, world, ctx):
    service = OwnerService(ctx)
    await service.handle_text("cafe-mei", "help")
    await service.handle_text("cafe-mei", "report")
    texts = [m.text for m in await owner_messages(db, "cafe-mei")]
    assert any("I'm your Swarm agent" in t for t in texts)
    assert any("Your Swarm week" in t for t in texts)
    assert not await db.scalar(select(ShopOrder))


async def test_a_photo_claim_is_about_the_product_named_not_the_latest_charge(
    db, world, ctx, runtime
):
    """A bare photo used to be filed against whichever order was charged last, so "2 trays
    of eggs cracked" refunded a line of the packaging order."""
    from app.db.models import GroupOrderLine, Item

    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds", "delivery", "settlement"):
        await runner.run(key)
    charged = list(
        await db.scalars(
            select(ShopOrder)
            .join(ShopOrder.shop)
            .where(ShopOrder.captured_amount_cents > 0)
            .order_by(ShopOrder.captured_at.desc())
        )
    )
    shops = await shops_by_code(db)
    mine = [so for so in charged if so.shop_id == shops["bakery-lim"].id]
    assert len(mine) > 1  # several deliveries were charged, dairy not the last of them

    await OwnerService(ctx).handle_photo(
        "bakery-lim", b"jpeg", "image/jpeg", "2 trays of eggs arrived cracked"
    )
    claim = await db.scalar(select(Claim))
    line = await db.get(GroupOrderLine, claim.group_order_line_id)
    item = await db.get(Item, line.item_id)
    assert item.product_code == "eggs-tray-30" and claim.qty_affected == 2
    # No model looked at the photo, so a person decides; nothing is refunded yet.
    assert claim.decision == ClaimDecision.ESCALATED_OPERATOR and claim.refund_payment_id is None

    from app.features import claims

    refunded = await claims.operator_decision(ctx, claim.id, approve=True)
    assert refunded.decision == ClaimDecision.REFUNDED
    assert refunded.amount_cents == 2 * line.agreed_unit_price_cents


async def test_a_photo_on_its_own_is_kept_and_the_owner_is_asked_what_is_wrong(db, world, ctx):
    from sqlalchemy import func

    from app.db.models import GroupOrderLine, Item, MediaBlob

    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds", "delivery", "settlement"):
        await runner.run(key)
    service = OwnerService(ctx)

    await service.handle_photo("bakery-lim", b"jpeg", "image/jpeg")
    sent = [m for m in await db.scalars(select(AgentMessage)) if m.from_agent == "owner:bakery-lim"]
    assert sent[-1].payload["photo_url"].startswith("/api/media/")
    assert "What's wrong, and with what?" in (await owner_messages(db, "bakery-lim"))[-1].text
    assert await db.scalar(select(func.count()).select_from(Claim)) == 0

    await service.handle_text("bakery-lim", "2 trays of eggs arrived cracked")
    claim = await db.scalar(select(Claim))
    line = await db.get(GroupOrderLine, claim.group_order_line_id)
    item = await db.get(Item, line.item_id)
    assert item.product_code == "eggs-tray-30" and claim.qty_affected == 2
    # The photo sent first is the claim's photo, stored once.
    assert claim.photo_url == sent[-1].payload["photo_url"]
    assert await db.scalar(select(func.count()).select_from(MediaBlob)) == 1
    reply = (await owner_messages(db, "bakery-lim"))[-1].text
    assert "Your claim: 2 trays of eggs, S$15.50. Nothing is refunded until it's decided." in reply


async def test_a_lone_photo_can_be_called_off(db, world, ctx):
    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds", "delivery", "settlement"):
        await runner.run(key)
    service = OwnerService(ctx)
    await service.handle_photo("bakery-lim", b"jpeg", "image/jpeg")
    await service.handle_text("bakery-lim", "never mind")
    assert (await db.scalar(select(Claim))) is None
    assert (await owner_messages(db, "bakery-lim"))[-1].text.startswith("OK, no claim.")


async def open_buttons(db, code):
    return [
        m
        for m in await owner_messages(db, code)
        if m.payload.get("actions") and not m.payload.get("answered")
    ]


async def test_after_the_scripted_week_no_question_is_left_open(db, world, ctx):
    """The demo's simulated owners answer for themselves; their buttons must close too."""
    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds", "delivery", "settlement", "surplus"):
        await runner.run(key)
    for code in ("cafe-mei", "brew-lab", "bakery-lim"):
        assert [m.type for m in await open_buttons(db, code)] == [], code
    weekly = next(m for m in await owner_messages(db, "cafe-mei") if m.type == "WEEKLY_NEEDS")
    assert weekly.payload["answered"].startswith("wn:ok:")
    # Café Mei's milk was short: its dairy delivery is answered with that button.
    answers = [
        m.payload["answered"].split(":")[1]
        for m in await owner_messages(db, "cafe-mei")
        if m.type == "DELIVERY"
    ]
    assert sorted(answers) == ["all", "all", "short"]


async def test_a_late_tap_gets_a_clear_answer_and_changes_nothing(db, world, ctx):
    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds", "delivery", "settlement"):
        await runner.run(key)
    delivery = next(m for m in await owner_messages(db, "cafe-mei") if m.type == "DELIVERY")
    short = next(a["id"] for a in delivery.payload["actions"] if a["id"].startswith("dl:short"))
    taps_before = await db.scalar(
        select(func.count())
        .select_from(AgentMessage)
        .where(AgentMessage.from_agent == "owner:cafe-mei")
    )
    await OwnerService(ctx).handle_action("cafe-mei", short)
    assert (await owner_messages(db, "cafe-mei"))[-1].text == (
        "That delivery is already settled: you paid for what arrived."
    )
    taps_after = await db.scalar(
        select(func.count())
        .select_from(AgentMessage)
        .where(AgentMessage.from_agent == "owner:cafe-mei")
    )
    assert taps_after == taps_before  # not recorded as an answer


async def test_closing_buttons_answers_the_chooser_and_closes_the_rest(db, world, ctx):
    import uuid

    from app.features import actions as act
    from app.features.buttons import close_buttons

    offer, other = uuid.uuid4(), uuid.uuid4()
    for code, ref in (("cafe-mei", offer), ("brew-lab", offer), ("teh-time", other)):
        await ctx.bus.publish(
            db,
            conversation_id=f"swap:{ref}",
            from_agent=f"shop:{code}",
            to_agent=f"owner:{code}",
            type="SURPLUS_OFFER",
            text="Want it?",
            payload={
                "actions": [
                    act.action(act.SWAP_OFFER, "yes", ref, "Yes"),
                    act.action(act.SWAP_OFFER, "no", ref, "No"),
                ]
            },
        )
    # Café Mei takes it; the offer is then closed for everyone else it was sent to.
    await close_buttons(db, act.SWAP_OFFER, offer, "yes", owner="owner:cafe-mei")
    await close_buttons(db, act.SWAP_OFFER, offer)
    answered = {
        m.to_agent: m.payload.get("answered")
        for m in await db.scalars(
            select(AgentMessage)
            .where(AgentMessage.type == "SURPLUS_OFFER")
            .execution_options(populate_existing=True)
        )
    }
    assert answered == {
        "owner:cafe-mei": f"sw:yes:{offer.hex}",
        "owner:brew-lab": "closed",
        "owner:teh-time": None,  # a different offer: still open
    }


async def test_a_button_the_shop_was_never_sent_does_nothing(db, world, ctx):
    before = len(await owner_messages(db, "cafe-mei"))
    await OwnerService(ctx).handle_action("cafe-mei", "zz:qq:notahex")
    sent = [
        m
        for m in await db.scalars(select(AgentMessage))
        if m.from_agent == "owner:cafe-mei" or m.to_agent == "owner:cafe-mei"
    ]
    assert len(sent) == before  # no "qq" bubble, no reply
