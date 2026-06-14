"""Domain Controller setup pipeline for the Shifter Engine provisioner.

Extracted from ``instance_setup.py`` (Sonar S104). Owns the DC-side
template-context shims, the bootstrap / SSH-access / verification /
XDR-install helpers, and the ``_run_dc_setup`` entry point that the
parallel orchestrator runs against each Domain Controller in a range.

"""

from __future__ import annotations

import logging
import os
from typing import Any

from components.instance import sanitize_hostname
from executors.base import Executor
from executors.factory import GuestExecutionContext, build_guest_execution_context
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.bootstrap import BootstrapPlan
from plans.dc_setup import DCSetupPlan
from plans.xdr_agent_install import XDRAgentInstallPlan
from state_helpers import _get_cloud_provider, _should_promote_dc_at_runtime, _should_run_dc_bootstrap_plan

logger = logging.getLogger(__name__)


class _DCBootstrapContext:
    """Template-context shim for the DC BootstrapPlan."""

    def __init__(self, hostname: str, public_key: str) -> None:
        self.hostname = hostname
        self.public_key = public_key


class _DCPromoteConfig:
    """Template-context shim for the DC promotion plan."""

    def __init__(self, domain_name: str, netbios_name: str, dsrm_password: str, domain_admin_password: str) -> None:
        self.domain_name = domain_name
        self.netbios_name = netbios_name
        self.dsrm_password = dsrm_password
        self.domain_admin_password = domain_admin_password


def _run_dc_bootstrap_plan(
    *,
    provider: str,
    instance_data: dict[str, Any],
    instance_id: str,
    public_key: str,
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
) -> None:
    """Run BootstrapPlan against a DC instance when the provider requires it."""
    if not _should_run_dc_bootstrap_plan(provider):
        return

    logger.info("Running DC bootstrap plan via %s setup path", provider)
    bootstrap_plan = BootstrapPlan()
    bootstrap_source = instance_data.get("hostname", "") or instance_data.get("name", "")
    bootstrap_hostname = sanitize_hostname(bootstrap_source) or f"dc-{instance_id[-8:]}"
    bootstrap_context = bootstrap_plan.get_context(
        _DCBootstrapContext(hostname=bootstrap_hostname, public_key=public_key)
    )
    bootstrap_result = orchestrator.orchestrate(
        execution.target,
        bootstrap_plan,
        bootstrap_context,
        document_name=execution.document_name,
    )
    if not bootstrap_result.success:
        raise SetupError(f"DC bootstrap failed: {bootstrap_result.error}")
    logger.info("DC bootstrap complete for %s", instance_id)


def _configure_dc_ssh_access(
    *,
    executor: Executor,
    execution: GuestExecutionContext,
    instance_id: str,
    public_key: str,
) -> None:
    """Write the per-instance SSH authorized key onto the DC and restart sshd."""
    if not public_key:
        logger.warning("No public key provided for DC %s, SSH key auth will not work", instance_id)
        return

    logger.info("Configuring SSH key on DC %s...", instance_id)
    ssh_key_script = f'''
$ErrorActionPreference = "Stop"
$publicKey = "{public_key}"

Write-Host "Configuring SSH key for Administrator..."

$sshDir = "C:\\ProgramData\\ssh"
if (!(Test-Path $sshDir)) {{
    New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
}}

$publicKey | Out-File -Encoding ascii "$sshDir\\administrators_authorized_keys"

# Set proper permissions
icacls "$sshDir\\administrators_authorized_keys" /inheritance:r `
    /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null

# Restart sshd to pick up new key
Restart-Service sshd -Force -ErrorAction SilentlyContinue

Write-Host "SSH key configured successfully"
'''
    ssh_result = executor.run_command(
        instance_id=execution.target,
        script=ssh_key_script,
        document_name=execution.document_name,
        timeout_seconds=60,
    )
    if not ssh_result.success:
        logger.warning("SSH key configuration failed: %s (continuing with setup)", ssh_result.stderr)
        return
    logger.info("SSH key configured on DC %s", instance_id)


def _verify_dc_setup(
    *,
    provider: str,
    domain_name: str,
    netbios_name: str,
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
) -> None:
    """Run DCSetupPlan against the DC and raise SetupError on verification failure."""
    logger.info("Verifying Domain Controller (%s)...", domain_name)
    runtime_promotion = _should_promote_dc_at_runtime(provider)
    logger.info(
        "Using %s DC verification path for provider=%s",
        "runtime" if runtime_promotion else "prebaked",
        provider,
    )
    dc_plan = DCSetupPlan(runtime_promotion=runtime_promotion)
    domain_admin_password = os.environ.get("DC_DOMAIN_PASSWORD", "")
    config_obj = _DCPromoteConfig(domain_name, netbios_name, domain_admin_password, domain_admin_password)
    dc_context = dc_plan.get_context(config_obj)
    dc_result = orchestrator.orchestrate(
        execution.target,
        dc_plan,
        dc_context,
        document_name=execution.document_name,
    )
    if not dc_result.success:
        raise SetupError(f"DC verification failed: {dc_result.error}")
    logger.info("DC verification complete")


def _install_dc_xdr(
    *,
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    instance_id: str,
    agent_presigned_url: str,
    xdr_required: bool,
) -> None:
    """Install the XDR agent on the DC, or raise per the `xdr_required` policy."""
    if agent_presigned_url:
        logger.info("Installing XDR agent on DC %s...", instance_id)
        xdr_plan = XDRAgentInstallPlan()
        xdr_context = xdr_plan.get_context({"agent_presigned_url": agent_presigned_url})
        xdr_result = orchestrator.orchestrate(
            execution.target,
            xdr_plan,
            xdr_context,
            document_name=execution.document_name,
        )
        if not xdr_result.success:
            raise SetupError(f"XDR agent install failed on DC: {xdr_result.error}")
        logger.info("XDR agent installed successfully on DC")
        return

    if xdr_required:
        raise SetupError(f"XDR agent required but no URL provided for DC {instance_id}")
    logger.info("No XDR agent URL provided for DC (not required)")


def _run_dc_setup(
    instance_data: dict[str, Any],
    instance_id: str,
    dc_config: dict[str, Any],
    agent_presigned_url: str,
    public_key: str = "",
    xdr_required: bool = False,
) -> bool:
    """Run setup for a DC instance."""
    logger.info("DC instance %s starting setup...", instance_id)
    domain_name = dc_config.get("domain_name", "")
    netbios_name = dc_config.get("netbios_name", "")
    logger.info("Domain: %s, NetBIOS: %s", domain_name, netbios_name)

    provider = _get_cloud_provider()
    execution = build_guest_execution_context(instance_data, os_type="windows", role="dc")
    executor = execution.executor
    orchestrator = SetupOrchestrator(executor=executor)

    # Wait up to 30 min for the DC AMI's sysprep reboot cycles to settle.
    logger.info("Waiting for %s connectivity on DC %s...", execution.transport_name, execution.target)
    execution.wait_for_ready(timeout_seconds=1800)
    logger.info("DC %s ready via %s", instance_id, execution.transport_name)

    try:
        _run_dc_bootstrap_plan(
            provider=provider,
            instance_data=instance_data,
            instance_id=instance_id,
            public_key=public_key,
            orchestrator=orchestrator,
            execution=execution,
        )
        _configure_dc_ssh_access(
            executor=executor,
            execution=execution,
            instance_id=instance_id,
            public_key=public_key,
        )
        _verify_dc_setup(
            provider=provider,
            domain_name=domain_name,
            netbios_name=netbios_name,
            orchestrator=orchestrator,
            execution=execution,
        )
        _install_dc_xdr(
            orchestrator=orchestrator,
            execution=execution,
            instance_id=instance_id,
            agent_presigned_url=agent_presigned_url,
            xdr_required=xdr_required,
        )
        return True
    finally:
        execution.close()
