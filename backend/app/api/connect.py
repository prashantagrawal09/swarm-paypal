"""Connect a shop's PayPal (one-time approval that saves the wallet for future holds)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CtxDep
from app.features import connect
from app.paypal.errors import PayPalError

router = APIRouter(prefix="/api/connect", tags=["connect"])


class OrderIn(BaseModel):
    order_id: str


@router.post("/{code}/start")
async def start(code: str, ctx: CtxDep) -> dict[str, Any]:
    try:
        return await connect.start(ctx, code)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=f"PayPal: {exc.message}") from exc


@router.post("/{code}/simulated-approve")
async def simulated_approve(code: str, body: OrderIn, ctx: CtxDep) -> dict[str, str]:
    try:
        await connect.simulated_approve(ctx, code, body.order_id)
    except (LookupError, ValueError, PayPalError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "approved"}


@router.post("/{code}/complete")
async def complete(code: str, body: OrderIn, ctx: CtxDep) -> dict[str, Any]:
    try:
        return await connect.complete(ctx, code, body.order_id)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=f"PayPal: {exc.message}") from exc
