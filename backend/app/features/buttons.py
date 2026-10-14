"""Owner buttons stay live only while what they ask about is still open.

Whatever settles a question (the owner's tap, a typed answer, the demo's simulated owner,
the week moving on) closes the buttons that asked it, so an old message can't be answered
again. The phone greys them out; a late tap from an old Telegram message gets a reply.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentMessage

CLOSED = "closed"
# How far back to look: the open questions are always recent.
RECENT = 400


async def close_buttons(
    session: AsyncSession,
    kind: str,
    ref: uuid.UUID,
    chosen: str | None = None,
    *,
    owner: str | None = None,
) -> None:
    """Mark messages whose buttons ask about (`kind`, `ref`) as answered: with the `chosen`
    verb's button where the message has it, otherwise just closed. `owner` ("owner:cafe-mei")
    limits it to one shop's messages."""
    suffix = f":{ref.hex}"
    rows = await session.scalars(
        select(AgentMessage)
        .where(AgentMessage.to_agent.like(owner or "owner:%"))
        .order_by(AgentMessage.seq.desc())
        .limit(RECENT)
    )
    changed = False
    for message in list(rows):
        if message.payload.get("answered"):
            continue
        ids = [str(a.get("id", "")) for a in message.payload.get("actions", [])]
        if not any(i.startswith(f"{kind}:") and i.endswith(suffix) for i in ids):
            continue
        pick = f"{kind}:{chosen}{suffix}" if chosen else None
        await session.execute(
            update(AgentMessage)
            .where(AgentMessage.id == message.id)
            .values(payload={**message.payload, "answered": pick if pick in ids else CLOSED})
        )
        changed = True
    if changed:
        await session.commit()
