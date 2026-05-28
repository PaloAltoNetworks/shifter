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

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from components.instance import sanitize_hostname
from executors.aws_executor import AWSExecutor
from executors.factory import GuestExecutionContext, get_ssh_username
from executors.ssm_executor import SSMExecutor
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.base import SetupPlan
from plans.domain_join import DomainJoinPlan
from plans.linux_bootstrap import LinuxBootstrapPlan
from plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan
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


def _run_polaris_range_bootstrap(
    instance_id: str,
    dc_ip: str,
    public_key: str,
) -> None:
    """Run PolarisRangeBootstrapPlan against a polaris VM instance."""
    if not dc_ip:
        raise SetupError(
            f"polaris range bootstrap for {instance_id}: dc_ip is empty "
            "(scenario must include a role=dc instance so the DC's "
            "private IP can be discovered)"
        )
    if not public_key:
        raise SetupError(
            f"polaris range bootstrap for {instance_id}: public_key is empty "
            "(per-instance ssh key from tls_private_key.instance was not propagated)"
        )

    logger.info(
        "Running polaris range bootstrap on %s (dc_ip=%s, key length=%d)",
        instance_id,
        dc_ip,
        len(public_key),
    )

    # Set IMDSv2 PutResponseHopLimit to 2 on the polaris-vm so the
    # a14-kali container (one extra hop from the EC2 host's network
    # namespace through the docker bridge) can reach IMDS at
    # 169.254.169.254 and pick up the EC2 instance role's credentials.
    # Default IMDS hop limit is 1. Without this, claude inside the kali
    # container has no AWS creds at runtime.
    # Idempotent: re-running on an already-2 instance is a no-op.
    try:
        import boto3 as _boto3

        _ec2 = _boto3.client("ec2", region_name=os.environ.get("AWS_REGION", "us-east-2"))
        _ec2.modify_instance_metadata_options(
            InstanceId=instance_id,
            HttpPutResponseHopLimit=2,
            HttpTokens="required",
            HttpEndpoint="enabled",
        )
        logger.info("Set IMDSv2 hop limit=2 on %s for kali container reachability", instance_id)
    except Exception as e:
        # Warn rather than fail provisioning — claude inside kali will surface
        # the loss of creds at runtime if this slip propagates that far.
        logger.warning("failed to set IMDS hop limit on %s: %s", instance_id, e)

    executor = SSMExecutor()
    orchestrator = SetupOrchestrator(executor=executor)
    plan = PolarisRangeBootstrapPlan()

    class _PolarisCtx:
        """Local context shim for PolarisRangeBootstrapPlan template variables."""

        def __init__(self) -> None:
            self.dc_ip = dc_ip
            self.public_key = public_key

    context = plan.get_context(_PolarisCtx())
    result = orchestrator.orchestrate(
        instance_id,
        plan,
        context,
        document_name="AWS-RunShellScript",
    )
    if not result.success:
        raise SetupError(f"polaris range bootstrap failed on {instance_id}: {result.error}")
    logger.info("polaris range bootstrap complete for %s", instance_id)


def _build_uuid_to_config(range_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a {instance uuid → instance config} lookup from the range spec."""
    return {
        inst.get("uuid", ""): inst for subnet in range_spec.get("subnets", []) for inst in subnet.get("instances", [])
    }


def _partition_pod_vs_vm(
    instances_output: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split scanned instances into (pod-backed, VM-backed) lists."""
    pods: list[dict[str, Any]] = []
    vms: list[dict[str, Any]] = []
    for inst in instances_output:
        if inst.get("asset_type", "vm_runtime_vm") == "scenario_pod":
            pods.append(inst)
        else:
            vms.append(inst)
    return pods, vms


def _partition_dc_vs_other(
    vm_instances: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split VM-backed instances into (DC, non-DC) lists."""
    dcs: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for inst in vm_instances:
        if inst.get("role") == "dc":
            dcs.append(inst)
        else:
            others.append(inst)
    return dcs, others


def _setup_dc_instances_blocking(
    dc_instances: list[dict[str, Any]],
    uuid_to_config: dict[str, dict[str, Any]],
) -> None:
    """Run DC setup for every DC instance synchronously (domain joins depend on it)."""
    import main

    for dc_inst in dc_instances:
        inst_uuid = dc_inst.get("uuid", "")
        inst_config = uuid_to_config.get(inst_uuid, {})
        dc_config = inst_config.get("dc_config", {})
        agent_url = main.get_agent_presigned_url(inst_config)
        main._run_dc_setup(
            instance_data=dc_inst,
            instance_id=dc_inst["instance_id"],
            dc_config=dc_config,
            agent_presigned_url=agent_url or "",
            public_key=dc_inst.get("public_key", ""),
            xdr_required=bool(inst_config.get("agent")),
        )


def _resolve_dc_ip_and_domain(
    dc_instances: list[dict[str, Any]],
    uuid_to_config: dict[str, dict[str, Any]],
    dc_ip: str | None,
    domain_name: str | None,
) -> tuple[str | None, str | None]:
    """Pick the DC IP + domain to use for downstream domain joins."""
    if not dc_instances or dc_ip:
        return dc_ip, domain_name
    first_dc = dc_instances[0]
    dc_uuid = first_dc.get("uuid", "")
    dc_config = uuid_to_config.get(dc_uuid, {}).get("dc_config", {})
    return first_dc.get("private_ip"), dc_config.get("domain_name")


def _setup_one_other_instance(
    inst: dict[str, Any],
    uuid_to_config: dict[str, dict[str, Any]],
    actual_dc_ip: str | None,
    actual_domain: str | None,
    range_id: int,
) -> tuple[str, bool, str | None]:
    """Run setup for a single non-DC VM. Returns (instance_id, success, error)."""
    import main

    inst_id = inst["instance_id"]
    inst_uuid = inst.get("uuid", "")
    inst_config = uuid_to_config.get(inst_uuid, {})
    spec = _InstanceSetupSpec(
        role=inst.get("role", "victim"),
        os_type=inst.get("os", "ubuntu"),
        public_key=inst.get("public_key", ""),
        agent_presigned_url=main.get_agent_presigned_url(inst_config) or "",
        xdr_required=bool(inst_config.get("agent")),
        instance_name=inst.get("hostname", "") or inst.get("name", ""),
        range_id=range_id,
        domain_join=_DomainJoinSpec(
            join_domain=inst_config.get("join_domain", False),
            dc_ip=actual_dc_ip,
            domain_name=actual_domain,
        ),
    )
    try:
        main._run_single_instance_setup(instance_data=inst, instance_id=inst_id, spec=spec)
        # Per-scenario post-bootstrap: the polaris VM AMI is pre-baked with
        # a docker compose stack hardcoded to range 0's DC IP and the
        # bake-time kali pubkey. After LinuxBootstrapPlan finishes, rewrite
        # the compose override and force-recreate the dns + a14-kali
        # containers with this range's actual DC IP and per-instance pubkey.
        # Gate on ami_key so this only fires for polaris instances.
        if inst_config.get("ami_key") == "polaris-vm":
            _run_polaris_range_bootstrap(
                instance_id=inst_id,
                dc_ip=actual_dc_ip or "",
                public_key=inst.get("public_key", ""),
            )
        return (inst_id, True, None)
    except Exception as e:
        # Catch-all so any single instance's failure becomes a tuple the
        # orchestrator can fail the whole range on, rather than crashing
        # the executor thread.
        return (inst_id, False, str(e))


def _setup_other_instances_parallel(
    other_instances: list[dict[str, Any]],
    uuid_to_config: dict[str, dict[str, Any]],
    actual_dc_ip: str | None,
    actual_domain: str | None,
    range_id: int,
) -> None:
    """Run setup for non-DC VMs in parallel; raise on any failure."""
    if not other_instances:
        return
    logger.info("Running setup for %d non-DC instances in parallel...", len(other_instances))
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(
                _setup_one_other_instance,
                inst,
                uuid_to_config,
                actual_dc_ip,
                actual_domain,
                range_id,
            ): inst
            for inst in other_instances
        }
        for future in as_completed(futures):
            inst_id, success, error = future.result()
            if not success:
                raise SetupError(f"Instance {inst_id} setup failed: {error}")


def run_instance_setup(
    instances_output: list[dict[str, Any]],
    range_spec: dict[str, Any],
    dc_ip: str | None = None,
    domain_name: str | None = None,
    range_id: int = 0,
) -> None:
    """Run setup for all instances after infrastructure is ready.

    Runs DC setup first (blocking), then all other instances in parallel.
    """
    uuid_to_config = _build_uuid_to_config(range_spec)
    pod_instances, vm_instances = _partition_pod_vs_vm(instances_output)
    if pod_instances:
        logger.info("Skipping VM setup for %d pod-backed scenario assets", len(pod_instances))

    dc_instances, other_instances = _partition_dc_vs_other(vm_instances)

    # DC setup MUST complete before any domain joins fire.
    _setup_dc_instances_blocking(dc_instances, uuid_to_config)

    actual_dc_ip, actual_domain = _resolve_dc_ip_and_domain(dc_instances, uuid_to_config, dc_ip, domain_name)

    _setup_other_instances_parallel(other_instances, uuid_to_config, actual_dc_ip, actual_domain, range_id)
    logger.info("All instance setup complete")


# Quiet unused-import warnings on direct ``json`` / ``AWSExecutor`` deps —
# referenced in adjacent modules that still receive the file's symbols
# during the gradual provisioner main split.
_ = (json, AWSExecutor)
