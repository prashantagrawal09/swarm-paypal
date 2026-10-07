"""Connect a shop's PayPal (one-time approval that saves the wallet for future holds)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CtxDep
from app.features import connect
from app.features.context import Ctx
from app.paypal.errors import PayPalError
from app.security import LinkError, verify

router = APIRouter(prefix="/api/connect", tags=["connect"])


class StartIn(BaseModel):
    token: str | None = Field(default=None, max_length=80)


class OrderIn(StartIn):
    order_id: str = Field(max_length=64)


def _authorize(ctx: Ctx, code: str, token: str | None) -> None:
    """Demo mode lets anyone connect a demo shop; otherwise only the owner's signed link."""
    if ctx.runtime.settings.demo_mode and not token:
        return
    try:
        verify(ctx.runtime.settings, code, token, ctx.now(), "connect")
    except LinkError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{code}/start")
async def start(code: str, ctx: CtxDep, body: StartIn | None = None) -> dict[str, Any]:
    _authorize(ctx, code, body.token if body else None)
    try:
        return await connect.start(ctx, code, body.token if body else None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=f"PayPal: {exc.message}") from exc


@router.post("/{code}/simulated-approve")
async def simulated_approve(code: str, body: OrderIn, ctx: CtxDep) -> dict[str, str]:
    _authorize(ctx, code, body.token)
    try:
        await connect.simulated_approve(ctx, code, body.order_id)
    except (LookupError, ValueError, PayPalError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "approved"}


@router.post("/{code}/complete")
async def complete(code: str, body: OrderIn, ctx: CtxDep) -> dict[str, Any]:
    _authorize(ctx, code, body.token)
    try:
        return await connect.complete(ctx, code, body.order_id)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=f"PayPal: {exc.message}") from exc
