"""Signed owner links.

Outside demo mode, a shop is only ever acted for by its owner:

- Telegram: the operator sends the owner an invite (`/start <code>_<expiry>_<signature>`),
  so nobody can link a chat to a shop by guessing its code.
- Connect PayPal: the bot hands the linked owner a link carrying a token for that one shop;
  the connect API refuses anything else, so nobody can attach their wallet to a shop.

Tokens are `<expiry>_<signature>`: an HMAC-SHA256 over purpose, shop and expiry, keyed by
SECRET_KEY. The format only uses characters Telegram allows in /start payloads.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

from app.config import Settings

TTL = {"connect": timedelta(days=2), "telegram": timedelta(days=7)}


class LinkError(Exception):
    pass


def _secret(settings: Settings) -> bytes:
    if settings.secret_key is None or not settings.secret_key.get_secret_value():
        raise LinkError("Owner links are off until SECRET_KEY is set.")
    return settings.secret_key.get_secret_value().encode()


def _signature(secret: bytes, purpose: str, shop_code: str, expires: int) -> str:
    message = f"{purpose}:{shop_code}:{expires}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()[:24]


def sign(settings: Settings, shop_code: str, now: datetime, purpose: str) -> str:
    expires = int((now + TTL[purpose]).timestamp())
    return f"{expires}_{_signature(_secret(settings), purpose, shop_code, expires)}"


def verify(
    settings: Settings, shop_code: str, token: str | None, now: datetime, purpose: str
) -> None:
    """Raises LinkError unless `token` is a live link for this shop and purpose."""
    expires_text, _, signature = (token or "").partition("_")
    if not expires_text.isdigit() or not signature:
        raise LinkError("This link is incomplete. Ask Swarm for a new one.")
    expected = _signature(_secret(settings), purpose, shop_code, int(expires_text))
    if not hmac.compare_digest(expected, signature):
        raise LinkError("This link isn't valid for this shop.")
    if now.timestamp() > int(expires_text):
        raise LinkError("This link has expired. Ask Swarm for a new one.")


def connect_link(settings: Settings, shop_code: str, now: datetime) -> str:
    token = sign(settings, shop_code, now, "connect")
    return f"{settings.public_frontend_url.rstrip('/')}/connect/{shop_code}?t={token}"


def telegram_invite(settings: Settings, shop_code: str, now: datetime) -> str:
    """The /start payload for an owner's invite (fits Telegram's 64-character limit)."""
    return f"{shop_code}_{sign(settings, shop_code, now, 'telegram')}"


def parse_invite(settings: Settings, payload: str, now: datetime) -> str:
    """Returns the shop code of a valid invite payload, or raises LinkError."""
    shop_code, _, token = payload.partition("_")
    verify(settings, shop_code, token, now, "telegram")
    return shop_code
