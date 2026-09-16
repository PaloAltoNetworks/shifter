"""Synchronous guest-state proof for bootstrap-realized RAES composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from executors.base import CommandExecutor
from executors.factory import GuestExecutionContext, build_guest_execution_context
from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.raes_composition_verification import RaesCompositionVerificationPlan
from raes_gcp_composition import RaesGceCompositionError
from raes_plan import RaesPlan, RaesPlanAccount, RaesPlanContent, RaesPlanNode

_GUEST_READY_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class RaesCompositionVerificationOps:
    """Injectable guest execution and orchestration operations."""

    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context
    orchestrator_factory: Callable[[CommandExecutor], SetupOrchestrator] = SetupOrchestrator


def _platform(node: RaesPlanNode) -> str:
    """Return the guest verification platform for one node."""
    return "windows" if (node.os_family or "linux").lower() == "windows" else "linux"


def _bootstrap_content(plan: RaesPlan, node: RaesPlanNode) -> tuple[RaesPlanContent, ...]:
    """Return bootstrap-realized content targeting one node."""
    return tuple(item for item in plan.content if item.target_address == node.address and item.source_name is None)


def _local_accounts(plan: RaesPlan, node: RaesPlanNode) -> tuple[RaesPlanAccount, ...]:
    """Return locally realized accounts targeting one node."""
    return tuple(
        account
        for account in plan.accounts
        if account.target_address == node.address and account.domain_ref is None and account.domain_id is None
    )


def _assert_content_is_verifiable(item: RaesPlanContent) -> None:
    """Reject a bootstrap content item without a complete guest probe."""
    supported_file = item.content_type == "file" and item.text is not None and bool(item.path)
    supported_directory = item.content_type == "directory" and bool(item.destination)
    if item.source_name is None and not (supported_file or supported_directory):
        raise RaesGceCompositionError("RAES composition uses an unsupported content shape")


def _assert_account_is_verifiable(account: RaesPlanAccount, nodes: dict[str, RaesPlanNode]) -> None:
    """Reject an account whose target or platform attributes cannot be probed."""
    node = nodes.get(account.target_address)
    if node is None:
        raise RaesGceCompositionError("RAES composition target is unavailable")
    if _platform(node) == "windows" and (account.login_shell or account.home):
        raise RaesGceCompositionError("RAES Windows account uses unsupported account attributes")


def _assert_node_probe_is_available(plan: RaesPlan, node: RaesPlanNode) -> None:
    """Require a rendered probe whenever a node has bootstrap composition."""
    content = _bootstrap_content(plan, node)
    accounts = _local_accounts(plan, node)
    if not content and not accounts:
        return
    verification_script = RaesCompositionVerificationPlan(
        platform=_platform(node), content=content, accounts=accounts
    ).verify_step.script
    if not verification_script:
        raise RaesGceCompositionError("RAES composition verification script is unavailable")


def assert_composition_is_verifiable(plan: RaesPlan) -> None:
    """Reject composition shapes whose authored semantics cannot be probed."""
    nodes = {node.address: node for node in plan.nodes}
    for item in plan.content:
        _assert_content_is_verifiable(item)
    for account in plan.accounts:
        _assert_account_is_verifiable(account, nodes)
    for node in plan.nodes:
        _assert_node_probe_is_available(plan, node)


def _outputs_by_key(instance_outputs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index unique, non-empty concrete instance outputs by authored key."""
    outputs: dict[str, dict[str, Any]] = {}
    for output in instance_outputs:
        key = output.get("uuid")
        if not isinstance(key, str) or not key or key in outputs:
            raise RaesGceCompositionError("RAES composition instance output coverage is invalid")
        outputs[key] = output
    return outputs


def _verify_instance(
    output: dict[str, Any],
    platform: str,
    plan: RaesCompositionVerificationPlan,
    ops: RaesCompositionVerificationOps,
) -> None:
    """Run one node-level read-only verification plan on one guest."""
    execution = ops.execution_builder(output, os_type=platform, role="raes-node")
    try:
        if execution.wait_for_ready(timeout_seconds=_GUEST_READY_TIMEOUT_SECONDS) is False:
            raise RaesGceCompositionError("RAES composition guest did not become ready")
        result = ops.orchestrator_factory(execution.executor).orchestrate(
            execution.target,
            plan,
            plan.get_context({}),
            execution.document_name,
        )
        verification = result.verification_result
        if verification is None or not verification.success:
            raise RaesGceCompositionError("RAES composition in-guest verification failed")
    finally:
        execution.close()


def verify_bootstrap_composition(
    plan: RaesPlan,
    instance_outputs: list[dict[str, Any]],
    ops: RaesCompositionVerificationOps | None = None,
) -> frozenset[str]:
    """Verify every bootstrap composition item on every target instance."""
    assert_composition_is_verifiable(plan)
    resolved_ops = ops or RaesCompositionVerificationOps()
    outputs = _outputs_by_key(instance_outputs)
    expected_outputs = {f"{node.address}#{index}" for node in plan.nodes for index in range(node.count)}
    if set(outputs) != expected_outputs:
        raise RaesGceCompositionError("RAES composition instance output coverage is invalid")
    verified: set[str] = set()
    try:
        for node in plan.nodes:
            content = _bootstrap_content(plan, node)
            accounts = _local_accounts(plan, node)
            if not content and not accounts:
                continue
            verification_plan = RaesCompositionVerificationPlan(
                platform=_platform(node), content=content, accounts=accounts
            )
            for index in range(node.count):
                output = outputs.get(f"{node.address}#{index}")
                if output is None:
                    raise RaesGceCompositionError("RAES composition instance output is missing")
                _verify_instance(output, _platform(node), verification_plan, resolved_ops)
            verified.update(item.address for item in content)
            verified.update(account.address for account in accounts)
    except RaesGceCompositionError:
        raise
    except Exception:
        raise RaesGceCompositionError("RAES composition in-guest verification failed") from None
    return frozenset(verified)
