"""Telegram glue: linking, keyboards and the notifier (no network)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.agents.bus import BusEvent
from app.db.models import Shop, TelegramChat
from app.features import actions as act
from app.telegram_bot.handlers import ChatUser, acting_shop, shops_command, start_command
from app.telegram_bot.keyboards import callback_data, keyboard, split_callback
from app.telegram_bot.notifier import TelegramNotifier

pytestmark = pytest.mark.db


def test_callback_data_fits_and_round_trips():
    action = act.action(act.SWAP_OFFER, "yes", "a" * 32, "Yes")
    data = callback_data("auntie-rose-kitchen", action["id"])
    assert len(data.encode()) <= 64
    assert split_callback(data) == ("auntie-rose-kitchen", action["id"])
    markup = keyboard("cafe-mei", [action, act.action(act.SWAP_OFFER, "no", "a" * 32, "No")])
    assert markup is not None and len(markup.inline_keyboard[0]) == 2


async def test_start_and_as_link_the_chat(db, world, ctx):
    user = ChatUser(4242, "owner", "Mei")
    assert "/start" in await start_command(ctx, user, [])
    text = await start_command(ctx, user, ["cafe-mei"])
    assert "Café Mei" in text
    assert (await acting_shop(db, 4242)).code == "cafe-mei"
    await start_command(ctx, user, ["bakery-lim"], switching=True)
    assert (await acting_shop(db, 4242)).code == "bakery-lim"
    shops = {s.code: s for s in await db.scalars(select(Shop))}
    assert shops["cafe-mei"].telegram_chat_id == 4242 == shops["bakery-lim"].telegram_chat_id
    assert "cafe-mei" in await shops_command(ctx)
    assert "don't know" in await start_command(ctx, user, ["mars-bar"])
    assert (await db.get(TelegramChat, 4242)).first_name == "Mei"


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, Any]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup: Any = None) -> None:
        self.sent.append((chat_id, text, reply_markup))


async def test_notifier_relays_owner_messages_with_buttons(db, world, ctx, runtime, monkeypatch):
    import app.telegram_bot.notifier as notifier_module

    class SessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(notifier_module, "get_sessionmaker", lambda: SessionFactory())
    await start_command(ctx, ChatUser(77), ["cafe-mei"])
    sender = FakeSender()
    notifier = TelegramNotifier(runtime, sender)
    action = act.action(act.WEEKLY_NEEDS, "ok", "b" * 32, "Approve", "primary")
    event = BusEvent(
        "agent_message",
        {"to": "owner:cafe-mei", "text": "Same as usual?", "payload": {"actions": [action]}},
    )
    assert await notifier.handle(event)
    chat_id, text, markup = sender.sent[0]
    assert chat_id == 77 and "Café Mei" in text and markup.inline_keyboard[0][0].text == "Approve"
    assert not await notifier.handle(
        BusEvent("agent_message", {"to": "owner:teh-time", "text": "x"})
    )
    assert not await notifier.handle(BusEvent("paypal", {"kind": "captured"}))
