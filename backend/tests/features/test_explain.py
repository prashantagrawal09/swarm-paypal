"""The home page's worked examples must be the pricing rules, not a story about them."""

from __future__ import annotations

import pytest

from app.features import explain
from app.features.context import Ctx
from app.money import pricing

pytestmark = pytest.mark.db


@pytest.fixture
async def examples(db, world, runtime):
    result = await explain.worked_examples(Ctx(db, runtime))
    assert result is not None
    return result


async def test_pooling_walks_down_the_suppliers_own_tiers(examples):
    tiers = pricing.parse_tiers(examples["pooling"]["tiers"])
    steps = examples["pooling"]["steps"]
    assert [step["shops"] for step in steps] == list(range(1, 13))
    assert steps[0]["joined"]["code"] == "cafe-mei"
    assert examples["supplier"]["code"] == "johorfarm"  # the lowest price at full volume

    total = 0
    alone = 0
    for step in steps:
        qty = step["joined"]["qty"]
        total += qty
        alone += qty * pricing.tier_unit_price(tiers, qty)
        assert step["qty"] == total
        assert step["unit_price_cents"] == pricing.tier_unit_price(tiers, total)
        assert step["pooled_cents"] == total * step["unit_price_cents"]
        assert step["alone_cents"] == alone
        assert step["saved_cents"] == alone - step["pooled_cents"]

    prices = [step["unit_price_cents"] for step in steps]
    assert prices == sorted(prices, reverse=True)  # more shops never cost more per unit
    assert (prices[0], prices[-1]) == (245, 196)
    assert steps[0]["saved_cents"] == 0  # one shop "pooling" saves nothing
    assert steps[-1]["qty"] == 276 and steps[-1]["saved_cents"] > 10_000


async def test_short_delivery_charges_for_what_arrived_and_releases_the_rest(examples):
    delivery = examples["delivery"]
    rows = delivery["rows"]
    ordered, hold = delivery["ordered"], delivery["hold_cents"]
    assert delivery["shop"]["code"] == "cafe-mei" and ordered == 34
    assert [row["delivered"] for row in rows] == list(range(ordered + 1))
    assert hold == ordered * delivery["unit_price_cents"] + delivery["delivery_share_cents"]

    assert rows[0] == {"delivered": 0, "charged_cents": 0, "released_cents": hold}
    assert rows[-1] == {"delivered": ordered, "charged_cents": hold, "released_cents": 0}
    charged = [row["charged_cents"] for row in rows]
    assert charged == sorted(charged)
    for row in rows:
        # Never more than the hold, and nothing is created or lost.
        assert 0 <= row["charged_cents"] <= hold
        assert row["charged_cents"] + row["released_cents"] == hold
    # The delivery share shrinks with the weight that arrived, as on a real short delivery.
    thirty = rows[30]
    assert thirty["charged_cents"] == 30 * delivery["unit_price_cents"] + (
        delivery["delivery_share_cents"] * 30 // ordered
    )


async def test_the_fee_is_split_across_everyone_who_ordered(examples, db):
    delivery = examples["delivery"]
    assert 0 < delivery["delivery_share_cents"] < delivery["delivery_fee_cents"]


async def test_endpoint(db, world, runtime):
    import httpx

    from app.api.deps import runtime_dep
    from app.db.session import get_session
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[runtime_dep] = lambda: runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as api:
        body = (await api.get("/api/explain")).json()
    assert body["product"]["code"] == "milk-full-cream-1l"
    assert len(body["pooling"]["steps"]) == 12
