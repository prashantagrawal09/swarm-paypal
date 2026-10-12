"""A tiny cache for the read models the live board polls.

Several people watching the same demo ask for the same expensive summaries after every
event. The answer only changes when something is published on the bus (or the Swarm Clock
moves), so one computation is shared until then. A short time limit bounds staleness for
the rare change that publishes nothing (a webhook reconciliation, for example).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.clock import SwarmClock
from app.features.context import Ctx

T = TypeVar("T")
MAX_AGE_SECONDS = 3
_monotonic = time.monotonic  # a seam for the tests


async def shared(ctx: Ctx, key: str, compute: Callable[[], Awaitable[T]]) -> T:
    """`compute()`, or the value another request already computed for this exact moment."""
    # The Swarm Clock only moves when told to, so its time is part of "this exact moment";
    # a real clock never stands still and must not be.
    clock = ctx.clock
    stamp = (
        ctx.runtime.bus.version,
        int(_monotonic() // MAX_AGE_SECONDS),
        clock.now().isoformat() if isinstance(clock, SwarmClock) else "",
    )
    hit = ctx.runtime.read_cache.get(key)
    if hit is not None and hit[0] == stamp:
        cached: T = hit[1]
        return cached
    value = await compute()
    ctx.runtime.read_cache[key] = (stamp, value)
    return value
