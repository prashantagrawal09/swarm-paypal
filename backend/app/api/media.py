"""Serve uploaded photos (claims evidence)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CtxDep
from app.db.models import MediaBlob

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{media_id}")
async def media(media_id: uuid.UUID, ctx: CtxDep) -> Response:
    blob = await ctx.session.get(MediaBlob, media_id)
    if blob is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=blob.data,
        media_type=blob.content_type,
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
