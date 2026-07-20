"""Tests for terraform_vars provider dispatch (unsupported-backend fail-closed).

Covers the two genuine gcp-vs-aws dispatch sites in terraform_vars.py that
previously fell through to AWS-only behavior for any non-gcp provider value:
``_resolve_instance_type`` (EC2 instance-type resolution) and
``_build_range_terraform_variables`` (AWS-only Terraform variable set).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class TestResolveInstanceTypeProviderDispatch:
    """``_resolve_instance_type`` must fail closed for an unsupported provider."""

    def test_raises_for_unsupported_provider(self, monkeypatch):
        import terraform_vars
        from cloud.exceptions import CloudProviderNotImplementedError

        # resolve_cloud_provider() only ever returns a KNOWN_BACKENDS value or
        # raises, so a future third backend is exercised via the module's own
        # imported resolver reference (ADR-019 boundary-mock-policy: object-form
        # monkeypatch.setattr on the first-party module, not a string patch target).
        monkeypatch.setattr(terraform_vars, "resolve_cloud_provider", lambda *a, **k: "azure")

        with pytest.raises(CloudProviderNotImplementedError, match="azure"):
            terraform_vars._resolve_instance_type("attacker", "kali", None)

    def test_override_wins_before_provider_is_resolved(self, monkeypatch):
        """An explicit override must short-circuit before the provider check."""
        import terraform_vars

        monkeypatch.setattr(terraform_vars, "resolve_cloud_provider", lambda *a, **k: "azure")

        assert terraform_vars._resolve_instance_type("attacker", "kali", "custom.type") == "custom.type"


class TestBuildRangeTerraformVariablesProviderDispatch:
    """``_build_range_terraform_variables`` must fail closed for an unsupported provider."""

    def test_raises_for_unsupported_provider(self, monkeypatch):
        import terraform_vars
        from cloud.exceptions import CloudProviderNotImplementedError

        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("RANGE_INSTANCE_PROFILE_NAME", "shifter-dev-range-profile")
        monkeypatch.setattr(
            terraform_vars,
            "load_range_network_config",
            lambda: SimpleNamespace(
                network_id="vpc-test",
                network_cidr="10.1.0.0/16",
                primary_portal_cidr="10.0.0.0/16",
            ),
        )
        monkeypatch.setattr(terraform_vars, "get_range_availability_zone", lambda: "us-east-2a")
        # The provider check at the end of _build_range_terraform_variables reads
        # state_helpers._get_cloud_provider (imported into terraform_vars); patch
        # that reference so no subnets/instances need to exist to reach it.
        monkeypatch.setattr(terraform_vars, "_get_cloud_provider", lambda: "azure")

        with pytest.raises(CloudProviderNotImplementedError, match="azure"):
            terraform_vars._build_range_terraform_variables(
                request_id="req-1",
                range_id=1,
                user_id=2,
                range_spec={"ngfw": False, "subnets": []},
            )
