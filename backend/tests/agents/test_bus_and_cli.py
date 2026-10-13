"""Message bus, the live API and the negotiation CLI."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.agents.bus import BusEvent, MessageBus
from app.cli import run_negotiation
from app.config import Settings
from app.db.enums import Category
from app.db.session import get_session
from app.llm.client import OfflineLLM
from app.main import create_app
from app.paypal.accounts import GatewayRegistry
from app.runtime import Runtime
from tests.conftest import DEMO_WEEK

pytestmark = pytest.mark.db


async def test_publish_stores_and_streams(db, clock, bus):
    queue = bus.subscribe()
    message = await bus.publish(
        db,
        conversation_id="c1",
        from_agent="shop:cafe-mei",
        to_agent="coordinator:swarm",
        type="JOIN",
        text="In!",
    )
    event = queue.get_nowait()
    assert event.event == "agent_message" and event.data["seq"] == message.seq
    await bus.emit("captured", {"shop": "cafe-mei", "amount_cents": 900})
    assert queue.get_nowait().data["kind"] == "captured"
    bus.unsubscribe(queue)
    assert bus.subscriber_count == 0


async def test_slow_subscribers_drop_the_oldest_events(clock):
    bus = MessageBus(clock, queue_size=2)
    queue = bus.subscribe()
    for n in range(3):
        bus.broadcast(BusEvent("tick", {"n": n}))
    assert [queue.get_nowait().data["n"] for _ in range(2)] == [1, 2]


async def test_sse_stream_says_hello_then_relays_events(clock):
    bus = MessageBus(clock)
    stream = bus.sse(heartbeat=0.05)
    assert (await anext(stream)).startswith("event: hello")
    # Nothing to replay for a first visit: it is caught up straight away.
    assert (await anext(stream)).startswith("event: caught_up")
    waiting = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    bus.broadcast(BusEvent("paypal", {"kind": "hold_placed"}))
    chunk = await asyncio.wait_for(waiting, 1)
    assert chunk.startswith("event: paypal") and '"hold_placed"' in chunk
    assert await asyncio.wait_for(anext(stream), 1) == ": keep-alive\n\n"
    await stream.aclose()


async def test_a_reset_starts_a_new_epoch_and_says_so(clock):
    bus = MessageBus(clock)
    before = bus.epoch
    queue = bus.subscribe()
    await bus.emit("captured", {"shop": "cafe-mei"})
    assert bus.epoch == before and "epoch" not in queue.get_nowait().data

    await bus.emit("reset", {"week": "2026-10-12"})
    told = queue.get_nowait().data
    assert bus.epoch != before and told["epoch"] == bus.epoch

    hello = await anext(bus.sse(heartbeat=0.05))
    assert json.loads(hello.split("data: ")[1])["epoch"] == bus.epoch


async def test_a_position_from_before_a_reset_is_not_replayed(clock):
    from app.api.live import stream

    bus = MessageBus(clock)

    async def chunks(**asked) -> list[str]:
        response = await stream(bus, **asked)
        body = response.body_iterator
        seen = [await anext(body), await anext(body)]
        await body.aclose()
        return [chunk.split("\n")[0] for chunk in seen]

    # No position, or one from another epoch: hello, then caught up with nothing replayed.
    nothing = ["event: hello", "event: caught_up"]
    assert await chunks(last_event_id=None, after=None, epoch=None) == nothing
    assert await chunks(last_event_id=None, after=40, epoch="stale") == nothing
    assert bus.subscriber_count == 0


async def test_agent_messages_api(db, bus):
    await bus.publish(
        db, conversation_id="negotiation:x", from_agent="a", to_agent="b", type="RFQ", text="hello"
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as api:
        rows = (
            await api.get("/api/agent-messages", params={"conversation_id": "negotiation:x"})
        ).json()
    assert [r["type"] for r in rows] == ["RFQ"]


async def test_cli_negotiation_prints_the_conversation(db, world, clock, bus):
    runtime = Runtime(
        Settings(), clock, GatewayRegistry(Settings(), clock=clock), bus, OfflineLLM()
    )
    lines: list[str] = []
    groups = await run_negotiation(db, runtime, DEMO_WEEK, [Category.DAIRY], out=lines.append)
    output = "\n".join(lines)
    assert len(groups) == 1
    for expected in ("MONDAY", "TUESDAY", "RFQ", "FINAL_QUOTE", "AWARD", "Result:", "Shops save"):
        assert expected in output
