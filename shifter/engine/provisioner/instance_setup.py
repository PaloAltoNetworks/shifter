"""Per-instance setup orchestration for the Shifter Engine provisioner.

Extracted from ``main.py`` (Sonar S104). Owns the dataclasses that
bundle per-instance setup inputs, the runtime/transport helpers that
push the bootstrap / RDP-password / XDR-install / domain-join plans
through ``SetupOrchestrator``, the Polaris range bootstrap path, the
DC setup pipeline, and the parallel run_instance_setup entry point
that the orchestrator container calls after Terraform completes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from components.instance import sanitize_hostname
from executors.factory import GuestExecutionContext, build_guest_execution_context, get_ssh_username
from instance_password_setup import set_local_password_or_raise as _push_local_password_or_raise
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.base import SetupPlan
from plans.bootstrap import BootstrapPlan
from plans.domain_join import DomainJoinPlan
from plans.linux_bootstrap import LinuxBootstrapPlan
from plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from plans.xdr_agent_install import XDRAgentInstallPlan

logger = logging.getLogger(__name__)

_LINUX_VICTIM_OS_TYPES = ("kali", "ubuntu", "amazon-linux")


@dataclass(frozen=True)
class _DomainJoinSpec:
    """Bundle of optional-domain-join parameters for Windows victim setup."""

    join_domain: bool
    dc_ip: str | None
    domain_name: str | None


@dataclass(frozen=True)
class _InstanceSetupSpec:
    """Bundle of per-instance setup inputs that aren't on the execution context."""

    role: str
    os_type: str
    public_key: str
    agent_presigned_url: str
    xdr_required: bool
    instance_name: str
    range_id: int
    domain_join: _DomainJoinSpec
    set_local_password: bool = True
    local_password_target_container: str | None = None


class _InstanceSetupCtx:
    """Plan-context shim carrying per-instance setup parameters."""

    def __init__(
        self,
        hostname: str,
        public_key: str,
        agent_presigned_url: str,
        ssh_user: str,
    ) -> None:
        self.hostname = hostname
        self.public_key = public_key
        self.agent_presigned_url = agent_presigned_url
        self.ssh_user = ssh_user


def _resolve_setup_hostname(instance_name: str, instance_id: str) -> str:
    """Return the hostname to write into the per-instance setup context."""
    sanitized_name = sanitize_hostname(instance_name) if instance_name else ""
    return sanitized_name or f"inst-{instance_id[-8:]}"


def _run_setup_plan(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    plan: SetupPlan,
    context: dict[str, Any],
    document_name: str,
    failure_prefix: str,
) -> None:
    """Execute one plan and raise SetupError on failure."""
    result = orchestrator.orchestrate(execution.target, plan, context, document_name=document_name)
    if not result.success:
        raise SetupError(f"{failure_prefix}: {result.error}")


def _set_local_password_or_raise(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    platform: str,
    failure_prefix: str,
    target_container: str | None = None,
) -> None:
    """Adapt the instance context to the password-transport service."""
    _push_local_password_or_raise(
        orchestrator,
        execution,
        instance_data,
        ssh_user=ctx.ssh_user,
        platform=platform,
        failure_prefix=failure_prefix,
        target_container=target_container,
    )


def _setup_attacker_role(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    *,
    set_local_password: bool = True,
    local_password_target_container: str | None = None,
) -> None:
    """Run the Kali bootstrap plan for an attacker-role instance."""
    plan = LinuxBootstrapPlan()
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        plan.get_context(ctx),
        execution.document_name,
        failure_prefix="Kali setup failed",
    )
    if set_local_password:
        try:
            _set_local_password_or_raise(
                orchestrator,
                execution,
                ctx,
                instance_data,
                platform="linux",
                failure_prefix="Kali RDP password push failed",
                target_container=local_password_target_container,
            )
        except SetupError as exc:
            logger.warning("Kali RDP password push non-fatal skip for %s: %s", execution.target, exc)
    else:
        logger.info("Kali local password push deferred for %s", execution.target)
    logger.info("Kali setup complete for %s", execution.target)


def _set_attacker_container_password_after_bootstrap(
    instance_data: dict[str, Any],
    instance_id: str,
    *,
    container_name: str,
    ssh_user: str = "kali",
    required: bool = False,
) -> None:
    """Set the per-instance password inside a container-backed Kali endpoint."""
    execution = build_guest_execution_context(instance_data, os_type="kali", role="attacker")
    orchestrator = SetupOrchestrator(executor=execution.executor)
    try:
        logger.info("Waiting for %s connectivity on %s...", execution.transport_name, execution.target)
        execution.wait_for_ready(timeout_seconds=120)
        logger.info("Target %s is ready via %s", execution.target, execution.transport_name)
        setup_name = instance_data.get("hostname", "") or instance_data.get("name", "")
        ctx = _InstanceSetupCtx(
            hostname=_resolve_setup_hostname(setup_name, instance_id),
            public_key=instance_data.get("public_key", ""),
            agent_presigned_url="",
            ssh_user=ssh_user,
        )
        try:
            _set_local_password_or_raise(
                orchestrator,
                execution,
                ctx,
                instance_data,
                platform="linux",
                failure_prefix=f"{container_name} RDP password push failed",
                target_container=container_name,
            )
        except SetupError as exc:
            if required:
                raise
            logger.warning("%s RDP password push non-fatal skip: %s", container_name, exc)
    finally:
        execution.close()


def _install_xdr_or_raise(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    plan_cls: type[SetupPlan],
    agent_presigned_url: str,
    xdr_required: bool,
    failure_prefix: str,
    success_log: str,
) -> None:
    """Install the XDR agent or raise/log according to ``xdr_required``."""
    instance_id = execution.target
    if agent_presigned_url:
        plan = plan_cls()
        ctx_obj = plan.get_context({"agent_presigned_url": agent_presigned_url})
        # GDC range guests sit on an isolated L2 segment with no egress, so the
        # agent installer (fetched from GCS) and the agent's subsequent
        # phone-home to Cortex/PAN-OS are both unreachable. Per #615 the XDR
        # agent is best-effort on the GDC in-range transport: log and continue
        # so the range still provisions end-to-end. Functional XDR-on-GDC is
        # tracked separately (it requires range-network egress). The AWS SSM
        # path stays strict and raises. The orchestrator both raises SetupError
        # on step retry-exhaustion AND can return result.success=False, so both
        # paths must honour the GDC deferral.
        is_gdc = execution.transport_name == _GDC_RANGE_TRANSPORT
        try:
            result = orchestrator.orchestrate(execution.target, plan, ctx_obj, document_name=execution.document_name)
        except SetupError as exc:
            if is_gdc:
                logger.warning(
                    "XDR agent install raised on %s over %s; deferring XDR on "
                    "GDC (range has no egress) and continuing: %s",
                    instance_id,
                    execution.transport_name,
                    exc,
                )
                return
            raise
        if result.success:
            logger.info(success_log, instance_id)
            return
        if is_gdc:
            logger.warning(
                "XDR agent install did not complete on %s over %s; deferring XDR on "
                "GDC (range has no egress) and continuing: %s",
                instance_id,
                execution.transport_name,
                result.error,
            )
            return
        raise SetupError(f"{failure_prefix}: {result.error}")
    if xdr_required:
        raise SetupError(f"XDR agent required but no URL provided for {instance_id}")
    logger.info("No XDR agent URL provided for %s (not required)", instance_id)


def _setup_linux_victim(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    agent_presigned_url: str,
    xdr_required: bool,
) -> None:
    """Run the linux victim path: bootstrap, per-instance RDP password, optional XDR install."""
    instance_id = execution.target
    plan = LinuxBootstrapPlan()
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        plan.get_context(ctx),
        execution.document_name,
        failure_prefix="Linux bootstrap failed",
    )
    logger.info("Linux bootstrap complete for %s", instance_id)
    _set_local_password_or_raise(
        orchestrator,
        execution,
        ctx,
        instance_data,
        platform="linux",
        failure_prefix="Linux RDP password push failed",
    )
    _install_xdr_or_raise(
        orchestrator,
        execution,
        LinuxXDRAgentInstallPlan,
        agent_presigned_url,
        xdr_required,
        failure_prefix="Linux XDR install failed",
        success_log="Linux XDR agent installed on %s",
    )


def _join_windows_domain(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    dj: _DomainJoinSpec,
) -> None:
    """Join the Windows victim to its domain, or raise per the explicit policy."""
    if not dj.join_domain:
        return
    instance_id = execution.target
    if not (dj.dc_ip and dj.domain_name):
        raise SetupError(f"Domain join required but dc_ip or domain_name not provided for {instance_id}")
    domain_password = os.environ.get("DC_DOMAIN_PASSWORD", "")
    if not domain_password:
        raise SetupError(f"Domain join required but DC_DOMAIN_PASSWORD not set for {instance_id}")
    logger.info("Joining domain %s for %s...", dj.domain_name, instance_id)
    plan = DomainJoinPlan()
    dj_context = plan.get_context(
        {
            "dc_ip": dj.dc_ip,
            "domain_name": dj.domain_name,
            "domain_admin_password": domain_password,
        }
    )
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        dj_context,
        execution.document_name,
        failure_prefix=f"Domain join failed for {instance_id}",
    )
    logger.info("Domain join complete for %s", instance_id)


def _setup_windows_victim(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    agent_presigned_url: str,
    xdr_required: bool,
    dj: _DomainJoinSpec,
) -> None:
    """Run the windows victim path: bootstrap, per-instance Admin password, XDR install, optional domain join."""
    instance_id = execution.target
    plan = BootstrapPlan()
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        plan.get_context(ctx),
        execution.document_name,
        failure_prefix="Windows bootstrap failed",
    )
    logger.info("Windows bootstrap complete for %s", instance_id)
    # Override the bootstrap-default Administrator username for the
    # local-Administrator password push.
    pw_ctx = _InstanceSetupCtx(
        hostname=ctx.hostname,
        public_key=ctx.public_key,
        agent_presigned_url=ctx.agent_presigned_url,
        ssh_user="Administrator",
    )
    _set_local_password_or_raise(
        orchestrator,
        execution,
        pw_ctx,
        instance_data,
        platform="windows",
        failure_prefix="Windows Administrator password push failed",
    )
    _install_xdr_or_raise(
        orchestrator,
        execution,
        XDRAgentInstallPlan,
        agent_presigned_url,
        xdr_required,
        failure_prefix="Windows XDR install failed",
        success_log="Windows XDR agent installed on %s",
    )
    _join_windows_domain(orchestrator, execution, dj)


def _dispatch_instance_setup_role(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    spec: _InstanceSetupSpec,
) -> None:
    """Route an instance through the correct role/os setup path."""
    if spec.role == "attacker":
        _setup_attacker_role(
            orchestrator,
            execution,
            ctx,
            instance_data,
            set_local_password=spec.set_local_password,
            local_password_target_container=spec.local_password_target_container,
        )
        return
    if spec.role != "victim":
        # Unknown role: leave behavior identical to pre-refactor (no plan runs).
        return
    if spec.os_type in _LINUX_VICTIM_OS_TYPES:
        _setup_linux_victim(
            orchestrator,
            execution,
            ctx,
            instance_data,
            spec.agent_presigned_url,
            spec.xdr_required,
        )
        return
    _setup_windows_victim(
        orchestrator,
        execution,
        ctx,
        instance_data,
        spec.agent_presigned_url,
        spec.xdr_required,
        spec.domain_join,
    )


# GDC ("range-pod-ssh") and GCE ("ssh") in-range guests run a full first-boot
# cloud-init before SSH is ready (the heavy Polaris host does not finish within
# the EC2/SSM-tuned default), so both get a larger budget; SSM stays default.
_GDC_RANGE_TRANSPORT = "range-pod-ssh"
_DEFAULT_SETUP_READY_TIMEOUT_SECONDS = 300
_INRANGE_SSH_SETUP_READY_TIMEOUT_SECONDS = 900
_INRANGE_SSH_TRANSPORTS = frozenset({_GDC_RANGE_TRANSPORT, "ssh"})


def _setup_ready_timeout(transport_name: str) -> int:
    """SSH-ready budget for guest setup, by transport (in-range SSH vs SSM)."""
    if transport_name in _INRANGE_SSH_TRANSPORTS:
        return _INRANGE_SSH_SETUP_READY_TIMEOUT_SECONDS
    return _DEFAULT_SETUP_READY_TIMEOUT_SECONDS


def _run_single_instance_setup(
    instance_data: dict[str, Any],
    instance_id: str,
    spec: _InstanceSetupSpec,
) -> bool:
    """Run setup for a single non-DC instance."""
    logger.info("Starting setup for %s instance %s...", spec.role, instance_id)

    execution = build_guest_execution_context(instance_data, os_type=spec.os_type, role=spec.role)
    orchestrator = SetupOrchestrator(executor=execution.executor)

    logger.info("Waiting for %s connectivity on %s...", execution.transport_name, execution.target)
    execution.wait_for_ready(timeout_seconds=_setup_ready_timeout(execution.transport_name))
    logger.info("Target %s is ready via %s", execution.target, execution.transport_name)

    ctx = _InstanceSetupCtx(
        hostname=_resolve_setup_hostname(spec.instance_name, instance_id),
        public_key=spec.public_key,
        agent_presigned_url=spec.agent_presigned_url,
        ssh_user=get_ssh_username(spec.os_type, spec.role),
    )

    try:
        _dispatch_instance_setup_role(orchestrator, execution, ctx, instance_data, spec)
        return True
    finally:
        execution.close()
