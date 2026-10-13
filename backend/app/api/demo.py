"""Demo control panel API."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CtxDep, require_demo_key
from app.db.models import Payment
from app.demo import controls
from app.features import claims

router = APIRouter(prefix="/api/demo", tags=["demo"])
Guard = Annotated[None, Depends(require_demo_key)]


class InjectIn(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    now: bool = False


class ClaimDecisionIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)


@router.get("/state")
async def state(ctx: CtxDep) -> dict[str, Any]:
    return await controls.state(ctx)


@router.post("/advance")
async def advance(ctx: CtxDep, _: Guard, paced: bool = False) -> dict[str, Any]:
    """Run the next step. With `paced=true` it runs in the background at a watchable pace
    (like "run week") and this returns straight away."""
    if ctx.runtime.demo_lock.locked():
        raise HTTPException(status_code=409, detail="The week is already running")
    if paced:
        if not controls.start_run_step(ctx.runtime):
            raise HTTPException(status_code=409, detail="The week is already running")
        return {"status": "started"}
    async with ctx.runtime.demo_lock:
        return await controls.advance(ctx)


@router.post("/run-week")
async def run_week(ctx: CtxDep, _: Guard) -> dict[str, Any]:
    started = controls.start_run_week(ctx.runtime)
    if not started:
        raise HTTPException(status_code=409, detail="The week is already running")
    return {"status": "started"}


@router.post("/inject")
async def inject(body: InjectIn, ctx: CtxDep, _: Guard) -> dict[str, Any]:
    if body.kind not in controls.INJECTIONS:
        raise HTTPException(status_code=422, detail=f"Unknown injection {body.kind}")
    async with ctx.runtime.demo_lock:
        return await controls.inject(ctx, body.kind, body.params, body.now)


@router.post("/reset")
async def reset(ctx: CtxDep, _: Guard) -> dict[str, Any]:
    if ctx.runtime.demo_lock.locked():
        raise HTTPException(status_code=409, detail="Wait for the week to finish first")
    async with ctx.runtime.demo_lock:
        return await controls.reset(ctx)


@router.post("/claims/{claim_id}/decide")
async def decide_claim(
    claim_id: uuid.UUID, body: ClaimDecisionIn, ctx: CtxDep, _: Guard
) -> dict[str, Any]:
    claim = await claims.operator_decision(ctx, claim_id, body.approve, body.note)
    refund = (
        await ctx.session.get(Payment, claim.refund_payment_id) if claim.refund_payment_id else None
    )
    return {
        "id": str(claim.id),
        "decision": claim.decision.value,
        "refund": (
            {
                "amount_cents": refund.amount_cents,
                "paypal_id": refund.paypal_id,
                "mode": refund.paypal_mode.value,
            }
            if refund
            else None
        ),
    }
