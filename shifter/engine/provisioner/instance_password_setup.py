"""Secret-safe local guest password setup across cloud transports.

AWS bootstraps guests over SSM, then switches the secret-bearing password step
to host-key-pinned SSH.  GCP guests already use SSH, so they keep their existing
execution context.  This module owns that transport switch and keeps
``instance_setup`` focused on role orchestration.
"""

from __future__ import annotations

from typing import Any

from executors.base import ExecutorError
from executors.factory import GuestExecutionContext
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.set_local_password import SetLocalPasswordPlan
from state_helpers import _get_cloud_provider

_WINDOWS_SSH_HOST_KEY_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$key = Get-Content "C:\ProgramData\ssh\ssh_host_ed25519_key.pub" -Raw
Write-Output ("SHIFTER_SSH_HOST_KEY=" + $key.Trim())
"""
_LINUX_SSH_HOST_KEY_SCRIPT = "cat /etc/ssh/ssh_host_ed25519_key.pub | sed 's/^/SHIFTER_SSH_HOST_KEY=/'"
_SSH_HOST_KEY_MARKER = "SHIFTER_SSH_HOST_KEY="


def _resolve_rdp_password_from_secret_ref(rdp_password_secret_arn: str | None) -> str | None:
    """Fetch an RDP password from the active provider's secret store."""
    if not rdp_password_secret_arn:
        return None
    from cloud import get_secrets_store

    return get_secrets_store().get_secret(rdp_password_secret_arn)


def _read_aws_ssh_host_key_or_raise(
    execution: GuestExecutionContext,
    *,
    platform: str,
    failure_prefix: str,
) -> str:
    """Read the guest SSH host key over the trusted SSM side channel."""
    script = _WINDOWS_SSH_HOST_KEY_SCRIPT if platform == "windows" else _LINUX_SSH_HOST_KEY_SCRIPT
    try:
        result = execution.executor.run_command(
            execution.target,
            script,
            timeout_seconds=60,
            document_name=execution.document_name,
        )
    except ExecutorError as exc:
        raise SetupError(f"{failure_prefix}: could not read the SSH host key over SSM") from exc

    for line in result.stdout.splitlines():
        if not line.startswith(_SSH_HOST_KEY_MARKER):
            continue
        fields = line.removeprefix(_SSH_HOST_KEY_MARKER).strip().split()
        if len(fields) >= 2 and fields[0] == "ssh-ed25519":
            return " ".join(fields[:2])
    raise SetupError(f"{failure_prefix}: guest did not return a valid ed25519 SSH host key")


def _build_aws_password_execution_or_raise(
    execution: GuestExecutionContext,
    instance_data: dict[str, Any],
    *,
    ssh_user: str,
    platform: str,
    failure_prefix: str,
) -> GuestExecutionContext:
    """Build a host-key-pinned SSH context for the secret-bearing step."""
    private_ip = str(instance_data.get("private_ip") or "")
    ssh_key_ref = str(instance_data.get("ssh_key_secret_arn") or "")
    if not private_ip or not ssh_key_ref:
        raise SetupError(f"{failure_prefix}: instance {execution.target} is missing private_ip or ssh_key_secret_arn")

    host_public_key = _read_aws_ssh_host_key_or_raise(
        execution,
        platform=platform,
        failure_prefix=failure_prefix,
    )
    from cloud import get_secrets_store
    from executors.guest_ssh_executor import GuestSSHExecutor

    ssh_executor = GuestSSHExecutor(
        private_key=get_secrets_store().get_secret(ssh_key_ref),
        username=ssh_user,
        host_public_key=host_public_key,
        known_hosts_host=private_ip,
    )
    password_execution = GuestExecutionContext(
        executor=ssh_executor,
        target=private_ip,
        document_name=execution.document_name,
        transport_name="pinned-ssh",
    )
    try:
        password_execution.wait_for_ready(timeout_seconds=120)
    except ExecutorError as exc:
        password_execution.close()
        raise SetupError(f"{failure_prefix}: pinned SSH transport did not become ready") from exc
    return password_execution


def _run_password_plan(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    plan: SetLocalPasswordPlan,
    context: dict[str, Any],
    failure_prefix: str,
) -> None:
    """Run the local-password plan and translate orchestration failure."""
    result = orchestrator.orchestrate(
        execution.target,
        plan,
        context,
        document_name=execution.document_name,
    )
    if not result.success:
        raise SetupError(f"{failure_prefix}: {result.error}")


def set_local_password_or_raise(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    instance_data: dict[str, Any],
    *,
    ssh_user: str,
    platform: str,
    failure_prefix: str,
    target_container: str | None = None,
) -> None:
    """Push the per-instance local password without exposing it through SSM."""
    cloud_provider = _get_cloud_provider()
    instance_id = execution.target
    if cloud_provider == "aws":
        secret_ref = instance_data.get("rdp_password_secret_arn")
    else:
        secret_ref = instance_data.get("gcp_bootstrap_rdp_password_secret_ref") or instance_data.get(
            "rdp_password_secret_arn"
        )
    if not secret_ref:
        raise SetupError(
            f"{failure_prefix}: instance {instance_id} has no RDP secret reference in its provisioned state"
        )

    password_execution = execution
    password_orchestrator = orchestrator
    owns_password_execution = False
    if cloud_provider == "aws":
        password_execution = _build_aws_password_execution_or_raise(
            execution,
            instance_data,
            ssh_user=ssh_user,
            platform=platform,
            failure_prefix=failure_prefix,
        )
        password_orchestrator = SetupOrchestrator(executor=password_execution.executor)
        owns_password_execution = True

    try:
        password = _resolve_rdp_password_from_secret_ref(str(secret_ref))
        if not password:
            raise SetupError(f"{failure_prefix}: per-instance RDP password fetch returned empty for {instance_id}")
        plan = SetLocalPasswordPlan(platform=platform, target_container=target_container)
        context = plan.get_context({"rdp_username": ssh_user, "rdp_password": password})
        _run_password_plan(
            password_orchestrator,
            password_execution,
            plan,
            context,
            failure_prefix,
        )
    finally:
        if owns_password_execution:
            password_execution.close()
