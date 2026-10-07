"""Telegram handlers. Each one opens a database session, works out which shop the chat
speaks for, and hands over to the shared `OwnerService`; replies come back as agent
messages that the notifier relays to the chat.

Commands:
- `/start <shop code>`: link this chat to a shop.
- `/as <shop code>`: demo mode only; act as another shop from the same Telegram account.
- `/shops`: demo mode only; list the shop codes.
- `/report`: this week's savings. `/help`: what you can say.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from app.db.models import Shop, TelegramChat
from app.db.session import get_sessionmaker
from app.features.context import Ctx
from app.owners.service import OwnerService
from app.runtime import Runtime
from app.telegram_bot.keyboards import split_callback

logger = logging.getLogger(__name__)

NOT_LINKED = (
    "Hi! I'm the Swarm assistant. Link this chat to your shop with "
    "/start <shop code>, for example /start cafe-mei"
)


@dataclass
class ChatUser:
    chat_id: int
    username: str | None = None
    first_name: str | None = None


# ---------------------------------------------------------------------------------------
# Linking (plain functions, tested without Telegram)
# ---------------------------------------------------------------------------------------


async def link_chat(session: AsyncSession, user: ChatUser, shop: Shop) -> None:
    chat = await session.get(TelegramChat, user.chat_id)
    if chat is None:
        chat = TelegramChat(chat_id=user.chat_id, state={})
        session.add(chat)
    chat.shop_id = shop.id
    chat.username, chat.first_name = user.username, user.first_name
    shop.telegram_chat_id = user.chat_id
    await session.commit()


async def acting_shop(session: AsyncSession, chat_id: int) -> Shop | None:
    chat = await session.get(TelegramChat, chat_id)
    if chat is None or chat.shop_id is None:
        return None
    return await session.get(Shop, chat.shop_id)


async def start_command(ctx: Ctx, user: ChatUser, args: list[str], switching: bool = False) -> str:
    demo = ctx.runtime.settings.demo_mode
    if switching and not demo:
        return "Switching shops is only available in demo mode."
    if not args:
        return NOT_LINKED if not switching else "Use /as <shop code>, e.g. /as bakery-lim"
    shop = await ctx.session.scalar(select(Shop).where(Shop.code == args[0].lower().strip()))
    if shop is None:
        hint = " Try /shops for the list." if demo else ""
        return f"I don't know a shop called {args[0]!r}.{hint}"
    await link_chat(ctx.session, user, shop)
    mode = "REAL PayPal sandbox" if shop.paypal_mode.value == "REAL" else "simulated PayPal"
    return (
        f"✅ You're now {shop.owner_name} at {shop.name} ({mode}). I'll message you here "
        'about orders, deliveries and deals. Say "help" any time.'
    )


async def shops_command(ctx: Ctx) -> str:
    if not ctx.runtime.settings.demo_mode:
        return "This list is only available in demo mode."
    rows = await ctx.session.scalars(select(Shop).order_by(Shop.name))
    lines = [
        f"• {s.code}: {s.name} ({'REAL' if s.paypal_mode.value == 'REAL' else 'sim'})" for s in rows
    ]
    return "Shops you can act as (/as <code>):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------------------
# Telegram glue
# ---------------------------------------------------------------------------------------


def _runtime(context: ContextTypes.DEFAULT_TYPE) -> Runtime:
    runtime: Runtime = context.application.bot_data["runtime"]
    return runtime


def _user(update: Update) -> ChatUser:
    chat = update.effective_chat
    user = update.effective_user
    assert chat is not None
    return ChatUser(chat.id, user.username if user else None, user.first_name if user else None)


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_command(update, context, switching=False)


async def on_as(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_command(update, context, switching=True)


async def _reply_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, switching: bool
) -> None:
    async with get_sessionmaker()() as session:
        ctx = Ctx(session, _runtime(context))
        text = await start_command(ctx, _user(update), list(context.args or []), switching)
    if update.effective_message:
        await update.effective_message.reply_text(text)


async def on_shops(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with get_sessionmaker()() as session:
        text = await shops_command(Ctx(session, _runtime(context)))
    if update.effective_message:
        await update.effective_message.reply_text(text)


async def _with_shop(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> tuple[AsyncSession, Ctx, Shop] | None:
    session = get_sessionmaker()()
    ctx = Ctx(session, _runtime(context))
    await ctx.runtime.reload_clock(session)
    shop = await acting_shop(session, _user(update).chat_id)
    if shop is None:
        await session.close()
        if update.effective_message:
            await update.effective_message.reply_text(NOT_LINKED)
        return None
    return session, ctx, shop


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _with_shop(update, context)
    message = update.effective_message
    if found is None or message is None or message.text is None:
        return
    session, ctx, shop = found
    async with session:
        await OwnerService(ctx).handle_text(shop.code, message.text)


async def on_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _with_shop(update, context)
    if found is None:
        return
    session, ctx, shop = found
    async with session:
        await OwnerService(ctx).send_report(shop)


async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _with_shop(update, context)
    if found is None:
        return
    session, ctx, shop = found
    async with session:
        await OwnerService(ctx).handle_text(shop.code, "help")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    shop_code, action_id = split_callback(query.data)
    async with get_sessionmaker()() as session:
        ctx = Ctx(session, _runtime(context))
        await ctx.runtime.reload_clock(session)
        if shop_code is None:
            shop = await acting_shop(session, _user(update).chat_id)
            if shop is None:
                return
            shop_code = shop.code
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:  # the message may be too old to edit; the answer still counts
            logger.debug("Could not clear buttons", exc_info=True)
        await OwnerService(ctx).handle_action(shop_code, action_id)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _with_shop(update, context)
    message = update.effective_message
    if found is None or message is None or not message.photo:
        return
    session, ctx, shop = found
    largest = message.photo[-1]
    telegram_file = await largest.get_file()
    data = bytes(await telegram_file.download_as_bytearray())
    async with session:
        await OwnerService(ctx).handle_photo(shop.code, data, "image/jpeg", message.caption or "")


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Voice notes (F10, stretch): transcribed with faster-whisper when it is installed."""
    message = update.effective_message
    if message is None or message.voice is None:
        return
    from app.telegram_bot.voice import transcribe

    telegram_file = await message.voice.get_file()
    text = await transcribe(bytes(await telegram_file.download_as_bytearray()))
    if not text:
        await message.reply_text("I can't listen to voice notes yet. Please send it as text 🙏")
        return
    found = await _with_shop(update, context)
    if found is None:
        return
    session, ctx, shop = found
    async with session:
        await OwnerService(ctx).handle_text(shop.code, text)
