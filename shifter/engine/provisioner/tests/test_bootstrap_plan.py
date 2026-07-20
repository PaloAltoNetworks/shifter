"""Tests for BootstrapPlan."""

import re
from dataclasses import dataclass

import pytest

from plans.bootstrap import BootstrapPlan

# Same bare-{{word}} matcher SetupOrchestrator._render_script uses. Dot-prefixed
# Go/Docker template tokens (`{{.Names}}`, `{{json .X}}`) do not match and are
# expected to survive rendering untouched -- only a bare `{{ word }}` left in
# rendered output would mean a template variable silently failed to resolve.
_BARE_TEMPLATE_TOKEN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass
class MockInstance:
    """Mock instance for testing get_context."""

    hostname: str | None = None
    public_key: str = ""


class TestBootstrapPlan:
    """Tests for BootstrapPlan behavior."""

    def test_steps_in_correct_order(self):
        """Hostname must be set before SSH is configured."""
        plan = BootstrapPlan()
        step_names = [s.name for s in plan.steps]
        assert step_names == ["set_hostname", "configure_ssh"]

    def test_hostname_step_requires_reboot(self):
        """Hostname change requires reboot to take effect."""
        plan = BootstrapPlan()
        hostname_step = next(s for s in plan.steps if s.name == "set_hostname")
        assert hostname_step.requires_reboot is True

    def test_get_context_returns_expected_values(self):
        """get_context returns hostname and public_key."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname="test-dc-1", public_key="ssh-rsa AAAA")
        context = plan.get_context(instance)
        assert context["hostname"] == "test-dc-1"
        assert context["public_key"] == "ssh-rsa AAAA"

    def test_get_context_missing_hostname_raises(self):
        """get_context raises if hostname is missing."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname=None)
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)

    def test_get_context_empty_hostname_raises(self):
        """get_context raises if hostname is empty."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname="")
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)


@dataclass
class MockPolarisInstance:
    """Mock instance for Polaris bootstrap context tests."""

    dc_ip: str | None = "10.1.2.7"
    public_key: str = "ssh-rsa AAAA"
    range_id: int = 7
    agent_role_arn: str = "arn:aws:iam::123456789012:role/shifter-range-7-polaris-agent"


class TestPolarisRangeBootstrapPlan:
    """Tests for PolarisRangeBootstrapPlan step selection and context rendering."""

    def test_get_context_uses_agent_bucket_for_smoketest_tarball(self, monkeypatch, aws_polaris_agent_env):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.delenv("POLARIS_TESTS_BUCKET", raising=False)
        monkeypatch.delenv("AGENT_STORAGE_BUCKET", raising=False)
        monkeypatch.setenv("AGENT_S3_BUCKET", "shifter-dev-user-storage-123")

        context = PolarisRangeBootstrapPlan().get_context(MockPolarisInstance())

        assert context["polaris_tests_bucket"] == "shifter-dev-user-storage-123"
        assert context["polaris_tests_key"] == "polaris/tests/polaris-tests.tar.gz"

    def test_get_context_allows_explicit_tests_bucket_and_key(self, monkeypatch, aws_polaris_agent_env):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.setenv("POLARIS_TESTS_BUCKET", "custom-polaris-tests")
        monkeypatch.setenv("POLARIS_TESTS_KEY", "custom/tests.tar.gz")
        monkeypatch.setenv("AGENT_S3_BUCKET", "ignored-agent-bucket")

        context = PolarisRangeBootstrapPlan().get_context(MockPolarisInstance())

        assert context["polaris_tests_bucket"] == "custom-polaris-tests"
        assert context["polaris_tests_key"] == "custom/tests.tar.gz"

    def test_get_context_requires_tests_bucket(self, monkeypatch):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.delenv("POLARIS_TESTS_BUCKET", raising=False)
        monkeypatch.delenv("AGENT_STORAGE_BUCKET", raising=False)
        monkeypatch.delenv("AGENT_S3_BUCKET", raising=False)

        polaris_range_bootstrap_plan = PolarisRangeBootstrapPlan()
        mock_polaris_instance = MockPolarisInstance()
        with pytest.raises(ValueError, match="POLARIS_TESTS_BUCKET"):
            polaris_range_bootstrap_plan.get_context(mock_polaris_instance)

    def test_aws_provider_selects_s3_fetch_firewall_and_bedrock_shard(self):
        """AWS gets an extra durable-firewall-install step GCP does not (#1377).

        The firewall step runs FIRST -- before polaris_range_bootstrap
        force-recreates a14-kali -- so the participant container can never run
        before the IMDS drop rule is present (#1377 cycle-3 fail-open window)."""
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        plan = PolarisRangeBootstrapPlan(provider="aws")
        step_names = [s.name for s in plan.steps]

        assert step_names == [
            "polaris_install_imds_firewall",
            "polaris_range_bootstrap",
            "polaris_fetch_tests",
            "polaris_install_splice_watcher",
            "polaris_kali_bedrock_shard",
        ]
        # The firewall must precede the step that starts/recreates a14-kali.
        assert step_names.index("polaris_install_imds_firewall") < step_names.index("polaris_range_bootstrap")
        assert "aws s3 cp" in dict(zip(step_names, [s.script for s in plan.steps], strict=True))["polaris_fetch_tests"]

    def test_gcp_provider_selects_gcs_fetch_and_vertex_shard(self):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        plan = PolarisRangeBootstrapPlan(provider="gcp")
        step_names = [s.name for s in plan.steps]

        assert step_names == [
            "polaris_range_bootstrap",
            "polaris_fetch_tests",
            "polaris_install_splice_watcher",
            "polaris_kali_vertex_shard",
        ]
        scripts = dict(zip(step_names, [s.script for s in plan.steps], strict=True))
        assert "gcloud storage cp" in scripts["polaris_fetch_tests"]
        vertex = scripts["polaris_kali_vertex_shard"]
        assert "CLAUDE_CODE_USE_VERTEX" in vertex
        # Metadata exfil path is blocked and the key is owned by the agent user.
        assert "169.254.169.254/32 -j DROP" in vertex
        assert "chown kali:kali /etc/vertex" in vertex

    def test_aws_context_carries_bedrock_model_ids(self, aws_polaris_agent_env):
        """Model ids, region, and STS timing come from the config seam, not module defaults (#1377)."""
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("AGENT_S3_BUCKET", "b")
            context = PolarisRangeBootstrapPlan(provider="aws").get_context(MockPolarisInstance())

        assert context["anthropic_model"] == aws_polaris_agent_env["AWS_POLARIS_AGENT_MAIN_MODEL_ID"]
        assert context["anthropic_small_fast_model"] == aws_polaris_agent_env["AWS_POLARIS_AGENT_SMALL_MODEL_ID"]
        assert context["main_model_id"] == context["anthropic_model"]
        assert context["small_model_id"] == context["anthropic_small_fast_model"]
        assert context["role_arn"] == "arn:aws:iam::123456789012:role/shifter-range-7-polaris-agent"
        assert context["region"] == aws_polaris_agent_env["AWS_POLARIS_AGENT_REGION"]
        assert context["sts_session_duration_seconds"] == 900
        assert context["refresh_window_seconds"] == 300
        assert "vertex_project_id" not in context

    def test_aws_context_carries_range_id_and_environment_for_sts_session_naming(
        self, monkeypatch, aws_polaris_agent_env
    ):
        """The STS session name is built from range_id + environment (#1377); both must render."""
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.setenv("AGENT_S3_BUCKET", "b")
        monkeypatch.setenv("ENVIRONMENT", "aws-dev")

        context = PolarisRangeBootstrapPlan(provider="aws").get_context(MockPolarisInstance(range_id=7))

        assert context["range_id"] == 7
        assert context["environment"] == "aws-dev"

    def test_aws_context_requires_agent_config(self, monkeypatch):
        """No AWS_POLARIS_AGENT_* env -> fail closed, no IMDS/instance-profile fallback (#1377)."""
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.delenv("AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN", raising=False)
        monkeypatch.setenv("AGENT_S3_BUCKET", "b")

        polaris_range_bootstrap_plan = PolarisRangeBootstrapPlan(provider="aws")
        mock_polaris_instance = MockPolarisInstance()
        with pytest.raises(ValueError, match="AWS Polaris agent"):
            polaris_range_bootstrap_plan.get_context(mock_polaris_instance)

    def test_aws_context_requires_agent_role_arn(self, monkeypatch, aws_polaris_agent_env):
        """Config present but no per-range role ARN threaded in -> fail closed (#1377)."""
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.setenv("AGENT_S3_BUCKET", "b")

        polaris_range_bootstrap_plan = PolarisRangeBootstrapPlan(provider="aws")
        mock_polaris_instance = MockPolarisInstance(agent_role_arn="")
        with pytest.raises(ValueError, match="agent_role_arn"):
            polaris_range_bootstrap_plan.get_context(mock_polaris_instance)

    def test_gcp_context_carries_vertex_project_region_models(self):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("POLARIS_TESTS_BUCKET", "gcs-bucket")
            mp.setenv("GCP_RANGE_VERTEX_PROJECT_ID", "proj-123")
            mp.setenv("GCP_RANGE_VERTEX_REGION", "us-east5")
            context = PolarisRangeBootstrapPlan(provider="gcp").get_context(MockPolarisInstance())

        assert context["vertex_project_id"] == "proj-123"
        assert context["vertex_region"] == "us-east5"
        assert context["range_id"] == 7
        assert context["anthropic_model"]
        # GCP has no AWS agent role; POLARIS_RANGE_BOOTSTRAP_SCRIPT's AWS-only
        # a14-kali mount fragments are always present (empty for GCP) so
        # rendering never raises a missing-template-variable error (#1377).
        assert context["aws_agent_setup_block"] == ""
        assert context["aws_agent_compose_block"] == ""

    def test_gcp_context_requires_vertex_project(self, monkeypatch):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.setenv("POLARIS_TESTS_BUCKET", "gcs-bucket")
        monkeypatch.delenv("GCP_RANGE_VERTEX_PROJECT_ID", raising=False)
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

        polaris_range_bootstrap_plan = PolarisRangeBootstrapPlan(provider="gcp")
        mock_polaris_instance = MockPolarisInstance()
        with pytest.raises(ValueError, match="Vertex project"):
            polaris_range_bootstrap_plan.get_context(mock_polaris_instance)


# --- Slice 5 (#1377): host STS refresh, durable IMDS firewall, a14-kali ----
# credential_process wiring, and fail-closed verification. -----------------

# The exact pubkey-validation-to-build-cd transition POLARIS_RANGE_BOOTSTRAP_
# SCRIPT produced before #1377 slice 5 (a single blank line separates the
# validation `fi` from `cd .../build`). GCP's context supplies "" for
# {{ aws_agent_setup_block }}, and substituting "" for a token that occupies
# an entire template line reproduces this blank line exactly.
_ORIGINAL_PUBKEY_VALIDATION_TO_BUILD_CD = """if [[ -z "$KALI_PUBKEY" ]]; then
  echo "polaris bootstrap: KALI_PUBKEY is empty, refusing to rewrite override" >&2
  exit 1
fi

cd /opt/polaris/scenario-dev/polaris/build"""

# The exact a14-kali compose fragment POLARIS_RANGE_BOOTSTRAP_SCRIPT produced
# before #1377 slice 5. GCP must keep producing byte-identical output; only
# the AWS path may append a volumes: block after it.
_ORIGINAL_A14_KALI_COMPOSE_BLOCK = """services:
  a14-kali:
    ports:
      - "22:22"
      - "3389:3389"
    environment:
      KALI_AUTHORIZED_KEY: "$KALI_PUBKEY"
      KALI_SPLICE_PRIVATE_KEY_B64: "$SPLICE_PRIVATE_KEY_B64"
  a9-splice:"""

# The exact VERIFY_POLARIS_BOOTSTRAP_SCRIPT (shared/GCP) contract before
# slice 5. Any AWS-only checks must live in a separate provider-selected
# constant so this one -- and therefore the GCP verification path -- never
# changes by a single byte.
_ORIGINAL_VERIFY_POLARIS_BOOTSTRAP_SCRIPT = """#!/bin/bash
set -euo pipefail

DC_IP="{{ dc_ip }}"

# 1. a14-kali container is running.
if ! docker ps --format \'{{.Names}}\' | grep -qx \'a14-kali\'; then
  echo "polaris verify: a14-kali is not running" >&2
  exit 1
fi

# 2. dns container is running.
if ! docker ps --format \'{{.Names}}\' | grep -qx \'dns\'; then
  echo "polaris verify: dns is not running" >&2
  exit 1
fi

# 3. dns container resolves dc01.boreas.local to THIS range\'s DC IP.
#    Query from inside a14-kali because the alpine `bind` package on the
#    dns container does not include dig (it\'s in the separate `bind-tools`
#    package). a14-kali points at the dns container via docker compose\'s
#    bridge DNS, so this exercises the real participant lookup path.
resolved=$(docker exec a14-kali dig +short dc01.boreas.local || true)
if [[ "$resolved" != "$DC_IP" ]]; then
  echo "polaris verify: dc01.boreas.local resolved to \'$resolved\', expected \'$DC_IP\'" >&2
  exit 1
fi

# 4. a14-kali has the per-instance kali pubkey installed.
if ! docker exec a14-kali test -s /home/kali/.ssh/authorized_keys; then
  echo "polaris verify: a14-kali /home/kali/.ssh/authorized_keys is missing or empty" >&2
  exit 1
fi

# 4a. Splice-relay credential gate (#707): private key staged on a14-kali
#     and matching pubkey installed on a9-splice. Without both halves the
#     Bunker chain (flags 31-36) is unreachable post-splice. Mode is also
#     checked on the private key — wrong perms invite client refusal at
#     ssh-time, which masquerades as the original P0 symptom.
if ! docker exec a14-kali test -s /home/kali/.ssh/splice_relay; then
  echo "polaris verify: splice_relay private key missing on a14-kali" >&2
  exit 1
fi
splice_mode=$(docker exec a14-kali stat -c \'%a\' /home/kali/.ssh/splice_relay 2>/dev/null || echo "")
if [[ "$splice_mode" != "600" ]]; then
  echo "polaris verify: splice_relay private key has wrong mode \'$splice_mode\' (expected 600)" >&2
  exit 1
fi
if ! docker exec a9-splice test -s /root/.ssh/authorized_keys; then
  echo "polaris verify: a9-splice /root/.ssh/authorized_keys is missing or empty" >&2
  exit 1
fi

# 5. a14-kali is NOT on splice-link at range start (the watcher attaches
#    it only after flag 19 is earned). Inspect the container directly
#    with a dot-prefixed Go template so the orchestrator\'s Jinja
#    placeholder regex does not collide (see comments above).
a14_nets=$(docker inspect a14-kali --format \'{{json .NetworkSettings.Networks}}\' 2>/dev/null || true)
if echo "$a14_nets" | grep -q \'"[a-z0-9_-]*splice-link"\'; then
  echo "polaris verify: a14-kali is already on splice-link at boot (should attach only after flag 19)" >&2
  exit 1
fi

# 6. splice watcher service is active.
if ! systemctl is-active --quiet polaris-splice-watcher.service; then
  echo "polaris verify: polaris-splice-watcher.service is not active" >&2
  systemctl status polaris-splice-watcher.service --no-pager >&2 || true
  exit 1
fi

echo "polaris verify: dc01 -> $resolved, kali key installed, splice gated, watcher active"
exit 0
"""


class TestPolarisAwsAgentSecurity:
    """AWS-only host security controls added by #1377 slice 5.

    STS assume-role credential refresh (host-side, never IMDS), a durable
    DOCKER-USER metadata firewall, read-only a14-kali credential delivery,
    and fail-closed verification of all of the above.
    """

    def _aws_context(self, monkeypatch, aws_polaris_agent_env, **overrides):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.setenv("AGENT_S3_BUCKET", "b")
        monkeypatch.setenv("ENVIRONMENT", "aws-dev")
        instance = MockPolarisInstance(**overrides) if overrides else MockPolarisInstance()
        return PolarisRangeBootstrapPlan(provider="aws").get_context(instance)

    # --- KALI_BEDROCK_SHARD_SCRIPT: STS refresh + credential_process -----

    def test_kali_bedrock_shard_renders_sts_refresh_and_credential_process(self, monkeypatch, aws_polaris_agent_env):
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans._polaris_scripts_aws import KALI_BEDROCK_SHARD_SCRIPT

        context = self._aws_context(monkeypatch, aws_polaris_agent_env)
        rendered = SetupOrchestrator._render_script(KALI_BEDROCK_SHARD_SCRIPT, context, "polaris_kali_bedrock_shard")

        assert "aws sts assume-role" in rendered
        assert "--role-arn" in rendered
        assert context["role_arn"] in rendered
        assert "/run/shifter-agent" in rendered
        assert "credential_process" in rendered
        assert "shifter-refresh-bedrock-creds" in rendered
        assert ".timer" in rendered
        assert "systemctl enable" in rendered
        # umask + atomic same-dir temp-then-mv, never a bare `> credentials.json`.
        assert "umask 077" in rendered
        assert "mv " in rendered

    def test_kali_bedrock_shard_has_no_imds_reliance(self, monkeypatch, aws_polaris_agent_env):
        from plans._polaris_scripts_aws import KALI_BEDROCK_SHARD_SCRIPT

        lowered = KALI_BEDROCK_SHARD_SCRIPT.lower()
        assert "hop limit" not in lowered
        assert "hopresponselimit" not in lowered
        assert "modify_instance_metadata_options" not in lowered

    def test_kali_bedrock_shard_never_traces_and_never_warns_past_a_refresh_failure(
        self, monkeypatch, aws_polaris_agent_env
    ):
        """No `set -x` (would echo secrets to logs); the initial refresh call is
        a bare statement under `set -e`, not `|| true`/`|| echo warn`, so a
        failed assume-role aborts the whole step instead of continuing."""
        from plans._polaris_scripts_aws import KALI_BEDROCK_SHARD_SCRIPT

        assert "set -x" not in KALI_BEDROCK_SHARD_SCRIPT
        assert '"$REFRESH_SCRIPT"\n' in KALI_BEDROCK_SHARD_SCRIPT

    def test_kali_bedrock_shard_requires_role_arn_and_region(self, monkeypatch, aws_polaris_agent_env):
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans._polaris_scripts_aws import KALI_BEDROCK_SHARD_SCRIPT

        context = self._aws_context(monkeypatch, aws_polaris_agent_env)
        context["role_arn"] = ""
        rendered = SetupOrchestrator._render_script(KALI_BEDROCK_SHARD_SCRIPT, context, "polaris_kali_bedrock_shard")
        assert "role_arn and region are required" in rendered or "exit 2" in rendered

    # --- INSTALL_IMDS_FIREWALL_SCRIPT: durable DOCKER-USER block ----------

    def test_install_imds_firewall_targets_docker_user_and_preserves_dns_resolver(self):
        from plans._polaris_scripts_aws import INSTALL_IMDS_FIREWALL_SCRIPT

        script = INSTALL_IMDS_FIREWALL_SCRIPT
        assert "DOCKER-USER" in script
        assert "169.254.169.254/32" in script
        assert "-j DROP" in script
        # The VPC DNS resolver must never be targeted by a DROP rule.
        assert "169.254.169.253" not in script

    def test_install_imds_firewall_is_durable_not_a_one_time_call(self):
        """Must install a restore unit ordered against Docker -- not just call
        iptables once (the exact anti-pattern the design doc calls out)."""
        from plans._polaris_scripts_aws import INSTALL_IMDS_FIREWALL_SCRIPT

        script = INSTALL_IMDS_FIREWALL_SCRIPT
        assert "docker.service" in script
        assert "systemctl enable" in script
        assert "ExecStartPost" in script
        assert ".service" in script

    def test_install_imds_firewall_fails_closed_on_missing_rule_or_inactive_unit(self):
        from plans._polaris_scripts_aws import INSTALL_IMDS_FIREWALL_SCRIPT

        script = INSTALL_IMDS_FIREWALL_SCRIPT
        assert "exit 1" in script
        assert "is-enabled" in script
        assert "is-active" in script

    def test_install_imds_firewall_blocks_ipv6_imds_too(self):
        from plans._polaris_scripts_aws import INSTALL_IMDS_FIREWALL_SCRIPT

        script = INSTALL_IMDS_FIREWALL_SCRIPT
        assert "ip6tables" in script
        assert "fd00:ec2::254" in script

    def test_install_imds_firewall_step_is_aws_only(self):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        gcp_step_names = [s.name for s in PolarisRangeBootstrapPlan(provider="gcp").steps]
        assert "polaris_install_imds_firewall" not in gcp_step_names

    # --- a14-kali read-only mount: AWS-only gate in the SHARED script -----

    def test_aws_compose_rewrite_adds_readonly_agent_mount_for_a14_kali(self, monkeypatch, aws_polaris_agent_env):
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans._polaris_scripts import POLARIS_RANGE_BOOTSTRAP_SCRIPT

        context = self._aws_context(monkeypatch, aws_polaris_agent_env)
        context.update({"dc_ip": "10.1.2.7", "public_key": "ssh-rsa AAAA"})
        rendered = SetupOrchestrator._render_script(POLARIS_RANGE_BOOTSTRAP_SCRIPT, context, "polaris_range_bootstrap")

        assert "/run/shifter-agent:/run/shifter-agent:ro" in rendered

    def test_aws_provider_config_is_recreate_durable_not_written_into_container(
        self, monkeypatch, aws_polaris_agent_env
    ):
        """#1377 cycle-2 finding 2: a14-kali's provider config must survive a
        ``docker compose up --force-recreate``. It is therefore delivered by the
        compose override (environment + bind mounts + extra_hosts) plus host-side
        files under /run/shifter-agent materialized BEFORE the container starts --
        never written into the container layer via ``docker cp`` / ``docker exec``
        (which a recreate discards)."""
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans._polaris_scripts import POLARIS_RANGE_BOOTSTRAP_SCRIPT
        from plans._polaris_scripts_aws import KALI_BEDROCK_SHARD_SCRIPT

        context = self._aws_context(monkeypatch, aws_polaris_agent_env)
        context.update({"dc_ip": "10.1.2.7", "public_key": "ssh-rsa AAAA"})
        bootstrap = SetupOrchestrator._render_script(POLARIS_RANGE_BOOTSTRAP_SCRIPT, context, "polaris_range_bootstrap")
        shard = SetupOrchestrator._render_script(KALI_BEDROCK_SHARD_SCRIPT, context, "polaris_kali_bedrock_shard")

        # (a) Durable config lives in the compose override: env for docker exec /
        # PID-1, a bind of the profile.d shim for SSH login shells, and an
        # extra_hosts entry compose re-substitutes from .env on every recreate.
        assert 'AWS_CONFIG_FILE: "/run/shifter-agent/aws-config"' in bootstrap
        assert "CLAUDE_CODE_USE_BEDROCK:" in bootstrap
        assert context["region"] in bootstrap
        assert "/run/shifter-agent/claude-bedrock.sh:/etc/profile.d/claude-bedrock.sh:ro" in bootstrap
        assert "extra_hosts:" in bootstrap
        assert "${SHIFTER_BEDROCK_IP}" in bootstrap
        # STS is pinned the same way so the in-container agent-role verify
        # (aws sts get-caller-identity) can resolve the regional STS endpoint.
        assert "${SHIFTER_STS_IP}" in bootstrap

        # (b) The host materializes the reader / aws-config / profile.d shim and
        # publishes the Bedrock + STS VPC-endpoint IPs to the compose .env (via
        # _pin_endpoint_ip), all before the container starts (so a bind mount +
        # compose substitution work).
        assert "cat > /run/shifter-agent/credential-process.sh" in bootstrap
        assert "cat > /run/shifter-agent/aws-config" in bootstrap
        assert "cat > /run/shifter-agent/claude-bedrock.sh" in bootstrap
        assert '_pin_endpoint_ip "bedrock-runtime' in bootstrap
        assert '_pin_endpoint_ip "sts.' in bootstrap
        assert "/opt/polaris/scenario-dev/polaris/build/.env" in bootstrap

        # (c) The shard must NOT write provider config into the container layer
        # (the recreate-fragile anti-pattern the finding flags).
        assert "docker cp" not in shard
        assert "a14-kali:/home/kali/.aws" not in shard
        assert "/etc/profile.d/claude-bedrock.sh" not in shard
        assert "/etc/hosts" not in shard

    def test_rendered_aws_bootstrap_scripts_are_valid_shell(self, monkeypatch, aws_polaris_agent_env):
        """#1377 cycle-3: a raw-string ending bug produced an unterminated quote in
        the rendered AWS bootstrap (the trailing backslash escaped the closing
        quote). Guard against any such shell syntax error by running `bash -n`
        over every rendered AWS SSM script."""
        import shutil
        import subprocess
        import tempfile

        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans._polaris_scripts import POLARIS_RANGE_BOOTSTRAP_SCRIPT
        from plans._polaris_scripts_aws import (
            KALI_BEDROCK_SHARD_SCRIPT,
            VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS,
        )

        # Resolve an absolute bash path (avoids ruff S607 partial-path) and skip
        # cleanly where bash is unavailable rather than failing spuriously.
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash not available for shell syntax check")

        context = self._aws_context(monkeypatch, aws_polaris_agent_env)
        context.update({"dc_ip": "10.1.2.7", "public_key": "ssh-rsa AAAA"})
        scripts = {
            "polaris_range_bootstrap": POLARIS_RANGE_BOOTSTRAP_SCRIPT,
            "polaris_kali_bedrock_shard": KALI_BEDROCK_SHARD_SCRIPT,
            "verify_polaris_range": VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS,
        }
        for name, tmpl in scripts.items():
            rendered = SetupOrchestrator._render_script(tmpl, context, name)
            with tempfile.NamedTemporaryFile("w", suffix=".sh") as f:
                f.write(rendered)
                f.flush()
                result = subprocess.run(  # noqa: S603 — absolute bash path, list args, no shell
                    [bash, "-n", f.name], capture_output=True, text=True
                )
            assert result.returncode == 0, f"{name} failed bash -n: {result.stderr}"

    def test_gcp_compose_rewrite_is_byte_identical_to_pre_slice5(self):
        """The AWS-only fragments are Python-computed and substituted via
        plain {{ }} tokens (never a bash-runtime `if`), so with both tokens
        empty (GCP's actual context) rendering must reproduce, byte for byte,
        both insertion points exactly as they were before #1377 slice 5:
        the compose YAML block, and the blank line before `cd .../build`."""
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans._polaris_scripts import POLARIS_RANGE_BOOTSTRAP_SCRIPT

        context = {
            "dc_ip": "10.1.2.7",
            "public_key": "ssh-rsa AAAA",
            "aws_agent_setup_block": "",
            "aws_agent_compose_block": "",
        }
        rendered = SetupOrchestrator._render_script(POLARIS_RANGE_BOOTSTRAP_SCRIPT, context, "polaris_range_bootstrap")

        assert _ORIGINAL_A14_KALI_COMPOSE_BLOCK in rendered
        assert _ORIGINAL_PUBKEY_VALIDATION_TO_BUILD_CD in rendered
        assert "/run/shifter-agent" not in rendered
        assert "credential_process" not in rendered

    # --- Fail-closed verification (AWS-only verify_step variant) ----------

    def test_gcp_verify_script_is_byte_identical_to_pre_slice5(self):
        from plans._polaris_scripts import VERIFY_POLARIS_BOOTSTRAP_SCRIPT

        assert VERIFY_POLARIS_BOOTSTRAP_SCRIPT == _ORIGINAL_VERIFY_POLARIS_BOOTSTRAP_SCRIPT

    def test_gcp_verify_step_uses_shared_script(self):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        plan = PolarisRangeBootstrapPlan(provider="gcp")
        from plans._polaris_scripts import VERIFY_POLARIS_BOOTSTRAP_SCRIPT

        assert plan.verify_step.script == VERIFY_POLARIS_BOOTSTRAP_SCRIPT

    def test_aws_verify_step_uses_aws_variant_with_extra_checks(self):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        plan = PolarisRangeBootstrapPlan(provider="aws")
        from plans._polaris_scripts import VERIFY_POLARIS_BOOTSTRAP_SCRIPT
        from plans._polaris_scripts_aws import VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

        assert plan.verify_step.script == VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS
        assert plan.verify_step.script != VERIFY_POLARIS_BOOTSTRAP_SCRIPT
        # The AWS variant is a strict superset: every shared check still runs.
        common_checks = [
            "a14-kali is not running",
            "dc01.boreas.local resolved to",
            "authorized_keys is missing or empty",
            "splice_relay private key missing",
            "polaris-splice-watcher.service is not active",
        ]
        for marker in common_checks:
            assert marker in VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

    def test_aws_verify_script_checks_firewall_present(self):
        from plans._polaris_scripts_aws import VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

        assert "DOCKER-USER" in VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS
        assert "169.254.169.254/32" in VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

    def test_aws_verify_script_checks_sts_refresh_and_creds_file(self):
        from plans._polaris_scripts_aws import VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

        assert "/run/shifter-agent/credentials.json" in VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

    def test_aws_verify_script_checks_caller_identity_is_agent_role(self, monkeypatch, aws_polaris_agent_env):
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans._polaris_scripts_aws import VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

        context = self._aws_context(monkeypatch, aws_polaris_agent_env)
        context.update({"dc_ip": "10.1.2.7"})
        rendered = SetupOrchestrator._render_script(
            VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS, context, "verify_polaris_range"
        )

        assert "sts get-caller-identity" in rendered
        # The agent role name (last ARN path segment) must be derived and checked.
        role_name = context["role_arn"].rsplit("/", 1)[-1]
        assert role_name in rendered

    def test_aws_verify_script_checks_bedrock_smoke_invocation(self, monkeypatch, aws_polaris_agent_env):
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans._polaris_scripts_aws import VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

        context = self._aws_context(monkeypatch, aws_polaris_agent_env)
        context.update({"dc_ip": "10.1.2.7"})
        rendered = SetupOrchestrator._render_script(
            VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS, context, "verify_polaris_range"
        )

        assert "bedrock-runtime invoke-model" in rendered
        assert context["small_model_id"] in rendered

    def test_aws_verify_script_checks_imds_denied_from_a14_kali(self):
        from plans._polaris_scripts_aws import VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS

        script = VERIFY_POLARIS_BOOTSTRAP_SCRIPT_AWS
        assert "169.254.169.254" in script
        assert "a14-kali" in script
        assert "curl" in script
        # #1377 codex fix: probe the IMDSv2 token endpoint with PUT and treat any
        # HTTP response as reachability. A reachable IMDSv2 answers a tokenless
        # GET with 401, so a "non-2xx == blocked" check is a false negative that
        # would let a firewall failure pass. The denial check must therefore key
        # on the token endpoint + curl's connection success, not an HTTP 2xx.
        assert "latest/api/token" in script
        assert "PUT" in script
        assert "== 2*" not in script

    # --- No secret ever enters the render context / rendered scripts ------

    def test_render_all_aws_steps_and_verify_no_missing_tokens_or_secret_shaped_values(
        self, monkeypatch, aws_polaris_agent_env
    ):
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        plan = PolarisRangeBootstrapPlan(provider="aws")
        context = self._aws_context(monkeypatch, aws_polaris_agent_env)
        context.update({"dc_ip": "10.1.2.7", "public_key": "ssh-rsa AAAA"})

        # Never a raw STS/AWS access-key or session-token shape in context --
        # this whole design exists so those values never reach Python at all.
        for value in context.values():
            text = str(value)
            assert not text.startswith("AKIA")
            assert not text.startswith("ASIA")
            assert "SecretAccessKey" not in text
            assert "SessionToken" not in text

        for step in [*plan.steps, plan.verify_step]:
            rendered = SetupOrchestrator._render_script(step.script, context, step.name)
            assert not _BARE_TEMPLATE_TOKEN.findall(rendered), f"leftover template token in step {step.name}"

    def test_render_all_gcp_steps_no_missing_tokens(self):
        from orchestrators.setup_orchestrator import SetupOrchestrator
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("POLARIS_TESTS_BUCKET", "gcs-bucket")
            mp.setenv("GCP_RANGE_VERTEX_PROJECT_ID", "proj-123")
            plan = PolarisRangeBootstrapPlan(provider="gcp")
            context = plan.get_context(MockPolarisInstance())

        for step in [*plan.steps, plan.verify_step]:
            rendered = SetupOrchestrator._render_script(step.script, context, step.name)
            assert not _BARE_TEMPLATE_TOKEN.findall(rendered), f"leftover template token in step {step.name}"
