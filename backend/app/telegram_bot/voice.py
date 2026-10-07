"""Voice notes (F10, stretch). Uses faster-whisper when it is installed (it is optional and
large); otherwise returns None and the bot asks for text."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


@lru_cache
def _model() -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    return WhisperModel("base", device="cpu", compute_type="int8")


def _transcribe_sync(data: bytes) -> str | None:
    model = _model()
    if model is None:
        return None
    with tempfile.NamedTemporaryFile(suffix=".ogg") as handle:
        handle.write(data)
        handle.flush()
        segments, _ = model.transcribe(handle.name, language="en")
        text = " ".join(segment.text.strip() for segment in segments).strip()
    return text or None


async def transcribe(data: bytes) -> str | None:
    try:
        return await asyncio.to_thread(_transcribe_sync, data)
    except Exception:
        logger.exception("Voice transcription failed")
        return None
