"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.features.context import Ctx
from app.runtime import Runtime, get_runtime


def runtime_dep() -> Runtime:
    return get_runtime()


async def get_ctx(
    session: Annotated[AsyncSession, Depends(get_session)],
    runtime: Annotated[Runtime, Depends(runtime_dep)],
) -> AsyncIterator[Ctx]:
    await runtime.reload_clock(session)
    yield Ctx(session, runtime)


def require_demo_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_demo_key: Annotated[str | None, Header()] = None,
) -> None:
    """Demo actions can be locked with DEMO_PANEL_KEY (sent as X-Demo-Key)."""
    if not settings.demo_mode:
        raise HTTPException(status_code=403, detail="Demo controls are off (DEMO_MODE=false)")
    if settings.demo_panel_key and x_demo_key != settings.demo_panel_key.get_secret_value():
        raise HTTPException(status_code=401, detail="Demo panel key required")


CtxDep = Annotated[Ctx, Depends(get_ctx)]
