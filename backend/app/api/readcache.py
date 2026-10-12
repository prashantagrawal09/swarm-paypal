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

from app.features.context import Ctx

T = TypeVar("T")
MAX_AGE_SECONDS = 3


async def shared(ctx: Ctx, key: str, compute: Callable[[], Awaitable[T]]) -> T:
    """`compute()`, or the value another request already computed for this exact moment."""
    stamp = (
        ctx.runtime.bus.version,
        int(time.monotonic() // MAX_AGE_SECONDS),
        ctx.now().isoformat(),
    )
    hit = ctx.runtime.read_cache.get(key)
    if hit is not None and hit[0] == stamp:
        cached: T = hit[1]
        return cached
    value = await compute()
    ctx.runtime.read_cache[key] = (stamp, value)
    return value
