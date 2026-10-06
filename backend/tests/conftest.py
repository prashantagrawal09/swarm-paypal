"""Shared pytest fixtures: API client, the Postgres test database, the seeded world."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import httpx
import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.clock import SwarmClock, at_local
from app.config import Settings, get_settings
from app.db.models import Base
from app.events import RecordingEventSink
from app.main import create_app
from app.money.engine import MoneyEngine
from app.paypal.accounts import GatewayRegistry
from app.paypal.simulated import SimulatedPayPalState

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEMO_WEEK = date(2026, 10, 12)


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client wired straight into the FastAPI app (no network)."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = get_settings().test_database_url
    try:
        psycopg.connect(url.replace("+psycopg", ""), connect_timeout=2).close()
    except psycopg.OperationalError:
        pytest.skip("Postgres test database is not reachable (run: make db-up)")
    env = {**os.environ, "ALEMBIC_DATABASE_URL": url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
    )
    return url


@pytest.fixture
async def db(test_database_url: str) -> AsyncIterator[AsyncSession]:
    """A session on a freshly emptied test database."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------------------
# The seeded world
# ---------------------------------------------------------------------------------------


@pytest.fixture
def clock() -> SwarmClock:
    return SwarmClock(at_local(DEMO_WEEK, 8))


@pytest.fixture
async def world(db: AsyncSession):
    from app.seed.seed import seed_world

    return await seed_world(db, settings=Settings(), demo_week_start=DEMO_WEEK, simulate_all=True)


@pytest.fixture
def events() -> RecordingEventSink:
    return RecordingEventSink()


@pytest.fixture
def registry(clock: SwarmClock) -> GatewayRegistry:
    return GatewayRegistry(Settings(), clock=clock, sim_state=SimulatedPayPalState())


@pytest.fixture
def engine(db, registry, clock, events) -> MoneyEngine:
    return MoneyEngine(db, registry, clock, events)
