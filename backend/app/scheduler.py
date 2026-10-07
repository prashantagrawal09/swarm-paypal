"""Production schedule: run each step of the Swarm week at its Singapore time.

Only used when DEMO_MODE is false (then the clock is the real clock). In demo mode the demo
panel moves the Swarm Clock instead and nothing runs on a timer.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.clock import BUSINESS_TZ, week_start
from app.db.session import get_sessionmaker
from app.features.context import Ctx
from app.features.week import STEPS, WeekRunner
from app.runtime import Runtime

logger = logging.getLogger(__name__)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


async def run_step(runtime: Runtime, key: str) -> None:
    async with runtime.demo_lock, get_sessionmaker()() as session:
        ctx = Ctx(session, runtime)
        try:
            await WeekRunner(ctx, week_start(ctx.now())).run(key)
        except Exception:
            logger.exception("Scheduled step %s failed", key)


def build_scheduler(runtime: Runtime) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=BUSINESS_TZ)
    for step in STEPS:
        scheduler.add_job(
            run_step,
            CronTrigger(
                day_of_week=DAYS[step.day], hour=step.hour, minute=step.minute, timezone=BUSINESS_TZ
            ),
            args=[runtime, step.key],
            id=step.key,
            coalesce=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
    return scheduler


def start_scheduler(runtime: Runtime) -> AsyncIOScheduler | None:
    if runtime.settings.demo_mode:
        return None
    scheduler = build_scheduler(runtime)
    scheduler.start()
    logger.info("Week scheduler started: %s", ", ".join(job.id for job in scheduler.get_jobs()))
    return scheduler
