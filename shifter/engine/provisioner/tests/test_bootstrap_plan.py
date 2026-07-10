"""Tests for BootstrapPlan."""

from dataclasses import dataclass

import pytest

from plans.bootstrap import BootstrapPlan


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


class TestPolarisRangeBootstrapPlan:
    """Tests for PolarisRangeBootstrapPlan step selection and context rendering."""

    def test_get_context_uses_agent_bucket_for_smoketest_tarball(self, monkeypatch):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.delenv("POLARIS_TESTS_BUCKET", raising=False)
        monkeypatch.delenv("AGENT_STORAGE_BUCKET", raising=False)
        monkeypatch.setenv("AGENT_S3_BUCKET", "shifter-dev-user-storage-123")

        context = PolarisRangeBootstrapPlan().get_context(MockPolarisInstance())

        assert context["polaris_tests_bucket"] == "shifter-dev-user-storage-123"
        assert context["polaris_tests_key"] == "polaris/tests/polaris-tests.tar.gz"

    def test_get_context_allows_explicit_tests_bucket_and_key(self, monkeypatch):
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

        with pytest.raises(ValueError, match="POLARIS_TESTS_BUCKET"):
            PolarisRangeBootstrapPlan().get_context(MockPolarisInstance())

    def test_aws_provider_selects_s3_fetch_and_bedrock_shard(self):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        plan = PolarisRangeBootstrapPlan(provider="aws")
        step_names = [s.name for s in plan.steps]

        assert step_names == [
            "polaris_range_bootstrap",
            "polaris_fetch_tests",
            "polaris_install_splice_watcher",
            "polaris_kali_bedrock_shard",
        ]
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

    def test_aws_context_carries_bedrock_model_ids(self):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("AGENT_S3_BUCKET", "b")
            context = PolarisRangeBootstrapPlan(provider="aws").get_context(MockPolarisInstance())

        assert context["anthropic_model"].startswith("us.anthropic.")
        assert "vertex_project_id" not in context

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

    def test_gcp_context_requires_vertex_project(self, monkeypatch):
        from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan

        monkeypatch.setenv("POLARIS_TESTS_BUCKET", "gcs-bucket")
        monkeypatch.delenv("GCP_RANGE_VERTEX_PROJECT_ID", raising=False)
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

        with pytest.raises(ValueError, match="Vertex project"):
            PolarisRangeBootstrapPlan(provider="gcp").get_context(MockPolarisInstance())
