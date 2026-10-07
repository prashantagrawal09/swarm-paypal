"""The owner's side of the conversation, for the web phone (Telegram uses the same service)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.agents.bus import message_dict
from app.api.deps import CtxDep
from app.db.models import AgentMessage
from app.owners.service import OwnerService

router = APIRouter(prefix="/api/owners", tags=["owners"])

MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ActionIn(BaseModel):
    action_id: str = Field(max_length=64)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


async def _check_shop(ctx: Any, code: str) -> None:
    try:
        await ctx.shop(code)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{code}/inbox")
async def inbox(
    code: str, ctx: CtxDep, after_seq: int = 0, limit: int = 100
) -> list[dict[str, Any]]:
    """The owner's chat: messages to and from `owner:<code>`, oldest first."""
    await _check_shop(ctx, code)
    owner = f"owner:{code}"
    rows = await ctx.session.scalars(
        select(AgentMessage)
        .where(
            or_(AgentMessage.to_agent == owner, AgentMessage.from_agent == owner),
            AgentMessage.seq > after_seq,
        )
        .order_by(AgentMessage.seq.desc())
        .limit(min(limit, 300))
    )
    return [message_dict(m) for m in reversed(list(rows))]


@router.post("/{code}/actions")
async def press(code: str, body: ActionIn, ctx: CtxDep) -> dict[str, str]:
    await _check_shop(ctx, code)
    await OwnerService(ctx).handle_action(code, body.action_id)
    return {"status": "ok"}


@router.post("/{code}/messages")
async def send_text(code: str, body: TextIn, ctx: CtxDep) -> dict[str, str]:
    await _check_shop(ctx, code)
    await OwnerService(ctx).handle_text(code, body.text)
    return {"status": "ok"}


@router.post("/{code}/photo")
async def send_photo(
    code: str,
    ctx: CtxDep,
    photo: Annotated[UploadFile, File()],
    caption: Annotated[str, Form()] = "",
) -> dict[str, str]:
    await _check_shop(ctx, code)
    content_type = photo.content_type or ""
    if content_type not in PHOTO_TYPES:
        raise HTTPException(status_code=415, detail="Send a JPEG, PNG or WebP photo")
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo is larger than 8 MB")
    await OwnerService(ctx).handle_photo(code, data, content_type, caption[:500])
    return {"status": "ok"}
