"""Orchestrate bounded ACES Active Directory and SPN realization."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aces_plan import AcesPlan, AcesPlanAccount, AcesPlanDomain, AcesPlanNode
from executors.base import Executor
from executors.factory import GuestExecutionContext, build_guest_execution_context
from gcp_guest_secrets import (
    delete_aces_domain_account_secret,
    delete_aces_domain_authority_secret,
    delete_aces_domain_dsrm_secret,
    ensure_aces_domain_account_password_secret,
    ensure_aces_domain_authority_secret,
    ensure_aces_domain_dsrm_secret,
)
from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.aces_active_directory import (
    AcesDomainAccountPlan,
    AcesDomainControllerPlan,
    AcesDomainControllerVerificationPlan,
    AcesDomainMemberPlan,
    AcesDomainMemberStatePlan,
    AcesDomainOfflineJoinProvisionPlan,
)
from plans.base import SetupPlan


class AcesActiveDirectoryError(RuntimeError):
    """Value-free failure at the ACES directory realization boundary."""


_MACHINE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,14}$")
_OFFLINE_JOIN_BLOB_LIMIT = 1024 * 1024
_OFFLINE_JOIN_EVIDENCE_ERROR = "ACES directory offline join evidence is invalid"


@dataclass(frozen=True)
class AcesDirectorySecretOps:
    """Injectable secret, execution, and orchestration operations for AD realization."""

    ensure_dsrm: Callable[[int, str], tuple[str, str]]
    ensure_authority: Callable[[int, str, str], tuple[str, str]]
    ensure_account: Callable[[int, str, str, str], tuple[str, str]]
    delete_dsrm: Callable[[int, str], None]
    delete_authority: Callable[[int, str], None]
    delete_account: Callable[[int, str, str], None]
    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context
    orchestrator_factory: Callable[[Executor], SetupOrchestrator] = SetupOrchestrator


@dataclass(frozen=True)
class _DirectoryRuntime:
    """Resolved plan views and operations shared by one realization pass."""

    range_id: int
    aces_plan: AcesPlan
    outputs: dict[str, dict[str, Any]]
    accounts: dict[str, AcesPlanAccount]
    nodes: dict[str, AcesPlanNode]
    secret_ops: AcesDirectorySecretOps


@dataclass(frozen=True)
class _ControllerSession:
    """Post-promotion controller channel and its required private address."""

    execution: GuestExecutionContext
    private_ip: str


def default_directory_secret_ops() -> AcesDirectorySecretOps:
    """Return production Secret Manager and guest-execution bindings."""
    return AcesDirectorySecretOps(
        ensure_dsrm=ensure_aces_domain_dsrm_secret,
        ensure_authority=ensure_aces_domain_authority_secret,
        ensure_account=ensure_aces_domain_account_password_secret,
        delete_dsrm=delete_aces_domain_dsrm_secret,
        delete_authority=delete_aces_domain_authority_secret,
        delete_account=delete_aces_domain_account_secret,
    )


def _run(execution: GuestExecutionContext, plan: SetupPlan, secret_ops: AcesDirectorySecretOps) -> object:
    """Run one setup plan and convert an unsuccessful result to a bounded error."""
    result = secret_ops.orchestrator_factory(execution.executor).orchestrate(
        execution.target,
        plan,
        plan.get_context({}),
        execution.document_name,
    )
    if not result.success:
        raise AcesActiveDirectoryError("ACES directory setup plan failed")
    return result


def _promotion_was_applied(result: object) -> bool:
    """Return whether promotion mutated the guest after validating fixed evidence."""
    output = "\n".join(str(getattr(step, "stdout", "")) for step in getattr(result, "step_results", ()))
    applied = "ACES_AD_PROMOTION_APPLIED" in output
    verified = "ACES_AD_PROMOTION_VERIFIED" in output
    if applied == verified:
        raise AcesActiveDirectoryError("ACES directory promotion evidence is invalid")
    return applied


def _member_join_state(result: object) -> tuple[str, bool]:
    """Return the bounded local machine name and whether it is already joined."""
    output = "\n".join(str(getattr(step, "stdout", "")) for step in getattr(result, "step_results", ()))
    matches: list[tuple[str, bool]] = []
    for line in output.splitlines():
        if line.startswith("ACES_AD_MEMBER_JOIN_REQUIRED:"):
            matches.append((line.partition(":")[2], False))
        elif line.startswith("ACES_AD_MEMBER_ALREADY_JOINED:"):
            matches.append((line.partition(":")[2], True))
    if len(matches) != 1:
        raise AcesActiveDirectoryError("ACES directory member state evidence is invalid")
    encoded_name, joined = matches[0]
    try:
        machine_name = base64.b64decode(encoded_name, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise AcesActiveDirectoryError("ACES directory member identity is invalid") from None
    if not _MACHINE_NAME.fullmatch(machine_name):
        raise AcesActiveDirectoryError("ACES directory member identity is invalid")
    return machine_name, joined


def _offline_join_blob(execution: GuestExecutionContext, dns_name: str, machine_name: str) -> str:
    """Create an ODJ package without sending its machine credential through setup logs."""
    plan = AcesDomainOfflineJoinProvisionPlan(dns_name=dns_name, machine_name=machine_name)
    step = plan.steps[0]
    result = execution.executor.run_command(
        execution.target,
        step.script,
        timeout_seconds=step.timeout_seconds,
        document_name=execution.document_name,
        stdin_input=step.stdin_input,
    )
    if not result.success:
        raise AcesActiveDirectoryError("ACES directory offline join provisioning failed")
    encoded_blob = result.stdout.strip()
    if not encoded_blob or len(encoded_blob) > _OFFLINE_JOIN_BLOB_LIMIT:
        raise AcesActiveDirectoryError(_OFFLINE_JOIN_EVIDENCE_ERROR)
    try:
        decoded_blob = base64.b64decode(encoded_blob, validate=True)
    except binascii.Error:
        raise AcesActiveDirectoryError(_OFFLINE_JOIN_EVIDENCE_ERROR) from None
    if not decoded_blob:
        raise AcesActiveDirectoryError(_OFFLINE_JOIN_EVIDENCE_ERROR)
    return encoded_blob


def _wait_for_ready(execution: GuestExecutionContext, timeout_seconds: int) -> None:
    """Wait for one guest channel and fail closed on an explicit false result."""
    if execution.wait_for_ready(timeout_seconds=timeout_seconds) is False:
        raise AcesActiveDirectoryError("ACES directory guest did not become ready")


def _authority_output(controller_output: dict[str, Any], authority_username: str) -> dict[str, Any]:
    """Return controller output configured for post-promotion authority login."""
    output = dict(controller_output)
    output["gcp_host_ssh_username"] = authority_username
    output["ssh_username"] = authority_username
    return output


def _output(instance_outputs: dict[str, dict[str, Any]], instance_key: str) -> dict[str, Any]:
    """Return one required instance output or raise a bounded missing-output error."""
    try:
        return instance_outputs[instance_key]
    except KeyError:
        raise AcesActiveDirectoryError("ACES directory instance output is missing") from None


def _build_execution(
    runtime: _DirectoryRuntime,
    output: dict[str, Any],
    authority_username: str | None = None,
) -> GuestExecutionContext:
    """Build a Windows guest channel, optionally as the domain authority."""
    resolved_output = _authority_output(output, authority_username) if authority_username else output
    return runtime.secret_ops.execution_builder(
        resolved_output,
        os_type="windows",
        role="aces-node",
    )


def _initial_controller_execution(
    runtime: _DirectoryRuntime,
    output: dict[str, Any],
    authority_username: str,
) -> GuestExecutionContext:
    """Connect using bootstrap identity, falling back to reconciled authority."""
    execution = _build_execution(runtime, output)
    try:
        _wait_for_ready(execution, 60)
        return execution
    except Exception:
        execution.close()
    execution = _build_execution(runtime, output, authority_username)
    _wait_for_ready(execution, 600)
    return execution


def _controller_session(runtime: _DirectoryRuntime, domain: AcesPlanDomain) -> _ControllerSession:
    """Promote, reconnect to, and verify one admitted domain controller."""
    controller_output = _output(runtime.outputs, f"{domain.controller_addresses[0]}#0")
    authority = runtime.accounts[domain.authority_account_address]
    _dsrm_ref, dsrm_password = runtime.secret_ops.ensure_dsrm(runtime.range_id, domain.domain_id)
    _authority_ref, authority_password = runtime.secret_ops.ensure_authority(
        runtime.range_id,
        domain.domain_id,
        authority.password_strength,
    )
    initial = _initial_controller_execution(runtime, controller_output, authority.username)
    try:
        result = _run(
            initial,
            AcesDomainControllerPlan(
                dns_name=domain.dns_name,
                netbios_name=domain.netbios_name,
                authority_username=authority.username,
                dsrm_password=dsrm_password,
                authority_password=authority_password,
            ),
            runtime.secret_ops,
        )
        promotion_applied = _promotion_was_applied(result)
    finally:
        initial.close()

    execution = _build_execution(runtime, controller_output, authority.username)
    try:
        if promotion_applied:
            execution.executor.reboot_and_wait(
                execution.target,
                timeout_seconds=1200,
                document_name=execution.document_name,
            )
        _wait_for_ready(execution, 600)
        _run(
            execution,
            AcesDomainControllerVerificationPlan(
                dns_name=domain.dns_name,
                netbios_name=domain.netbios_name,
                authority_username=authority.username,
                authority_password=authority_password,
            ),
            runtime.secret_ops,
        )
        private_ip = str(controller_output.get("private_ip", ""))
        if not private_ip:
            raise AcesActiveDirectoryError("ACES directory controller address is missing")
        return _ControllerSession(execution=execution, private_ip=private_ip)
    except Exception:
        execution.close()
        raise


def _realize_member_instance(
    runtime: _DirectoryRuntime,
    domain: AcesPlanDomain,
    session: _ControllerSession,
    instance_key: str,
) -> None:
    """Join one member instance through a machine-scoped offline package."""
    execution = _build_execution(runtime, _output(runtime.outputs, instance_key))
    try:
        _wait_for_ready(execution, 600)
        state_result = _run(
            execution,
            AcesDomainMemberStatePlan(dns_name=domain.dns_name, controller_ip=session.private_ip),
            runtime.secret_ops,
        )
        machine_name, joined = _member_join_state(state_result)
        if not joined:
            blob = _offline_join_blob(session.execution, domain.dns_name, machine_name)
            _run(
                execution,
                AcesDomainMemberPlan(
                    dns_name=domain.dns_name,
                    controller_ip=session.private_ip,
                    offline_join_blob=blob,
                ),
                runtime.secret_ops,
            )
    finally:
        execution.close()


def _realize_members(runtime: _DirectoryRuntime, domain: AcesPlanDomain, session: _ControllerSession) -> None:
    """Realize every counted member instance in one domain."""
    for member_address in domain.member_addresses:
        member = runtime.nodes[member_address]
        for index in range(member.count):
            _realize_member_instance(runtime, domain, session, f"{member_address}#{index}")


def _realize_accounts(runtime: _DirectoryRuntime, domain: AcesPlanDomain, session: _ControllerSession) -> None:
    """Realize every admitted domain account and optional SPN."""
    for account in (item for item in runtime.aces_plan.accounts if item.domain_ref == domain.domain_id):
        _account_ref, password = runtime.secret_ops.ensure_account(
            runtime.range_id,
            domain.domain_id,
            account.address,
            account.password_strength,
        )
        _run(
            session.execution,
            AcesDomainAccountPlan(
                dns_name=domain.dns_name,
                username=account.username,
                password=password,
                spn=account.spn,
            ),
            runtime.secret_ops,
        )


def _realize_domain(runtime: _DirectoryRuntime, domain: AcesPlanDomain) -> None:
    """Realize one controller, its members, and its domain accounts."""
    session = _controller_session(runtime, domain)
    try:
        _realize_members(runtime, domain, session)
        _realize_accounts(runtime, domain, session)
    finally:
        session.execution.close()


def realize_aces_active_directory(
    *,
    range_id: int,
    aces_plan: AcesPlan,
    instance_outputs: list[dict[str, Any]],
    secret_ops: AcesDirectorySecretOps | None = None,
) -> None:
    """Realize every admitted domain before range apply may report success."""
    runtime = _DirectoryRuntime(
        range_id=range_id,
        aces_plan=aces_plan,
        outputs={str(output.get("uuid", "")): output for output in instance_outputs},
        accounts={account.address: account for account in aces_plan.accounts},
        nodes={node.address: node for node in aces_plan.nodes},
        secret_ops=secret_ops or default_directory_secret_ops(),
    )
    try:
        for domain in aces_plan.domains:
            _realize_domain(runtime, domain)
    except AcesActiveDirectoryError:
        raise
    except Exception:
        raise AcesActiveDirectoryError("ACES directory realization failed") from None


def delete_aces_directory_secrets(
    range_id: int,
    aces_plan: AcesPlan,
    secret_ops: AcesDirectorySecretOps | None = None,
) -> None:
    """Delete every deterministic directory secret reconstructible from the plan."""
    resolved_ops = secret_ops or default_directory_secret_ops()
    for domain in aces_plan.domains:
        for account in (item for item in aces_plan.accounts if item.domain_ref == domain.domain_id):
            resolved_ops.delete_account(range_id, domain.domain_id, account.address)
        resolved_ops.delete_authority(range_id, domain.domain_id)
        resolved_ops.delete_dsrm(range_id, domain.domain_id)
