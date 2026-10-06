"""Process-wide services: the Swarm Clock, the PayPal gateway registry and the event sink.

In demo mode the clock is a `SwarmClock` whose position is stored in the database, so the
API, the CLI and the Telegram bot all agree on "now" and the demo panel can move it. The
simulated PayPal's state is snapshotted to the database after every change, so simulated
holds survive a restart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bus import MessageBus
from app.clock import Clock, SwarmClock, SystemClock
from app.config import Settings, get_settings
from app.db.app_state import CLOCK_KEY, SIM_PAYPAL_KEY, get_state, set_state
from app.llm.client import LLM, build_llm
from app.paypal.accounts import GatewayRegistry
from app.paypal.simulated import SimulatedPayPalState

logger = logging.getLogger(__name__)


async def load_clock(session: AsyncSession) -> SwarmClock:
    data = await get_state(session, CLOCK_KEY)
    return SwarmClock.from_dict(data) if data else SwarmClock(datetime.now(UTC))


async def save_clock(session: AsyncSession, clock: SwarmClock) -> None:
    await set_state(session, CLOCK_KEY, clock.to_dict())
    await session.commit()


async def load_sim_state(session: AsyncSession) -> SimulatedPayPalState:
    data = await get_state(session, SIM_PAYPAL_KEY)
    return SimulatedPayPalState.from_dict(data) if data else SimulatedPayPalState()


async def persist_sim_state(state: SimulatedPayPalState) -> None:
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        await set_state(session, SIM_PAYPAL_KEY, state.to_dict())
        await session.commit()


@dataclass
class Runtime:
    settings: Settings
    clock: Clock
    registry: GatewayRegistry
    bus: MessageBus
    llm: LLM

    async def reload_clock(self, session: AsyncSession) -> Clock:
        """Pick up clock moves made by another process (demo panel, CLI)."""
        if isinstance(self.clock, SwarmClock):
            stored = await load_clock(session)
            if stored.now() >= self.clock.now():
                self.clock.set(stored.now())
        return self.clock


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        settings = get_settings()
        clock: Clock = SwarmClock(datetime.now(UTC)) if settings.demo_mode else SystemClock()
        _runtime = Runtime(
            settings=settings,
            clock=clock,
            registry=GatewayRegistry(settings, clock=clock),
            bus=MessageBus(clock),
            llm=build_llm(settings),
        )
    return _runtime


def set_runtime(runtime: Runtime | None) -> None:
    global _runtime
    _runtime = runtime


async def start_runtime(session: AsyncSession, llm: LLM | None = None) -> Runtime:
    """Build the runtime from the database: stored clock position and simulator snapshot."""
    settings = get_settings()
    clock: Clock = await load_clock(session) if settings.demo_mode else SystemClock()
    sim_state = await load_sim_state(session)
    registry = GatewayRegistry(
        settings, clock=clock, sim_state=sim_state, sim_on_change=persist_sim_state
    )
    runtime = Runtime(settings, clock, registry, MessageBus(clock), llm or build_llm(settings))
    set_runtime(runtime)
    return runtime


def get_clock() -> Clock:
    """FastAPI dependency."""
    return get_runtime().clock


def get_bus() -> MessageBus:
    """FastAPI dependency."""
    return get_runtime().bus
