"""Supplier agent: legal price options, its policy, and the mandate gate."""

from __future__ import annotations

import uuid

import pytest

from app.agents.base import Action
from app.agents.bus import MessageBus
from app.agents.supplier_agent import RFQ, SupplierAgent
from app.clock import SwarmClock
from app.db.models import Supplier, SupplierItem
from app.features.group_buy import SupplierOffer
from app.llm.client import OfflineLLM

QTY = {"milk": 300, "eggs": 100}


def make_agent(style: str = "steady, concedes slowly", stock: int = 1000) -> SupplierAgent:
    supplier = Supplier(
        code="fd",
        name="FreshDairy SG",
        delivery_fee_cents=3500,
        reliability_score=95,
        profile={"style": style},
    )
    supplier.id = uuid.uuid4()
    items = {
        "milk": SupplierItem(
            price_tiers=[
                {"min_qty": 1, "unit_price_cents": 260},
                {"min_qty": 200, "unit_price_cents": 205},
            ],
            floor_price_cents=192,
            stock_limit=stock,
        ),
        "eggs": SupplierItem(
            price_tiers=[
                {"min_qty": 1, "unit_price_cents": 950},
                {"min_qty": 60, "unit_price_cents": 840},
            ],
            floor_price_cents=790,
            stock_limit=stock,
        ),
    }
    clock = SwarmClock()
    return SupplierAgent(
        supplier,
        SupplierOffer(supplier, items),
        llm=OfflineLLM(),
        bus=MessageBus(clock),
        clock=clock,
    )


def rfq(round_number: int, final: bool = False, best: int | None = None) -> RFQ:
    return RFQ(uuid.uuid4(), "DAIRY", round_number, final, QTY, 12, "Thursday", best)


def test_opening_options_start_at_list_and_never_go_below_floor():
    agent = make_agent()
    options = {o.label: o for o in agent.options(rfq(1))}
    assert options["hold"].unit_prices == {"milk": 205, "eggs": 840}
    assert "floor" not in options
    for option in options.values():
        assert option.unit_prices["milk"] >= 192 and option.unit_prices["eggs"] >= 790
    assert options["deep"].landed_total_cents < options["small"].landed_total_cents


def test_final_round_offers_the_floor_and_never_raises_prices():
    agent = make_agent()
    agent.previous = {"milk": 200, "eggs": 820}
    options = {o.label: o for o in agent.options(rfq(3, final=True))}
    assert options["floor"].unit_prices == {"milk": 192, "eggs": 790}
    for option in options.values():
        assert option.unit_prices["milk"] <= 200 and option.unit_prices["eggs"] <= 820


def test_beat_option_undercuts_the_best_rival_by_half_a_percent():
    agent = make_agent()
    hold = next(o for o in agent.options(rfq(2)) if o.label == "hold")
    best = hold.landed_total_cents - 2000
    beat = next(o for o in agent.options(rfq(2, best=best)) if o.label == "beat")
    assert beat.landed_total_cents <= best * 9950 // 10000
    impossible = [o.label for o in agent.options(rfq(2, best=1000))]
    assert "beat" not in impossible


def test_policy_follows_the_supplier_style():
    steady, hungry = make_agent(), make_agent("hungry, competes hard")
    assert steady.policy(rfq(1), steady.options(rfq(1))) == "hold"
    assert hungry.policy(rfq(1), hungry.options(rfq(1))) == "small"
    final = rfq(3, final=True, best=1000)  # cannot be beaten
    assert hungry.policy(final, hungry.options(final)) == "floor"
    assert steady.policy(final, steady.options(final)) == "deep"


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (
            Action("submit_quote", {"unit_prices": {"milk": 150, "eggs": 800}, "quantities": QTY}),
            "BELOW_FLOOR",
        ),
        (
            Action("submit_quote", {"unit_prices": {"milk": 200}, "quantities": QTY}),
            "INCOMPLETE_QUOTE",
        ),
        (
            Action(
                "submit_quote",
                {"unit_prices": {"milk": 200, "caviar": 9}, "quantities": {"milk": 1, "caviar": 1}},
            ),
            "NOT_STOCKED",
        ),
        (Action("award_myself", {}), "TOOL_NOT_ALLOWED"),
    ],
)
def test_gate_refuses_actions_outside_the_mandate(action, code):
    verdict = make_agent().validate(action)
    assert not verdict.ok and verdict.code == code


def test_gate_refuses_price_rises_and_overselling():
    agent = make_agent(stock=50)
    verdict = agent.validate(
        Action("submit_quote", {"unit_prices": {"milk": 200, "eggs": 800}, "quantities": QTY})
    )
    assert verdict.code == "OUT_OF_STOCK"
    agent = make_agent()
    agent.previous = {"milk": 199, "eggs": 800}
    verdict = agent.validate(
        Action("counter_offer", {"unit_prices": {"milk": 200, "eggs": 800}, "quantities": QTY})
    )
    assert verdict.code == "PRICE_RAISED"
