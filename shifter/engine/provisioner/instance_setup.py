"""Per-instance setup orchestration for the Shifter Engine provisioner.

Extracted from ``main.py`` (Sonar S104). Owns the dataclasses that
bundle per-instance setup inputs, the runtime/transport helpers that
push the bootstrap / RDP-password / XDR-install / domain-join plans
through ``SetupOrchestrator``, the Polaris range bootstrap path, the
DC setup pipeline, and the parallel run_instance_setup entry point
that the orchestrator container calls after Terraform completes.

Cross-module callees that historically came from ``main.X`` (and are
patched in tests via ``patch("main.X")``) go through lazy
``import main; main.X(...)`` lookups so the existing test mocks keep
intercepting the same call sites without per-test edits.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from components.instance import sanitize_hostname
from executors.factory import GuestExecutionContext, get_ssh_username
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.base import SetupPlan
from plans.domain_join import DomainJoinPlan
from plans.linux_bootstrap import LinuxBootstrapPlan
from plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from plans.set_local_password import SetLocalPasswordPlan
from plans.xdr_agent_install import XDRAgentInstallPlan
from state_helpers import _get_cloud_provider

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


def _resolve_rdp_password_from_secret_ref(rdp_password_secret_arn: str | None) -> str | None:
    """Fetch the per-instance RDP password value from the active cloud secret store.

    Returns ``None`` when no secret reference is recorded (e.g., DC role,
    or older state without the field). Callers that require the value
    must check for ``None`` and either skip the push or raise.
    """
    if not rdp_password_secret_arn:
        return None
    from cloud import get_secrets_store

    secrets = get_secrets_store()
    return secrets.get_secret(rdp_password_secret_arn)


def _set_local_password_or_raise(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    platform: str,
    failure_prefix: str,
) -> None:
    """Push the per-instance local guest password via SSM/SSH (#762)."""
    cloud_provider = _get_cloud_provider()
    instance_id = execution.target
    rdp_token: str
    if cloud_provider == "aws":
        ssm_param_name = instance_data.get("rdp_password_ssm_param_name")
        if not ssm_param_name:
            raise SetupError(
                f"{failure_prefix}: instance {instance_id} has no "
                "rdp_password_ssm_param_name; provisioner did not record an SSM "
                "Parameter Store reference for the per-instance password"
            )
        rdp_token = f"{{{{ssm-secure:{ssm_param_name}}}}}"
    else:
        secret_ref = instance_data.get("rdp_password_secret_arn")
        if not secret_ref:
            raise SetupError(
                f"{failure_prefix}: instance {instance_id} has no rdp_password_secret_arn "
                "in its provisioned state; provisioner did not record a per-instance secret reference"
            )
        fetched = _resolve_rdp_password_from_secret_ref(secret_ref)
        if not fetched:
            raise SetupError(f"{failure_prefix}: per-instance RDP password fetch returned empty for {instance_id}")
        rdp_token = fetched
    plan = SetLocalPasswordPlan(platform=platform)
    context = plan.get_context({"rdp_username": ctx.ssh_user, "rdp_password": rdp_token})
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        context,
        execution.document_name,
        failure_prefix=failure_prefix,
    )
    logger.info("Per-instance RDP password set on %s (%s)", instance_id, platform)


def _setup_attacker_role(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
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
    _set_local_password_or_raise(
        orchestrator,
        execution,
        ctx,
        instance_data,
        platform="linux",
        failure_prefix="Kali RDP password push failed",
    )
    logger.info("Kali setup complete for %s", execution.target)


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
        _run_setup_plan(
            orchestrator,
            execution,
            plan,
            ctx_obj,
            execution.document_name,
            failure_prefix=failure_prefix,
        )
        logger.info(success_log, instance_id)
        return
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
    import main

    instance_id = execution.target
    plan = main.BootstrapPlan()
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
        _setup_attacker_role(orchestrator, execution, ctx, instance_data)
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


def _run_single_instance_setup(
    instance_data: dict[str, Any],
    instance_id: str,
    spec: _InstanceSetupSpec,
) -> bool:
    """Run setup for a single non-DC instance."""
    import main

    logger.info("Starting setup for %s instance %s...", spec.role, instance_id)

    execution = main.build_guest_execution_context(instance_data, os_type=spec.os_type, role=spec.role)
    orchestrator = main.SetupOrchestrator(executor=execution.executor)

    logger.info("Waiting for %s connectivity on %s...", execution.transport_name, execution.target)
    execution.wait_for_ready(timeout_seconds=300)
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
