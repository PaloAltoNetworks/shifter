"""POLARIS range per-instance bootstrap plan.

The polaris VM AMI is baked from a working range-0 docker compose stack —
17 containers including a14-kali and a dns container that hardcodes
dc01.boreas.local to range 0's DC IP. When the AMI is launched into a
fresh user range, two things must happen before participants can use it:

1. The dns container's docker-compose.override.yml carries DC01_IP from
   bake time. Each user range has its DC at a *different* private IP
   (.11 of that range's subnet — different last octet across ranges).
   The override has to be regenerated with this range's actual DC IP and
   the dns container recreated so its zone file resolves dc01 correctly.

2. The a14-kali container has a per-bake authorized_keys for the bake-
   time terraform tls_private_key. Each user range has its own
   tls_private_key.instance generated at apply time. The container's
   /home/kali/.ssh/authorized_keys has to be replaced with this range's
   per-instance public key so the portal terminal UI can SSH in as kali.

Both regenerations run via SSM RunCommand against the polaris VM EC2
host. The dns + a14-kali container entrypoints (already in the AMI's
docker-compose stack) sed/echo the new env-var values into the in-
container files on startup, so we just rewrite the override file on the
host and `docker compose up -d --force-recreate` the two affected
containers.

This plan runs AFTER LinuxBootstrapPlan in the orchestrator dispatch
for any attacker instance whose ami_key is polaris-vm, gated by the
instance setup caller (no scenario_id plumbing needed).
"""

import os
from typing import Any

from ._polaris_scripts import (
    FETCH_POLARIS_TESTS_SCRIPT,
    INSTALL_SPLICE_WATCHER_SCRIPT,
    KALI_BEDROCK_SHARD_SCRIPT,
    POLARIS_RANGE_BOOTSTRAP_SCRIPT,
    VERIFY_POLARIS_BOOTSTRAP_SCRIPT,
)
from ._polaris_scripts_gcp import (
    FETCH_POLARIS_TESTS_SCRIPT_GCS,
    KALI_VERTEX_SHARD_SCRIPT,
)
from .base import SetupStep

# Claude model defaults for the a14-kali agent, per provider credential plane.
# AWS uses Bedrock model ids; GCP uses Vertex model ids. Keep these in sync
# with the range host image's baked defaults.
_AWS_DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"
_AWS_DEFAULT_SMALL_FAST_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_GCP_DEFAULT_MODEL = "claude-sonnet-4-6"
_GCP_DEFAULT_SMALL_FAST_MODEL = "claude-haiku-4-5"
_GCP_DEFAULT_VERTEX_REGION = "us-east5"


class PolarisRangeBootstrapPlan:
    """Per-range polaris VM bootstrap.

    Runs after LinuxBootstrapPlan against the polaris VM EC2 host. Steps:

    1. Rewrite docker-compose.override.yml with this range's DC IP and
       per-instance kali pubkey.
    2. Force-recreate the dns and a14-kali containers so their
       entrypoints pick up the new env vars.
    3. Fetch the latest scenario-dev/polaris/tests/ tree from the
       shared dev-range-readable S3 bucket so the organizer smoketest
       harness is available on every freshly provisioned range.
    4. Install and start the polaris-splice-watcher systemd service,
       which attaches a14-kali to the splice-link docker network when
       the participant earns flag 19 (A5 thermal runaway). At range
       start A14 is NOT on splice-link.

    Verification:

    - dns container resolves dc01.boreas.local to the range-local DC IP
      (not the bake-time IP from range 0).
    - a14-kali container has /home/kali/.ssh/authorized_keys present.
    - a14-kali is NOT attached to splice-link at boot.
    - polaris-splice-watcher.service is active.
    """

    def __init__(self, provider: str = "aws") -> None:
        """Build the provider-appropriate step list.

        Args:
            provider: ``"gcp"`` selects the GCS artifact fetch + Vertex agent
                shard; anything else selects the AWS S3 fetch + Bedrock shard.
        """
        self.provider = "gcp" if provider == "gcp" else "aws"
        if self.provider == "gcp":
            fetch_script = FETCH_POLARIS_TESTS_SCRIPT_GCS
            shard_step = SetupStep(
                name="polaris_kali_vertex_shard",
                script=KALI_VERTEX_SHARD_SCRIPT,
                timeout_seconds=180,
                requires_reboot=False,
            )
        else:
            fetch_script = FETCH_POLARIS_TESTS_SCRIPT
            shard_step = SetupStep(
                name="polaris_kali_bedrock_shard",
                script=KALI_BEDROCK_SHARD_SCRIPT,
                timeout_seconds=180,
                requires_reboot=False,
            )
        self._steps: list[SetupStep] = [
            SetupStep(
                name="polaris_range_bootstrap",
                script=POLARIS_RANGE_BOOTSTRAP_SCRIPT,
                timeout_seconds=300,
                requires_reboot=False,
            ),
            SetupStep(
                name="polaris_fetch_tests",
                script=fetch_script,
                timeout_seconds=120,
                requires_reboot=False,
            ),
            SetupStep(
                name="polaris_install_splice_watcher",
                script=INSTALL_SPLICE_WATCHER_SCRIPT,
                timeout_seconds=60,
                requires_reboot=False,
            ),
            shard_step,
        ]
        self._verify_step = SetupStep(
            name="verify_polaris_range",
            script=VERIFY_POLARIS_BOOTSTRAP_SCRIPT,
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
        """Return template variables for the polaris range bootstrap scripts.

        Args:
            instance: Object with `dc_ip` and `public_key` attributes (the
                per-range DC private IP and the per-instance ssh public key).

        Returns:
            Dict of render variables covering the shared steps plus the
            provider-specific agent-shard step.

        Raises:
            ValueError: If a required value is missing or empty.
        """
        context = self._base_context(instance)
        agent_context = (
            self._gcp_agent_context(instance) if self.provider == "gcp" else self._aws_agent_context(instance)
        )
        context.update(agent_context)
        return context

    @staticmethod
    def _base_context(instance: object) -> dict[str, Any]:
        """Return the provider-neutral render variables (DC IP, key, tarball)."""
        dc_ip = getattr(instance, "dc_ip", None)
        if not dc_ip:
            raise ValueError(
                "PolarisRangeBootstrapPlan requires instance.dc_ip "
                "(polaris kali host needs the range's DC IP to rewrite "
                "the dns container's zone file)"
            )

        public_key = getattr(instance, "public_key", None)
        if not public_key:
            raise ValueError(
                "PolarisRangeBootstrapPlan requires instance.public_key "
                "(per-instance kali pubkey from the range's ssh key)"
            )

        polaris_tests_bucket = (
            os.environ.get("POLARIS_TESTS_BUCKET")
            or os.environ.get("AGENT_STORAGE_BUCKET")
            or os.environ.get("AGENT_S3_BUCKET")
            or ""
        )
        if not polaris_tests_bucket:
            raise ValueError(
                "PolarisRangeBootstrapPlan requires POLARIS_TESTS_BUCKET (or "
                "AGENT_S3_BUCKET) so the range host can fetch the smoketest tarball"
            )
        return {
            "dc_ip": dc_ip,
            "public_key": public_key,
            "polaris_tests_bucket": polaris_tests_bucket,
            "polaris_tests_key": os.environ.get("POLARIS_TESTS_KEY", "polaris/tests/polaris-tests.tar.gz"),
        }

    @staticmethod
    def _aws_agent_context(instance: object) -> dict[str, Any]:
        """Bedrock model ids for the a14-kali agent (AWS Bedrock plane)."""
        return {
            "anthropic_model": getattr(instance, "anthropic_model", None) or _AWS_DEFAULT_MODEL,
            "anthropic_small_fast_model": (
                getattr(instance, "anthropic_small_fast_model", None) or _AWS_DEFAULT_SMALL_FAST_MODEL
            ),
        }

    @staticmethod
    def _gcp_agent_context(instance: object) -> dict[str, Any]:
        """Vertex project/region/model context for the a14-kali agent (GCP plane)."""
        range_id = getattr(instance, "range_id", None)
        if range_id in (None, ""):
            raise ValueError(
                "Polaris on GCP requires the range id so the a14-kali agent can load its "
                "per-range Vertex key from Secret Manager"
            )
        project = (
            getattr(instance, "vertex_project_id", None)
            or os.environ.get("GCP_RANGE_VERTEX_PROJECT_ID")
            or os.environ.get("GCP_RANGE_CELL_PROJECT_ID")
            or os.environ.get("GCP_PROJECT_ID")
            or ""
        )
        if not project:
            raise ValueError(
                "Polaris on GCP requires a Vertex project: set GCP_RANGE_VERTEX_PROJECT_ID "
                "(or GCP_RANGE_CELL_PROJECT_ID / GCP_PROJECT_ID) so the a14-kali agent can reach Vertex AI"
            )
        region = (
            getattr(instance, "vertex_region", None)
            or os.environ.get("GCP_RANGE_VERTEX_REGION")
            or _GCP_DEFAULT_VERTEX_REGION
        )
        return {
            "range_id": range_id,
            "vertex_project_id": project,
            "vertex_region": region,
            **PolarisRangeBootstrapPlan._vertex_models(instance),
        }

    @staticmethod
    def _vertex_models(instance: object) -> dict[str, Any]:
        """Resolve the Vertex Claude model ids for the a14-kali agent."""
        return {
            "anthropic_model": (
                getattr(instance, "anthropic_model", None)
                or os.environ.get("GCP_RANGE_KALI_ANTHROPIC_MODEL")
                or _GCP_DEFAULT_MODEL
            ),
            "anthropic_small_fast_model": (
                getattr(instance, "anthropic_small_fast_model", None)
                or os.environ.get("GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL")
                or _GCP_DEFAULT_SMALL_FAST_MODEL
            ),
        }
