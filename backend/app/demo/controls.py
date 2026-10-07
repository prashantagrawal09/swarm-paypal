"""Demo control panel actions: move the Swarm Clock through the week, inject the week's
surprises, run the whole week, reset.

Every action runs under the runtime's demo lock, so two people pressing buttons at once
can't interleave steps. "Run full week" runs in the background with a short pause after
each agent message, so the live board can be followed in real time.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.clock import SwarmClock, at_local, local_time, week_day, week_start
from app.db.app_state import set_state
from app.db.models import AuditLog, Shop, Supplier
from app.db.session import get_sessionmaker
from app.features import emergency_borrow, surplus_swap
from app.features.context import Ctx
from app.features.week import DEFAULT_SCENARIO, STEPS, WeekRunner, save_scenario, scenario
from app.llm.client import AnthropicLLM
from app.runtime import Runtime

logger = logging.getLogger(__name__)

RUN_WEEK_PACE_SECONDS = 0.45
INJECTIONS = {"short_delivery", "wrong_price_invoice", "surplus", "emergency", "flash_deal"}


async def log(ctx: Ctx, action: str, details: dict[str, Any]) -> None:
    ctx.session.add(AuditLog(actor="demo", action=action, details=details, created_at=ctx.now()))
    await ctx.session.commit()
    await ctx.bus.emit("demo_action", {"action": action, **details})


def runner_for(ctx: Ctx) -> WeekRunner:
    return WeekRunner(ctx, week_start(ctx.now()))


async def state(ctx: Ctx) -> dict[str, Any]:
    runner = runner_for(ctx)
    done = (await runner.state())["done"]
    upcoming = await runner.next_step()
    now = ctx.now()
    day, phase = week_day(now)
    shops = await ctx.session.execute(
        select(Shop.paypal_mode, func.count()).group_by(Shop.paypal_mode)
    )
    suppliers = await ctx.session.execute(
        select(Supplier.paypal_mode, func.count()).group_by(Supplier.paypal_mode)
    )
    recent = await ctx.session.scalars(
        select(AuditLog)
        .where(AuditLog.actor.in_(["demo", "swarm:week"]))
        .order_by(AuditLog.seq.desc())
        .limit(15)
    )
    settings = ctx.runtime.settings
    llm = ctx.runtime.llm
    return {
        "now": now.isoformat(),
        "local": local_time(now).strftime("%a %d %b, %H:%M"),
        "day": day,
        "phase": phase,
        "week": str(runner.week),
        "steps": [
            {
                "key": step.key,
                "title": step.title,
                "description": step.description,
                "at": runner.time_of(step).isoformat(),
                "status": "done"
                if step.key in done
                else "next"
                if upcoming and step.key == upcoming.key
                else "pending",
            }
            for step in STEPS
        ],
        "running": ctx.runtime.background is not None and not ctx.runtime.background.done(),
        "scenario": await scenario(ctx),
        "modes": {
            "shops": {mode.value: count for mode, count in shops.all()},
            "suppliers": {mode.value: count for mode, count in suppliers.all()},
        },
        "llm": {
            "provider": llm.provider,
            "model": llm.model if isinstance(llm, AnthropicLLM) else None,
        },
        "paypal_env": settings.paypal_env,
        "telegram": bool(settings.telegram_bot_token),
        "demo_mode": settings.demo_mode,
        "log": [
            {
                "action": row.action,
                "actor": row.actor,
                "at": row.created_at.isoformat(),
                "details": row.details,
            }
            for row in recent
        ],
    }


async def advance(ctx: Ctx) -> dict[str, Any]:
    """Run the next step of the week (or roll over to next Monday)."""
    runner = runner_for(ctx)
    step = await runner.next_step()
    if step is None:
        clock = ctx.clock
        if isinstance(clock, SwarmClock):
            clock.set(at_local(runner.week + timedelta(days=7), 8))
            await set_state(ctx.session, "swarm_clock", clock.to_dict())
            await ctx.session.commit()
        runner = runner_for(ctx)
    step, result = await runner.run_next()
    await log(ctx, "advance", {"step": step.key if step else None})
    return {"step": step.key if step else None, "result": result}


async def run_rest_of_week(runtime: Runtime) -> None:
    """Background task: every remaining step, paced for viewers."""
    runtime.bus.pace_seconds = RUN_WEEK_PACE_SECONDS
    try:
        async with runtime.demo_lock:
            while True:
                async with get_sessionmaker()() as session:
                    ctx = Ctx(session, runtime)
                    runner = runner_for(ctx)
                    if await runner.next_step() is None:
                        await log(ctx, "week_complete", {"week": str(runner.week)})
                        break
                    step, _ = await runner.run_next()
                    await log(ctx, "advance", {"step": step.key if step else None, "auto": True})
                await asyncio.sleep(RUN_WEEK_PACE_SECONDS * 3)
    except Exception:
        logger.exception("Run-week failed")
        raise
    finally:
        runtime.bus.pace_seconds = 0.0


def start_run_week(runtime: Runtime) -> bool:
    if runtime.background is not None and not runtime.background.done():
        return False
    runtime.background = asyncio.create_task(run_rest_of_week(runtime))
    return True


async def inject(ctx: Ctx, kind: str, params: dict[str, Any], now: bool = False) -> dict[str, Any]:
    if kind not in INJECTIONS:
        raise ValueError(f"Unknown injection {kind}")
    current = await scenario(ctx)
    merged = {**DEFAULT_SCENARIO.get(kind, {}), **(current.get(kind) or {}), **params}
    current[kind] = merged
    await save_scenario(ctx, current)
    result: dict[str, Any] = {"scenario": merged}
    if now and kind == "surplus":
        expires = local_time(ctx.now()).date() + timedelta(days=int(merged.get("days_left", 2)))
        swap = await surplus_swap.offer(
            ctx, merged["shop"], merged["product"], int(merged["qty"]), expires
        )
        result["swap"] = {"id": str(swap.id), "status": swap.status.value}
    if now and kind == "emergency":
        swap = await emergency_borrow.request(
            ctx, merged["shop"], merged["product"], int(merged["qty"])
        )
        result["swap"] = {
            "id": str(swap.id),
            "status": swap.status.value,
            "seconds_to_sorted": swap.details.get("seconds_to_sorted"),
        }
    await log(ctx, f"inject:{kind}", {"params": merged, "now": now})
    return result


async def reset(ctx: Ctx) -> dict[str, Any]:
    """Wipe and reseed the demo world; the clock goes back to the demo week's Monday."""
    from app.seed.seed import reset_database, seed_world

    await reset_database(ctx.session)
    result = await seed_world(ctx.session)
    ctx.runtime.reset_simulator()
    clock = ctx.clock
    if isinstance(clock, SwarmClock):
        clock.set(at_local(result.demo_week_start, 8))
        await set_state(ctx.session, "swarm_clock", clock.to_dict())
    await save_scenario(ctx, dict(DEFAULT_SCENARIO))
    await ctx.bus.emit("reset", {"week": str(result.demo_week_start)})
    await log(ctx, "reset", {"week": str(result.demo_week_start), "real_shops": result.real_shops})
    return {
        "week": str(result.demo_week_start),
        "real_shops": result.real_shops,
        "real_suppliers": result.real_suppliers,
    }
