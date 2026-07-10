"""Polaris-specific post-bootstrap helper for the Shifter Engine provisioner.

Extracted from ``instance_setup.py`` (Sonar S104). Owns the post-Linux-
bootstrap rewrite of the polaris range host's docker compose stack so each
range gets its own DC IP and per-instance kali pubkey instead of the
bake-time defaults.

Provider-neutral: the compose override rewrite, splice-watcher install, and
verification steps are shared. The command transport is resolved through
``build_guest_execution_context`` (AWS SSM vs GCE direct SSH), and the
provider-specific steps (S3-vs-GCS artifact fetch, Bedrock-vs-Vertex agent
credential shard) are selected by ``PolarisRangeBootstrapPlan``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from executors.factory import build_guest_execution_context
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

logger = logging.getLogger(__name__)


def _set_aws_imds_hop_limit(instance_id: str) -> None:
    """Raise the IMDSv2 hop limit so the a14-kali container can reach IMDS (AWS only).

    The container is one extra hop from the EC2 host's network namespace
    through the docker bridge; the default hop limit of 1 blocks it from
    reaching IMDS at 169.254.169.254 and picking up the instance role. GCP
    has no equivalent (the Vertex shard uses the metadata server directly), so
    this runs only on the AWS path. Idempotent.
    """
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


def _run_polaris_range_bootstrap(
    instance_data: dict[str, Any],
    instance_id: str,
    dc_ip: str,
    public_key: str,
    *,
    range_id: int = 0,
    provider: str | None = None,
) -> None:
    """Run PolarisRangeBootstrapPlan against a polaris range host.

    ``instance_data`` is the provisioner instance output; it selects the guest
    transport (SSM for AWS, direct SSH for GCE). ``provider`` defaults to
    ``CLOUD_PROVIDER`` and picks the S3/Bedrock (AWS) vs GCS/Vertex (GCP) steps.
    """
    if not dc_ip:
        raise SetupError(
            f"polaris range bootstrap for {instance_id}: dc_ip is empty "
            "(scenario must include a role=dc instance so the DC's "
            "private IP can be discovered)"
        )
    if not public_key:
        raise SetupError(
            f"polaris range bootstrap for {instance_id}: public_key is empty "
            "(per-instance ssh public key was not propagated to instance output)"
        )

    resolved_provider = provider or os.environ.get("CLOUD_PROVIDER", "aws")
    logger.info(
        "Running polaris range bootstrap on %s provider=%s (dc_ip=%s, key length=%d)",
        instance_id,
        resolved_provider,
        dc_ip,
        len(public_key),
    )

    if resolved_provider != "gcp":
        _set_aws_imds_hop_limit(instance_id)

    execution = build_guest_execution_context(
        instance_data,
        os_type=str(instance_data.get("os", "ubuntu")),
        role=str(instance_data.get("role", "attacker")),
    )
    try:
        orchestrator = SetupOrchestrator(executor=execution.executor)
        plan = PolarisRangeBootstrapPlan(provider=resolved_provider)

        class _PolarisCtx:
            """Local context shim for PolarisRangeBootstrapPlan template variables."""

            def __init__(self) -> None:
                self.dc_ip = dc_ip
                self.public_key = public_key
                self.range_id = range_id

        context = plan.get_context(_PolarisCtx())
        result = orchestrator.orchestrate(
            execution.target,
            plan,
            context,
            document_name=execution.document_name,
        )
    finally:
        execution.close()
    if not result.success:
        raise SetupError(f"polaris range bootstrap failed on {instance_id}: {result.error}")
    logger.info("polaris range bootstrap complete for %s", instance_id)
