"""Read and write small JSON values in the `app_state` table (clock, simulator snapshot)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppState

CLOCK_KEY = "swarm_clock"
SIM_PAYPAL_KEY = "simulated_paypal"


async def get_state(session: AsyncSession, key: str) -> dict[str, Any] | None:
    row = await session.get(AppState, key)
    return dict(row.value) if row else None


async def set_state(session: AsyncSession, key: str, value: dict[str, Any]) -> None:
    statement = insert(AppState).values(key=key, value=value)
    statement = statement.on_conflict_do_update(
        index_elements=[AppState.key], set_={"value": value}
    )
    await session.execute(statement)
