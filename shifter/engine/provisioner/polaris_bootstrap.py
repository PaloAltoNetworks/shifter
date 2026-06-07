"""Polaris-specific post-bootstrap helper for the Shifter Engine provisioner.

Extracted from ``instance_setup.py`` (Sonar S104). Owns the post-Linux-
bootstrap rewrite of the polaris-vm AMI's docker compose stack so each
range gets its own DC IP and per-instance kali pubkey instead of the
bake-time defaults.
"""

from __future__ import annotations

import logging
import os

from executors.ssm_executor import SSMExecutor
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

logger = logging.getLogger(__name__)


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
