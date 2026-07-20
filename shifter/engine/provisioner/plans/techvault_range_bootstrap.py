"""TechVault range per-instance bootstrap plan.

The TechVault golden AMI is baked with the full ``techvault-operational``
docker compose stack in a running state (it auto-starts on boot), plus
Claude Code and the APTL MCP servers on the ``ubuntu`` host seat. Range
launch therefore does NOT reprovision the stack; the standard
``LinuxBootstrapPlan`` + set-local-password path handles the per-range SSH
key and RDP password for ``ubuntu``, and this plan adds the one remaining
per-range agent step: the AWS Bedrock credential shard.

This is the TechVault analog of ``PolarisRangeBootstrapPlan``, but much
smaller: no DC-IP rewrite (TechVault's AD is an in-compose container at a
static address), no container credential copy (the Claude seat is the host),
and no splice watcher. AWS Bedrock only; the GCP/Vertex plane is tracked in
issue #1446.
"""

from __future__ import annotations

import os
from typing import Any

from ._techvault_scripts import (
    TECHVAULT_BEDROCK_SHARD_SCRIPT,
    VERIFY_TECHVAULT_BOOTSTRAP_SCRIPT,
)
from .base import SetupStep

# Claude model defaults for the TechVault host agent (AWS Bedrock plane).
# Keep in sync with the POLARIS Bedrock defaults (_polaris_scripts / plan).
_AWS_DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"
_AWS_DEFAULT_SMALL_FAST_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_DEFAULT_AWS_REGION = "us-east-2"


class TechVaultRangeBootstrapPlan:
    """Per-range TechVault host bootstrap (AWS Bedrock credential shard).

    Runs after ``LinuxBootstrapPlan`` against the TechVault EC2 host. One
    step writes ``/etc/profile.d/claude-bedrock.sh`` so Claude Code on the
    host resolves Bedrock model access via the instance role; verification
    checks the shard landed and the ``claude`` CLI is present.
    """

    def __init__(self) -> None:
        """Build the (single) Bedrock shard step + verification."""
        self._default_model = _AWS_DEFAULT_MODEL
        self._default_small_fast_model = _AWS_DEFAULT_SMALL_FAST_MODEL
        self._default_region = _DEFAULT_AWS_REGION
        self._steps: list[SetupStep] = [
            SetupStep(
                name="techvault_bedrock_shard",
                script=TECHVAULT_BEDROCK_SHARD_SCRIPT,
                timeout_seconds=120,
                requires_reboot=False,
            ),
        ]
        self._verify_step = SetupStep(
            name="verify_techvault_range",
            script=VERIFY_TECHVAULT_BOOTSTRAP_SCRIPT,
            timeout_seconds=60,
            is_verification=True,
        )

    @property
    def steps(self) -> list[SetupStep]:
        """Ordered setup steps (satisfies the SetupPlan protocol)."""
        return self._steps

    @property
    def verify_step(self) -> SetupStep | None:
        """Final verification step (satisfies the SetupPlan protocol)."""
        return self._verify_step

    def get_context(self, instance: object) -> dict[str, Any]:
        """Return template variables for the Bedrock shard script.

        Args:
            instance: Object that may carry ``anthropic_model`` /
                ``anthropic_small_fast_model`` overrides; falls back to env
                (``TECHVAULT_ANTHROPIC_MODEL`` / ``ANTHROPIC_MODEL``) then the
                Bedrock defaults.

        Returns:
            Dict with ``anthropic_model``, ``anthropic_small_fast_model``,
            and ``aws_region``.
        """
        model = (
            getattr(instance, "anthropic_model", None)
            or os.environ.get("TECHVAULT_ANTHROPIC_MODEL")
            or os.environ.get("ANTHROPIC_MODEL")
            or self._default_model
        )
        small_fast = (
            getattr(instance, "anthropic_small_fast_model", None)
            or os.environ.get("TECHVAULT_ANTHROPIC_SMALL_FAST_MODEL")
            or os.environ.get("ANTHROPIC_SMALL_FAST_MODEL")
            or self._default_small_fast_model
        )
        region = os.environ.get("AWS_REGION") or self._default_region
        return {
            "anthropic_model": model,
            "anthropic_small_fast_model": small_fast,
            "aws_region": region,
        }
