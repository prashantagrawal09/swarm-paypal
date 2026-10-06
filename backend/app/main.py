"""FastAPI application entry point: wires routers, middleware and health checks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.db.session import get_engine, get_sessionmaker
from app.paypal.webhooks import router as paypal_webhooks_router
from app.runtime import get_runtime, start_runtime

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Load the Swarm Clock and simulator snapshot from the database (if it is up)."""
    try:
        async with get_sessionmaker()() as session:
            await start_runtime(session)
    except Exception as exc:  # the API should still start without a database
        logger.warning("Starting without stored runtime state: %s", exc)
    yield
    await get_runtime().registry.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title="Swarm API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(paypal_webhooks_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"name": "Swarm", "message": "Small shops buy together and pay like a chain."}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.app_env,
            "database": await _database_status(),
        }

    return app


async def _database_status() -> str:
    try:
        async with asyncio.timeout(2):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # health must report, never raise
        logger.warning("Database health check failed: %s", exc)
        return "unavailable"


app = create_app()
