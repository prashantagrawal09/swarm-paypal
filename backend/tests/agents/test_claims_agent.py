"""Claims: the model reads the photo, code decides the refund."""

from __future__ import annotations

import pytest

from app.agents.claims_agent import ClaimAssessment, ClaimsAgent, decide
from app.db.enums import Category, ClaimDecision, ClaimType, PaymentKind
from app.db.models import Claim, GroupOrderLine, Payment
from app.features import group_buy
from app.llm.client import ScriptedLLM
from app.money import ledger
from tests.conftest import DEMO_WEEK
from tests.helpers import awarded

PHOTO = b"\x89PNG\r\n\x1a\n fake image bytes"


def assessment(**overrides) -> ClaimAssessment:
    base = {
        "issue_type": "DAMAGED",
        "claim_supported": True,
        "confidence": 0.92,
        "qty_affected": 2,
        "evidence": "Two crushed trays visible.",
    }
    return ClaimAssessment(**{**base, **overrides})


def line(price: int = 800, delivered: int = 10) -> GroupOrderLine:
    return GroupOrderLine(qty_requested=10, qty_delivered=delivered, agreed_unit_price_cents=price)


def claim(kind: ClaimType = ClaimType.DAMAGED, qty: int = 2) -> Claim:
    return Claim(type=kind, qty_affected=qty, description="Crushed trays")


@pytest.mark.parametrize(
    ("assessed", "claimed", "price", "decision", "refund"),
    [
        (assessment(), claim(), 800, ClaimDecision.AUTO_REFUNDED, 1600),
        (assessment(confidence=0.7), claim(), 800, ClaimDecision.ESCALATED_SUPPLIER, 1600),
        (assessment(qty_affected=9), claim(qty=9), 800, ClaimDecision.ESCALATED_SUPPLIER, 7200),
        (assessment(issue_type="EXPIRED"), claim(), 800, ClaimDecision.ESCALATED_SUPPLIER, 1600),
        (
            assessment(issue_type="UNCLEAR", confidence=0.3),
            claim(),
            800,
            ClaimDecision.ESCALATED_OPERATOR,
            1600,
        ),
        (
            assessment(issue_type="NONE", claim_supported=False, confidence=0.95),
            claim(),
            800,
            ClaimDecision.REJECTED,
            0,
        ),
        (assessment(qty_affected=50), claim(qty=50), 100, ClaimDecision.AUTO_REFUNDED, 1000),
    ],
)
def test_code_decides_from_the_assessment(assessed, claimed, price, decision, refund):
    outcome = decide(claimed, line(price), assessed)
    assert (outcome.decision, outcome.refund_cents) == (decision, refund)


@pytest.mark.db
async def test_confident_small_claim_is_refunded_through_paypal(db, world, clock, engine, bus):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    await group_buy.record_delivery(db, group.id, clock.now())
    await engine.capture_group_order(group.id)
    group = await group_buy.load_group(db, group.id)
    so = group.shop_orders[0]
    target = so.lines[0]
    record = Claim(
        shop_id=so.shop_id,
        shop_order_id=so.id,
        group_order_line_id=target.id,
        type=ClaimType.DAMAGED,
        qty_affected=1,
        description="Bruised, see photo",
    )
    db.add(record)
    await db.commit()

    llm = ScriptedLLM({"claims_agent.assess": lambda content: assessment(qty_affected=1)})
    agent = ClaimsAgent(llm=llm, bus=bus, clock=clock)
    result = await agent.process(db, engine, record.id, PHOTO, "image/png")
    assert result.decision == ClaimDecision.AUTO_REFUNDED
    payment = await db.get(Payment, result.refund_payment_id)
    assert (
        payment.kind == PaymentKind.REFUND
        and payment.amount_cents == target.agreed_unit_price_cents
    )
    image_block = llm.calls[0][1][0]
    assert image_block["type"] == "image" and image_block["source"]["media_type"] == "image/png"
    assert await ledger.unbalanced_transactions(db) == []


@pytest.mark.db
async def test_no_photo_means_a_person_decides(db, world, clock, engine, bus):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    await group_buy.record_delivery(db, group.id, clock.now())
    await engine.capture_group_order(group.id)
    so = (await group_buy.load_group(db, group.id)).shop_orders[0]
    record = Claim(
        shop_id=so.shop_id,
        shop_order_id=so.id,
        group_order_line_id=so.lines[0].id,
        type=ClaimType.SHORT,
        qty_affected=1,
    )
    db.add(record)
    await db.commit()
    result = await ClaimsAgent(llm=ScriptedLLM(), bus=bus, clock=clock).process(
        db, engine, record.id
    )
    assert result.decision == ClaimDecision.ESCALATED_OPERATOR
    assert result.refund_payment_id is None
