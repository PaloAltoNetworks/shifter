"""TechVault-specific post-bootstrap helper for the Shifter Engine provisioner.

Runs ``TechVaultRangeBootstrapPlan`` against the TechVault range host after
``LinuxBootstrapPlan``. The TechVault golden AMI auto-starts its docker
compose stack on boot, so this only writes the AWS Bedrock credential shard
for Claude Code on the host seat. Mirrors ``polaris_bootstrap.py`` but is
smaller: the Claude seat is the EC2 host (not a container), so there is no
IMDS hop-limit bump and no container credential copy.
"""

from __future__ import annotations

import logging
from typing import Any

from executors.factory import build_guest_execution_context
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.techvault_range_bootstrap import TechVaultRangeBootstrapPlan

logger = logging.getLogger(__name__)


def _run_techvault_range_bootstrap(
    instance_data: dict[str, Any],
    instance_id: str,
    *,
    range_id: int = 0,
) -> None:
    """Run TechVaultRangeBootstrapPlan against a TechVault range host.

    ``instance_data`` is the provisioner instance output; it selects the
    guest transport (SSM for AWS, direct SSH for GCE). AWS Bedrock only.
    """
    logger.info("Running techvault range bootstrap on %s (range_id=%s)", instance_id, range_id)

    execution = build_guest_execution_context(
        instance_data,
        os_type=str(instance_data.get("os", "kali")),
        role=str(instance_data.get("role", "attacker")),
    )
    try:
        orchestrator = SetupOrchestrator(executor=execution.executor)
        plan = TechVaultRangeBootstrapPlan()

        class _TechVaultCtx:
            """Local context shim for TechVaultRangeBootstrapPlan template variables."""

            def __init__(self) -> None:
                self.range_id = range_id

        context = plan.get_context(_TechVaultCtx())
        result = orchestrator.orchestrate(
            execution.target,
            plan,
            context,
            document_name=execution.document_name,
        )
    finally:
        execution.close()
    if not result.success:
        raise SetupError(f"techvault range bootstrap failed on {instance_id}: {result.error}")
    logger.info("techvault range bootstrap complete for %s", instance_id)
