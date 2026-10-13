"""The recorded live stream: what the watch page replays and reconnecting browsers catch up on."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.agents.bus import BusEvent, MessageBus
from app.agents.recorder import StreamRecorder, recorded
from app.clock import week_start
from app.db.models import StreamEvent
from tests.conftest import DEMO_WEEK

pytestmark = pytest.mark.db


@pytest.fixture
async def sessions(db, test_database_url):
    """A second way into the test database, as the running app's recorder has."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def recording_bus(clock, sessions) -> MessageBus:
    bus = MessageBus(clock)
    bus.recorder = StreamRecorder(sessions, clock.now)
    return bus


async def say(bus: MessageBus, db, text: str):
    return await bus.publish(
        db,
        conversation_id="c1",
        from_agent="shop:cafe-mei",
        to_agent="coordinator",
        type="JOIN",
        text=text,
    )


async def test_the_stream_is_recorded_in_the_order_it_was_sent(recording_bus, db, clock):
    queue = recording_bus.subscribe()
    await say(recording_bus, db, "first")
    await recording_bus.emit("hold_placed", {"shop": "cafe-mei", "amount_cents": 1250})
    await recording_bus.emit("demo_action", {"action": "advance"})  # housekeeping
    await recording_bus.emit("reset", {"week": "2026-10-12"})  # housekeeping
    await say(recording_bus, db, "second")

    rows = await recorded(db)
    assert [(r.event, r.data.get("text") or r.data.get("kind")) for r in rows] == [
        ("agent_message", "first"),
        ("paypal", "hold_placed"),
        ("agent_message", "second"),
    ]
    assert [r.seq for r in rows] == sorted(r.seq for r in rows)
    assert {r.week_start for r in rows} == {DEMO_WEEK}
    assert rows[1].data["amount_cents"] == 1250 and rows[1].data["at"] == clock.now().isoformat()

    # Everyone connected still gets all five; the recorded ones carry their position.
    sent = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [e.seq for e in sent] == [rows[0].seq, rows[1].seq, None, None, rows[2].seq]
    assert f"id: {rows[0].seq}\n" in sent[0].to_sse()
    assert not sent[2].to_sse().startswith("id:")


async def test_a_week_can_be_read_back_from_any_position(recording_bus, db, clock):
    for text in ("a", "b", "c"):
        await say(recording_bus, db, text)
    clock.advance(days=7)
    await say(recording_bus, db, "next week")

    this_week = await recorded(db, week=DEMO_WEEK)
    assert [r.data["text"] for r in this_week] == ["a", "b", "c"]
    later = await recorded(db, week=DEMO_WEEK, after=this_week[0].seq)
    assert [r.data["text"] for r in later] == ["b", "c"]
    assert [r.data["text"] for r in await recorded(db, after=this_week[-1].seq)] == ["next week"]
    assert [r.data["text"] for r in await recorded(db, limit=2)] == ["a", "b"]


async def test_old_weeks_are_dropped_when_a_new_week_starts(recording_bus, db, clock):
    await say(recording_bus, db, "long ago")
    clock.advance(days=21)
    await say(recording_bus, db, "three weeks later")
    clock.advance(days=21)
    await recording_bus.emit("step_started", {"step": "forecasts", "title": "Monday"})

    texts = [r.data.get("text") or r.data.get("kind") for r in await recorded(db)]
    assert texts == ["three weeks later", "step_started"]


async def test_a_failing_recorder_never_stops_the_week(clock, db):
    async def broken(event: str, data: dict) -> int:
        raise RuntimeError("database is away")

    bus = MessageBus(clock)
    bus.recorder = broken
    queue = bus.subscribe()
    await bus.emit("captured", {"shop": "cafe-mei"})
    await say(bus, db, "still here")

    assert [queue.get_nowait().seq for _ in range(2)] == [None, None]
    assert await db.scalar(select(func.count()).select_from(StreamEvent)) == 0


async def test_values_are_stored_as_the_browser_sees_them(recording_bus, db):
    import uuid
    from datetime import date

    order = uuid.uuid4()
    await recording_bus.emit("captured", {"shop_order_id": order, "week": date(2026, 10, 12)})
    (row,) = await recorded(db)
    assert row.data["shop_order_id"] == str(order) and row.data["week"] == "2026-10-12"
    assert week_start(recording_bus.clock.now()) == row.week_start


async def test_a_reconnecting_browser_catches_up_without_duplicates(clock):
    bus = MessageBus(clock)

    async def missed() -> list[BusEvent]:
        # Events 4 and 5 were recorded while the browser was away. By the time the catch-up
        # is read, event 5 has also been sent live to the new subscription.
        bus.broadcast(BusEvent("paypal", {"kind": "captured"}, 5))
        return [
            BusEvent("paypal", {"kind": "hold_placed"}, 4),
            BusEvent("paypal", {"kind": "captured"}, 5),
        ]

    stream = bus.sse(heartbeat=0.05, missed=missed)
    hello = await anext(stream)
    assert hello.startswith("event: hello")
    first, second = await anext(stream), await anext(stream)
    assert first.startswith("id: 4\n") and second.startswith("id: 5\n")
    # The replay is over: the browser can tell old news from what is happening now.
    marker = await anext(stream)
    assert marker.startswith("event: caught_up") and json.loads(marker.split("data: ")[1]) == {
        "seq": 5
    }

    bus.broadcast(BusEvent("paypal", {"kind": "supplier_paid"}, 6))
    bus.broadcast(BusEvent("paypal", {"kind": "demo_action"}))  # unrecorded: always sent
    third, fourth = await anext(stream), await anext(stream)
    assert third.startswith("id: 6\n") and json.loads(third.split("data: ")[1])["kind"] == (
        "supplier_paid"
    )
    assert "demo_action" in fourth and not fourth.startswith("id:")
    await stream.aclose()
    assert bus.subscriber_count == 0


async def test_timeline_offers_the_last_recorded_week_until_a_new_one_starts(
    recording_bus, db, clock
):
    from app.api.live import timeline

    await say(recording_bus, db, "last week's news")
    clock.advance(days=7)

    body = await timeline(db, clock, None, 0)
    assert body["week"] == str(DEMO_WEEK) and len(body["events"]) == 1
    # Asking only for what is new never falls back: there is nothing new this week.
    assert (await timeline(db, clock, None, body["last_seq"]))["events"] == []

    await say(recording_bus, db, "this week has begun")
    body = await timeline(db, clock, None, 0)
    assert [e["data"]["text"] for e in body["events"]] == ["this week has begun"]
