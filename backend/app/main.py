"""FastAPI application entry point: wires routers, middleware and health checks."""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.db.session import get_engine

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title="Swarm API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
