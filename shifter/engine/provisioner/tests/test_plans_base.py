"""Tests for shared setup-plan primitives."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_dynamic_plan_exposes_runtime_steps_without_context() -> None:
    from plans.base import DynamicPlan, SetupStep

    steps = [SetupStep(name="configure", script="echo configure", timeout_seconds=30)]

    plan = DynamicPlan(name="runtime-plan", steps=steps)

    assert plan.name == "runtime-plan"
    assert plan.steps == steps
    assert plan.verify_step is None
    assert plan.get_context(object()) == {}
