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
from typing import Any

from config import resolve_cloud_provider
from executors.factory import build_guest_execution_context
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

logger = logging.getLogger(__name__)


def _run_polaris_range_bootstrap(
    instance_data: dict[str, Any],
    instance_id: str,
    dc_ip: str,
    public_key: str,
    *,
    range_id: int = 0,
    provider: str | None = None,
    agent_role_arn: str = "",
) -> None:
    """Run PolarisRangeBootstrapPlan against a polaris range host.

    ``instance_data`` is the provisioner instance output; it selects the guest
    transport (SSM for AWS, direct SSH for GCE). ``provider`` defaults to
    ``CLOUD_PROVIDER`` and picks the S3/Bedrock (AWS) vs GCS/Vertex (GCP) steps.
    ``agent_role_arn`` is the non-secret per-range Polaris Bedrock agent role
    ARN (Terraform output, #1377); only consumed on the AWS path.
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

    resolved_provider = provider or resolve_cloud_provider()
    logger.info(
        "Running polaris range bootstrap on %s provider=%s (dc_ip=%s, key length=%d)",
        instance_id,
        resolved_provider,
        dc_ip,
        len(public_key),
    )

    # GCP delivers the smoketest tarball via a provisioner-minted, short-lived
    # signed URL instead of the range-host SA's ADC (#1644). Mint it before
    # opening the guest channel so a signing/lookup failure fails the setup closed
    # with a sanitized error -- never a fallback to guest credentials or an
    # unsigned URL. The URL itself is a private bootstrap input and is never logged.
    polaris_tests_url = ""
    if resolved_provider == "gcp":
        from agent_assets import get_polaris_tests_presigned_url
        from cloud.exceptions import CloudStorageError

        try:
            polaris_tests_url = get_polaris_tests_presigned_url()
        except (CloudStorageError, ValueError) as exc:
            raise SetupError(
                f"polaris range bootstrap for {instance_id}: could not mint the smoketest tarball download URL"
            ) from exc

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
                self.agent_role_arn = agent_role_arn
                self.polaris_tests_url = polaris_tests_url
                self.vertex_secret_ref = str(instance_data.get("gcp_vertex_secret_ref", ""))

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
