"""Runner orchestration: ramp schedule, weighted route choice, and aggregation.

run_load is tested with an INJECTED fake executor (not a mocked app): this
verifies ramp/concurrency/aggregation/resilience, which are the harness's own
logic. The real executor drives the deployed app and is operator-run.
"""

import asyncio
import random

import pytest

from event_load_harness.config import RunConfig
from event_load_harness.profiles import get_profile
from event_load_harness.results import RouteResult
from event_load_harness.runner import (
    ramp_delays,
    run_load,
    steady_state_deadline,
    weighted_choice,
)


def test_steady_state_deadline_includes_ramp():
    # Every VU must get a full duration of steady state AFTER the ramp window,
    # so the deadline is start + ramp + duration, not start + duration.
    assert steady_state_deadline(100.0, 60.0, 600.0) == 760.0
    assert steady_state_deadline(0.0, 0.0, 30.0) == 30.0


def test_ramp_delays_linear():
    assert ramp_delays(4, 8) == [0.0, 2.0, 4.0, 6.0]


def test_ramp_delays_zero_ramp_is_all_zero():
    assert ramp_delays(3, 0) == [0.0, 0.0, 0.0]


def test_weighted_choice_picks_first_and_last_bucket():
    weights = {"a": 1, "b": 1, "c": 2}
    assert weighted_choice(weights, 0.0) == "a"
    assert weighted_choice(weights, 0.99) == "c"


def test_weighted_choice_single_route():
    assert weighted_choice({"only": 5}, 0.5) == "only"


def _config(**kw):
    data = {
        "target_url": "https://dev.example.com",
        "environment": "dev",
        "profile": "portal-core",
        "concurrency": 3,
        "ramp_seconds": 0,
        "duration_seconds": 0.05,
        "actor_source": "dev-login",
        "metric_source": "client-only",
        "report_path": "out/envelope.md",
        "confirm_host": "dev.example.com",
    }
    data.update(kw)
    return RunConfig.from_dict(data)


async def test_run_load_aggregates_and_only_uses_profile_routes():
    profile = get_profile("portal-core")
    actors = ["a1", "a2", "a3"]
    seen = set()

    async def fake_exec(actor, route_class):
        seen.add(route_class)
        return RouteResult(route_class, "http", ok=True, status_code=200, latency_ms=1.0)

    agg = await run_load(_config(), profile, actors, fake_exec, rng=random.Random(7))
    summary = agg.summary()
    assert summary["totals"]["requests"] > 0
    assert seen.issubset(set(profile.route_weights))


async def test_run_load_turns_executor_errors_into_error_results():
    profile = get_profile("portal-core")

    async def boom(actor, route_class):
        raise RuntimeError("simulated transport failure")

    agg = await run_load(_config(), profile, ["a1"], boom, rng=random.Random(1))
    summary = agg.summary()
    assert summary["totals"]["requests"] > 0
    assert summary["totals"]["errors"] == summary["totals"]["requests"]


async def test_run_load_requires_actors():
    with pytest.raises(ValueError, match="actor"):
        await run_load(_config(), get_profile("portal-core"), [], lambda *_: None)


async def test_run_load_respects_duration_deadline():
    # A near-zero duration should still complete promptly (deadline honored).
    async def fake_exec(actor, route_class):
        return RouteResult(route_class, "http", ok=True, status_code=200, latency_ms=1.0)

    agg = await asyncio.wait_for(
        run_load(_config(duration_seconds=0.05), get_profile("portal-core"), ["a"], fake_exec),
        timeout=5,
    )
    assert agg.summary()["totals"]["requests"] >= 1
