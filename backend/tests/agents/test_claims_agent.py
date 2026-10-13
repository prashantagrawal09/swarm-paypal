"""Claims: the model reads the photo, code decides the refund."""

from __future__ import annotations

import pytest

from app.agents.claims_agent import NO_PHOTO, NOT_REVIEWED, ClaimAssessment, ClaimsAgent, decide
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


NOTHING_SEEN = assessment(
    issue_type="UNCLEAR", claim_supported=False, confidence=0.0, qty_affected=0
)


def test_an_unreviewed_claim_puts_the_owners_count_at_stake():
    outcome = decide(claim(qty=3), line(800), NOTHING_SEEN, reviewed=False)
    assert outcome.decision == ClaimDecision.ESCALATED_OPERATOR
    assert (outcome.qty, outcome.refund_cents, outcome.reason) == (3, 2400, NO_PHOTO)


def test_an_unreviewed_claim_never_puts_more_at_stake_than_was_delivered():
    outcome = decide(claim(qty=40), line(800, delivered=6), NOTHING_SEEN, reviewed=False)
    assert (outcome.qty, outcome.refund_cents) == (6, 4800)


def test_a_photo_nothing_could_read_is_described_as_unchecked():
    with_photo = claim(qty=1)
    with_photo.photo_url = "/api/media/abc"
    outcome = decide(with_photo, line(800), NOTHING_SEEN, reviewed=False)
    assert (outcome.refund_cents, outcome.reason) == (800, NOT_REVIEWED)


def test_when_the_photo_is_unclear_a_person_rules_on_what_the_owner_claimed():
    # The model made out one damaged unit of the three claimed, but wasn't sure of anything.
    unsure = assessment(issue_type="UNCLEAR", confidence=0.3, qty_affected=1)
    outcome = decide(claim(qty=3), line(800), unsure)
    assert (outcome.decision, outcome.refund_cents) == (ClaimDecision.ESCALATED_OPERATOR, 2400)


def test_a_confirmed_problem_nobody_could_count_goes_to_the_supplier_at_the_owners_count():
    uncounted = assessment(qty_affected=0)
    outcome = decide(claim(qty=3), line(800), uncounted)
    assert (outcome.decision, outcome.refund_cents) == (ClaimDecision.ESCALATED_SUPPLIER, 2400)


def test_every_claim_left_open_has_money_at_stake():
    """An open claim's amount is what is held back from the supplier, so it is never zero."""
    open_decisions = {ClaimDecision.ESCALATED_OPERATOR, ClaimDecision.ESCALATED_SUPPLIER}
    seen = set()
    for issue in ("SHORT", "DAMAGED", "EXPIRED", "WRONG_ITEM", "NONE", "UNCLEAR"):
        for supported in (True, False):
            for confidence in (0.0, 0.3, 0.5, 0.7, 0.8, 0.95):
                for counted in (0, 1, 3, 30):
                    for reviewed in (True, False):
                        outcome = decide(
                            claim(qty=3),
                            line(800),
                            assessment(
                                issue_type=issue,
                                claim_supported=supported,
                                confidence=confidence,
                                qty_affected=counted,
                            ),
                            reviewed=reviewed,
                        )
                        seen.add(outcome.decision)
                        if outcome.decision in open_decisions:
                            assert 0 < outcome.refund_cents <= 3 * 800
                        elif outcome.decision == ClaimDecision.REJECTED:
                            assert outcome.refund_cents == 0
                        else:  # refunded on the spot: within the limit, never above the claim
                            assert 0 < outcome.refund_cents <= min(3 * 800, 5000)
    assert seen == {*open_decisions, ClaimDecision.REJECTED, ClaimDecision.AUTO_REFUNDED}


def test_a_supported_claim_is_refunded_for_what_the_photo_shows_not_what_was_claimed():
    outcome = decide(claim(qty=3), line(800), assessment(qty_affected=1))
    assert (outcome.decision, outcome.refund_cents) == (ClaimDecision.AUTO_REFUNDED, 800)


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
    # Nothing is refunded, but what the owner claimed is now at stake until a person decides.
    assert result.amount_cents == so.lines[0].agreed_unit_price_cents
    assert result.ai_assessment["decision_reason"] == NO_PHOTO
    assert result.ai_assessment["evidence"] == "No photo was sent."
