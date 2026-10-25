"""Fixed participant-host readiness check for RAES GCE and native EC2 realization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from config import BOOTSTRAP_PRECONFIGURED_MACHINE_HOST
from executors.factory import GuestExecutionContext, build_guest_execution_context
from instance_contract import instance_field
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.preconfigured_machine_host import PreconfiguredMachineHostPlan


def verify_preconfigured_hosts(
    instances: list[dict[str, Any]],
    *,
    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context,
) -> None:
    """Gate readiness on the same bounded liveness and fixed participant canary."""
    plan = PreconfiguredMachineHostPlan()
    for instance in instances:
        if instance_field(instance, "bootstrap_capability") != BOOTSTRAP_PRECONFIGURED_MACHINE_HOST:
            continue
        execution = execution_builder(
            instance, os_type=instance.get("os", "kali"), role=instance.get("role", "attacker")
        )
        try:
            if not execution.wait_for_ready(timeout_seconds=300):
                raise SetupError("Preconfigured range host management transport is unavailable")
            context = plan.get_context(instance)
            result = SetupOrchestrator(executor=execution.executor).orchestrate(
                execution.target, plan, context, document_name=execution.document_name
            )
            if not result.success:
                raise SetupError(f"Preconfigured range host failed participant readiness: {result.error}")
        finally:
            execution.close()
