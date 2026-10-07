"""FastAPI application entry point: routers, middleware, startup and shutdown."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from app import __version__
from app.api.connect import router as connect_router
from app.api.demo import router as demo_router
from app.api.live import router as live_router
from app.api.media import router as media_router
from app.api.owners import router as owners_router
from app.api.world import router as world_router
from app.config import get_settings
from app.db.models import Shop
from app.db.session import get_engine, get_sessionmaker
from app.paypal.webhooks import router as paypal_webhooks_router
from app.runtime import get_runtime, start_runtime
from app.scheduler import start_scheduler
from app.telegram_bot.bot import router as telegram_router
from app.telegram_bot.bot import start_bot, stop_bot

logger = logging.getLogger(__name__)


async def _seed_if_empty() -> None:
    from app.seed.seed import seed_world

    async with get_sessionmaker()() as session:
        if await session.scalar(select(func.count()).select_from(Shop)):
            return
        result = await seed_world(session)
        logger.info("Seeded the demo world (week of %s)", result.demo_week_start)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the Swarm Clock and simulator snapshot, then start the bot and scheduler."""
    settings = get_settings()
    for problem in settings.production_problems():
        logger.warning("Configuration: %s", problem)
    try:
        if settings.auto_seed:
            await _seed_if_empty()
        async with get_sessionmaker()() as session:
            await start_runtime(session)
    except Exception as exc:  # the API should still start without a database
        logger.warning("Starting without stored runtime state: %s", exc)
    runtime = get_runtime()
    app.state.telegram = None
    try:
        app.state.telegram = await start_bot(runtime)
    except Exception:
        logger.exception("Telegram bot failed to start; continuing without it")
    scheduler = start_scheduler(runtime)
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    await stop_bot(app.state.telegram)
    if runtime.background is not None and not runtime.background.done():
        runtime.background.cancel()
    await runtime.registry.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    app = FastAPI(
        title="Swarm API",
        version=__version__,
        lifespan=lifespan,
        description="Small shops buy together and pay like a chain. Every hold, capture, "
        "payout, invoice and refund runs through PayPal.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled error on %s %s [%s]", request.method, request.url.path, request_id
            )
            response = JSONResponse(
                {"detail": "Something went wrong on our side.", "request_id": request_id},
                status_code=500,
            )
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path not in ("/api/stream",):
            logger.debug(
                "%s %s %s %.0fms",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
            )
        return response

    for router in (
        paypal_webhooks_router,
        telegram_router,
        live_router,
        world_router,
        owners_router,
        demo_router,
        connect_router,
        media_router,
    ):
        app.include_router(router)

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
