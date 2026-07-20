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

from config import load_aws_polaris_agent_config

from ._polaris_scripts import (
    FETCH_POLARIS_TESTS_SCRIPT,
    INSTALL_SPLICE_WATCHER_SCRIPT,
    POLARIS_RANGE_BOOTSTRAP_SCRIPT,
    VERIFY_POLARIS_BOOTSTRAP_SCRIPT,
)
from ._polaris_scripts_aws import (
    INSTALL_IMDS_FIREWALL_SCRIPT,
    KALI_BEDROCK_SHARD_SCRIPT,
    VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS,
    render_aws_agent_blocks,
)
from ._polaris_scripts_gcp import (
    FETCH_POLARIS_TESTS_SCRIPT_GCS,
    KALI_VERTEX_SHARD_SCRIPT,
)
from .base import SetupStep

# Claude model defaults for the a14-kali agent's GCP Vertex credential plane.
# The AWS Bedrock plane has no independent defaults anymore -- its region,
# model ids, and STS session lifecycle all come from the single config seam
# (config.load_aws_polaris_agent_config, #1377) so they can't drift from the
# per-range Terraform agent-role policy.
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
    5. AWS only (#1377 slice 5): install the durable DOCKER-USER metadata
       firewall, then have a14-kali obtain its Bedrock credential via a
       host-refreshed STS session and AWS SDK ``credential_process``
       instead of IMDS.

    Verification:

    - dns container resolves dc01.boreas.local to the range-local DC IP
      (not the bake-time IP from range 0).
    - a14-kali container has /home/kali/.ssh/authorized_keys present.
    - a14-kali is NOT attached to splice-link at boot.
    - polaris-splice-watcher.service is active.
    - AWS only: the DOCKER-USER metadata firewall is present, the host STS
      refresh produced a live credentials file, a14-kali's assumed identity
      resolves to this range's agent role, a minimal Bedrock invocation
      succeeds, and IMDS is unreachable from inside a14-kali.
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
            verify_script = VERIFY_POLARIS_BOOTSTRAP_SCRIPT
        else:
            fetch_script = FETCH_POLARIS_TESTS_SCRIPT
            shard_step = SetupStep(
                name="polaris_kali_bedrock_shard",
                script=KALI_BEDROCK_SHARD_SCRIPT,
                timeout_seconds=180,
                requires_reboot=False,
            )
            verify_script = VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS
        self._steps: list[SetupStep] = []
        if self.provider != "gcp":
            # AWS-only: install the durable DOCKER-USER metadata firewall FIRST,
            # before polaris_range_bootstrap force-recreates a14-kali, so the
            # participant container can never run before the IMDS drop rule is
            # present (#1377 cycle-3: fail-open transition window). This is
            # defense-in-depth on top of the declarative HttpPutResponseHopLimit=1
            # on the range instance (terraform modules/range/main.tf), which is
            # the primary control -- a 2-hop container cannot obtain an IMDSv2
            # token at all regardless of firewall timing. GCP keeps its own inline
            # metadata block in KALI_VERTEX_SHARD_SCRIPT, so this step never runs
            # there.
            self._steps.append(
                SetupStep(
                    name="polaris_install_imds_firewall",
                    script=INSTALL_IMDS_FIREWALL_SCRIPT,
                    timeout_seconds=60,
                    requires_reboot=False,
                )
            )
        self._steps += [
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
        ]
        self._steps.append(shard_step)
        self._verify_step = SetupStep(
            name="verify_polaris_range",
            script=verify_script,
            timeout_seconds=120,
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
            # AWS-only POLARIS_RANGE_BOOTSTRAP_SCRIPT fragments (#1377 slice
            # 5); empty by default so GCP's render is byte-for-byte identical
            # to before -- _aws_agent_context overrides both with real content.
            "aws_agent_setup_block": "",
            "aws_agent_compose_block": "",
        }

    @staticmethod
    def _aws_agent_context(instance: object) -> dict[str, Any]:
        """AWS Bedrock agent-role config for the a14-kali agent (#1377 config seam).

        Region, model ids, and STS session lifecycle are sourced entirely from
        ``config.load_aws_polaris_agent_config()`` -- no independent model/ARN
        defaults live here anymore. Only the per-range agent role ARN (a
        Terraform output, not a static env var) is threaded in via
        ``instance.agent_role_arn``. Carries only the role ARN and non-secret
        config, never a credential or session token -- the actual assume-role
        happens entirely host-side (KALI_BEDROCK_SHARD_SCRIPT, #1377 slice 5),
        using the range host's own instance-profile credentials.

        Raises:
            ValueError: The AWS Polaris agent config is not set, or
                ``instance.agent_role_arn`` is missing/empty.
        """
        agent_config = load_aws_polaris_agent_config()
        if agent_config is None:
            raise ValueError(
                "PolarisRangeBootstrapPlan (AWS) requires the AWS Polaris agent Bedrock "
                "configuration to be set (AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN and "
                "related AWS_POLARIS_AGENT_* env vars); see config.load_aws_polaris_agent_config()"
            )

        role_arn = getattr(instance, "agent_role_arn", None) or ""
        if not role_arn:
            raise ValueError(
                "PolarisRangeBootstrapPlan (AWS) requires instance.agent_role_arn "
                "(the per-range Polaris Bedrock agent role ARN from the Terraform output)"
            )

        # Build the AWS-only bootstrap fragments with the validated region/model
        # ids baked in (#1377 cycle-2 finding 2): a14-kali's credential_process
        # reader, AWS profile, Claude/Bedrock env, and Bedrock VPC-endpoint hosts
        # entry are delivered durably via host mounts + the compose override,
        # never written into the container layer.
        setup_block, compose_block = render_aws_agent_blocks(
            agent_config.region, agent_config.main_model_id, agent_config.small_model_id
        )

        return {
            "anthropic_model": agent_config.main_model_id,
            "anthropic_small_fast_model": agent_config.small_model_id,
            "role_arn": role_arn,
            "region": agent_config.region,
            "sts_session_duration_seconds": agent_config.sts_session_duration_seconds,
            "refresh_window_seconds": agent_config.refresh_window_seconds,
            "main_model_id": agent_config.main_model_id,
            "small_model_id": agent_config.small_model_id,
            # Non-secret STS session-name components (#1377 slice 5): the host
            # refresh script builds `<environment>-range-<range_id>` so
            # CloudTrail can correlate a session back to its range without
            # embedding any user data or secret material.
            "range_id": getattr(instance, "range_id", 0) or 0,
            "environment": os.environ.get("ENVIRONMENT", "dev"),
            "aws_agent_setup_block": setup_block,
            "aws_agent_compose_block": compose_block,
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
