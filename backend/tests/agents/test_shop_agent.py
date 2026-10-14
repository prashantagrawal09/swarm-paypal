"""Shop agent: Monday proposal, confirmation, owner messages, award news."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.base import MandateViolation
from app.agents.shop_agent import ShopAgent, keyword_intent
from app.db.enums import ApprovalKind, ApprovalStatus, Category, ForecastStatus
from app.db.models import AgentMessage, ApprovalRequest, AuditLog, DemandForecast
from app.features import group_buy
from app.llm.client import OfflineLLM, ScriptedLLM
from tests.conftest import DEMO_WEEK
from tests.helpers import prepare_week, shops_by_code

pytestmark = pytest.mark.db


async def agent_for(db, code, clock, bus, llm=None) -> ShopAgent:
    shop = (await shops_by_code(db))[code]
    return ShopAgent(shop, llm=llm or OfflineLLM(), bus=bus, clock=clock)


async def test_monday_proposal_asks_the_owner(db, world, clock, bus):
    agent = await agent_for(db, "cafe-mei", clock, bus)
    approval, forecasts = await agent.weekly_proposal(db, DEMO_WEEK)
    assert approval.kind == ApprovalKind.WEEKLY_NEEDS and approval.status == ApprovalStatus.PENDING
    assert "L milk" in approval.question and approval.question.endswith("Shall I order that?")
    assert "Based on your last" in approval.question
    assert len(approval.payload["items"]) == len(forecasts) == 8
    message = await db.scalar(select(AgentMessage).where(AgentMessage.type == "WEEKLY_NEEDS"))
    assert message.to_agent == "owner:cafe-mei"
    assert [a["label"] for a in message.payload["actions"]] == ["Approve", "Change", "Skip"]
    assert message.payload["actions"][0]["id"] == f"wn:ok:{approval.id.hex}"


async def test_confirm_with_a_change_and_join_the_pool(db, world, clock, bus):
    agent = await agent_for(db, "cafe-mei", clock, bus)
    await agent.weekly_proposal(db, DEMO_WEEK)
    rows = await agent.confirm_needs(
        db, DEMO_WEEK, {"cooking-oil-2l": 0, "milk-full-cream-1l": 40}, owner_changed=True
    )
    assert {r.status for r in rows} == {ForecastStatus.CONFIRMED}
    milk = next(r for r in rows if r.confirmed_qty == 40)
    assert milk is not None
    approval = await db.scalar(select(ApprovalRequest))
    assert approval.status == ApprovalStatus.APPROVED
    join = await db.scalar(select(AgentMessage).where(AgentMessage.type == "JOIN"))
    assert "40 L milk" in join.text


async def test_unusual_quantities_need_the_owner(db, world, clock, bus):
    agent = await agent_for(db, "teh-time", clock, bus)
    await agent.weekly_proposal(db, DEMO_WEEK)
    with pytest.raises(MandateViolation) as exc:
        await agent.confirm_needs(db, DEMO_WEEK, {"milk-full-cream-1l": 500})
    assert exc.value.verdict.code == "UNUSUAL_QTY"
    refused = await db.scalar(
        select(AuditLog).where(AuditLog.action == "refused:confirm_weekly_needs")
    )
    assert refused is not None
    assert not list(
        await db.scalars(
            select(DemandForecast).where(DemandForecast.status == ForecastStatus.CONFIRMED)
        )
    )


@pytest.mark.parametrize(
    ("text", "intent", "product", "qty"),
    [
        ("Out of eggs, need 30 now", "emergency_request", "eggs-tray-30", 30),
        ("8 L milk expiring Sunday", "report_surplus", "milk-full-cream-1l", 8),
        ("need extra oil this week, CNY coming", "adjust_needs", "cooking-oil-2l", None),
        ("We're closed next week, skip please", "skip_week", None, None),
        ("What did I save last week?", "question", None, None),
    ],
)
def test_keyword_fallback_understands_common_messages(text, intent, product, qty):
    parsed = keyword_intent(text)
    assert (parsed.intent, parsed.product_code, parsed.qty) == (intent, product, qty)


@pytest.mark.parametrize(
    ("text", "qty", "change", "unit"),
    [
        ("4 L less milk", 4, "less", "l"),
        ("2 crates of milk less next week", 2, "less", "crates"),
        ("need 30 L milk this week", 30, "set", "l"),
        ("need extra oil this week", None, "more", None),
        ("add 2 trays of eggs", 2, "more", "trays"),
        ("fewer napkins please", None, "less", None),
        ("need more 12oz cups", None, "more", None),
    ],
)
def test_quantity_changes_keep_their_direction_and_unit(text, qty, change, unit):
    parsed = keyword_intent(text)
    assert parsed.intent == "adjust_needs"
    assert (parsed.qty, parsed.change, parsed.unit) == (qty, change, unit)


async def test_model_intents_are_checked_against_the_catalog(db, world, clock, bus):
    llm = ScriptedLLM(
        {
            "shop_agent.interpret": {
                "intent": "adjust_needs",
                "product_code": "caviar",
                "qty": 3,
                "note": "",
            }
        }
    )
    agent = await agent_for(db, "cafe-mei", clock, bus, llm)
    assert (await agent.interpret("more caviar please")).intent == "other"
    llm.answers["shop_agent.interpret"] = {
        "intent": "adjust_needs",
        "product_code": "cooking-oil-2l",
        "qty": 9999,
    }
    parsed = await agent.interpret("loads of oil")
    assert parsed.product_code == "cooking-oil-2l" and parsed.qty is None
    content = llm.calls[-1][1]
    assert '<owner_message from="owner:cafe-mei"' in content


async def test_award_news_mentions_the_saving_and_skipped_brands(db, world, clock, bus):
    groups = await prepare_week(db, DEMO_WEEK, clock)
    await group_buy.award_at_list_prices(db, groups[Category.DAIRY].id)
    group = await group_buy.load_group(db, groups[Category.DAIRY].id)
    text = await (await agent_for(db, "sunrise-bakes", clock, bus)).explain_award(db, group)
    assert "less than buying alone" in text
    assert "I left out milk" in text
