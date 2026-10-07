"""Owner action buttons carried in agent messages.

An action id doubles as Telegram `callback_data` (max 64 bytes): `<kind>:<verb>:<ref>`, where
ref is a UUID in hex (32 chars). The web phone sends the same id back, so both channels
share one handler (`app.owners.service`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

# kind codes
WEEKLY_NEEDS = "wn"
OVER_LIMIT = "ol"
DELIVERY = "dl"
SWAP_OFFER = "sw"
HANDOVER = "ho"
EMERGENCY = "em"
FLASH_DEAL = "fd"
CLAIM = "cl"
REPORT = "rp"


def action(
    kind: str, verb: str, ref: uuid.UUID | str, label: str, style: str = "default"
) -> dict[str, str]:
    ref_hex = ref.hex if isinstance(ref, uuid.UUID) else ref
    action_id = f"{kind}:{verb}:{ref_hex}"
    if len(action_id.encode()) > 64:
        raise ValueError("Action ids must fit Telegram's 64-byte callback data")
    return {"id": action_id, "label": label, "style": style}


@dataclass(frozen=True)
class ParsedAction:
    kind: str
    verb: str
    ref: uuid.UUID | None


def parse_action(action_id: str) -> ParsedAction:
    kind, verb, ref = [*action_id.split(":", 2), "", ""][:3]
    try:
        parsed_ref = uuid.UUID(hex=ref) if ref else None
    except ValueError:
        parsed_ref = None
    return ParsedAction(kind, verb, parsed_ref)
