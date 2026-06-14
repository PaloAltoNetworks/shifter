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
from typing import Any, ClassVar

from ._polaris_scripts import (
    FETCH_POLARIS_TESTS_SCRIPT,
    INSTALL_SPLICE_WATCHER_SCRIPT,
    KALI_BEDROCK_SHARD_SCRIPT,
    POLARIS_RANGE_BOOTSTRAP_SCRIPT,
    VERIFY_POLARIS_BOOTSTRAP_SCRIPT,
)
from .base import SetupStep


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

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="polaris_range_bootstrap",
            script=POLARIS_RANGE_BOOTSTRAP_SCRIPT,
            timeout_seconds=300,
            requires_reboot=False,
        ),
        SetupStep(
            name="polaris_fetch_tests",
            script=FETCH_POLARIS_TESTS_SCRIPT,
            timeout_seconds=120,
            requires_reboot=False,
        ),
        SetupStep(
            name="polaris_install_splice_watcher",
            script=INSTALL_SPLICE_WATCHER_SCRIPT,
            timeout_seconds=60,
            requires_reboot=False,
        ),
        SetupStep(
            name="polaris_kali_bedrock_shard",
            script=KALI_BEDROCK_SHARD_SCRIPT,
            timeout_seconds=180,
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_polaris_range",
        script=VERIFY_POLARIS_BOOTSTRAP_SCRIPT,
        timeout_seconds=60,
        is_verification=True,
    )

    @staticmethod
    def get_context(instance: object) -> dict[str, Any]:
        """Return template variables for the polaris range bootstrap script.

        Args:
            instance: Object with `dc_ip` and `public_key` attributes
                (the per-instance ssh public key from terraform's
                tls_private_key.instance).

        Returns:
            Dict with `dc_ip` and `public_key`.

        Raises:
            ValueError: If either is missing or empty.
        """
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
                "(per-instance kali pubkey from tls_private_key.instance)"
            )

        # Bedrock model identifiers for the kali-bedrock-shard step.
        # Match the same defaults the kali AMI bake set in
        # shifter/packer/scripts/kali/claude-code.sh — keep these in
        # sync. Per-range override would go on the InstanceSpec
        # (`anthropic_model`) if needed for sharding across model
        # variants; for now we ship the same shard everyone uses.
        anthropic_model = getattr(instance, "anthropic_model", "us.anthropic.claude-sonnet-4-6")
        anthropic_small_fast_model = getattr(
            instance,
            "anthropic_small_fast_model",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        )
        polaris_tests_bucket = (
            os.environ.get("POLARIS_TESTS_BUCKET")
            or os.environ.get("AGENT_STORAGE_BUCKET")
            or os.environ.get("AGENT_S3_BUCKET")
            or ""
        )
        if not polaris_tests_bucket:
            raise ValueError(
                "PolarisRangeBootstrapPlan requires POLARIS_TESTS_BUCKET or "
                "AGENT_S3_BUCKET so the range host can fetch the smoketest tarball"
            )
        polaris_tests_key = os.environ.get("POLARIS_TESTS_KEY", "polaris/tests/polaris-tests.tar.gz")

        return {
            "dc_ip": dc_ip,
            "public_key": public_key,
            "anthropic_model": anthropic_model,
            "anthropic_small_fast_model": anthropic_small_fast_model,
            "polaris_tests_bucket": polaris_tests_bucket,
            "polaris_tests_key": polaris_tests_key,
        }
