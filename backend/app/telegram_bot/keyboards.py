"""Inline keyboards for owner actions.

Callback data is `<shop code>|<action id>` so a chat that acts for several shops (demo mode)
always routes the press to the right shop. Telegram allows 64 bytes; if the prefix would
not fit, the bare action id is sent and the chat's current shop is used.
"""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

STYLE = {"primary": "success", "danger": "danger"}
MAX_CALLBACK_BYTES = 64


def callback_data(shop_code: str, action_id: str) -> str:
    data = f"{shop_code}|{action_id}"
    return data if len(data.encode()) <= MAX_CALLBACK_BYTES else action_id


def split_callback(data: str) -> tuple[str | None, str]:
    if "|" in data:
        shop, action_id = data.split("|", 1)
        return shop, action_id
    return None, data


def keyboard(
    shop_code: str, actions: list[dict[str, Any]], per_row: int = 2
) -> InlineKeyboardMarkup | None:
    if not actions:
        return None
    buttons = [
        InlineKeyboardButton(
            text=str(a["label"]),
            callback_data=callback_data(shop_code, str(a["id"])),
            style=STYLE.get(str(a.get("style", ""))),
        )
        for a in actions
    ]
    rows = [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(rows)
