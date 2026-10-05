"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from app.main import create_app


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client wired straight into the FastAPI app (no network)."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
