"""Async virtual-user orchestration: ramp, concurrency, duration, aggregation.

The runner is intentionally generic over *how* a route is executed: it takes an
``execute_one(actor, route_class) -> RouteResult`` coroutine. The live executor
(``routes.LiveRouteExecutor``) drives the real app; tests inject a deterministic
fake. Per-route reconnect/close-code logic lives in the executor, so the runner
stays a pure scheduler-and-aggregator.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable

from event_load_harness.profiles import Profile
from event_load_harness.results import RouteResult
from event_load_harness.routes import WS_ROUTES
from event_load_harness.stats import Aggregator

ExecuteOne = Callable[[object, str], Awaitable[RouteResult]]


def ramp_delays(concurrency: int, ramp_seconds: float) -> list[float]:
    """Linear start-delay per virtual user: VU i starts at ``i/concurrency * ramp``."""
    if concurrency <= 0:
        return []
    if ramp_seconds <= 0:
        return [0.0] * concurrency
    return [round(i / concurrency * ramp_seconds, 6) for i in range(concurrency)]


def weighted_choice(weights: dict[str, int], pick: float) -> str:
    """Map ``pick`` in [0, 1) into the cumulative weight distribution of ``weights``."""
    total = sum(weights.values())
    threshold = pick * total
    cumulative = 0
    last = ""
    for route_class, weight in weights.items():
        cumulative += weight
        last = route_class
        if threshold < cumulative:
            return route_class
    return last


def _kind(route_class: str) -> str:
    return "ws" if route_class in WS_ROUTES else "http"


def steady_state_deadline(start: float, ramp_seconds: float, duration_seconds: float) -> float:
    """Deadline that gives every virtual user a full ``duration_seconds`` at target concurrency.

    The deadline must include the ramp window: a VU starting at the end of the
    ramp would otherwise run for almost none of ``duration_seconds``, and the
    report would claim a steady-state duration the run never sustained.
    """
    return start + ramp_seconds + duration_seconds


async def run_load(
    config,
    profile: Profile,
    actors: list,
    execute_one: ExecuteOne,
    *,
    rng: random.Random | None = None,
) -> Aggregator:
    """Drive ``config.concurrency`` virtual users against ``profile`` for ``duration_seconds``.

    Returns an Aggregator of every RouteResult. An exception from ``execute_one``
    is recorded as an error result so one failing route never aborts a VU or the
    run.
    """
    if not actors:
        raise ValueError("run_load needs at least one actor")
    rng = rng or random.Random()
    agg = Aggregator()
    delays = ramp_delays(config.concurrency, config.ramp_seconds)
    weights = profile.route_weights
    deadline = steady_state_deadline(time.monotonic(), config.ramp_seconds, config.duration_seconds)

    async def virtual_user(index: int) -> None:
        actor = actors[index % len(actors)]
        if delays[index]:
            await asyncio.sleep(delays[index])
        while time.monotonic() < deadline:
            route_class = weighted_choice(weights, rng.random())
            try:
                result = await execute_one(actor, route_class)
            except Exception:
                result = RouteResult(
                    route_class,
                    _kind(route_class),
                    ok=False,
                    status_code=None,
                    latency_ms=0.0,
                    error_category="executor_error",
                )
            agg.add(result)

    await asyncio.gather(*(virtual_user(i) for i in range(config.concurrency)))
    return agg
