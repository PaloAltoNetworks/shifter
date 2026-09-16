"""Server-owned deployment scope resolution (#2086, ADR-063-R1)."""

from __future__ import annotations

from django.test import override_settings

from shared.deployment import resolve_deployment_scope


def test_prefers_gcp_project_as_the_resource_ownership_boundary():
    with override_settings(GCP_PROJECT_ID="proj-abc", WARM_POOL_DEPLOYMENT_NAME="wp"):
        assert resolve_deployment_scope() == "proj-abc"


def test_falls_back_to_configured_deployment_name():
    with override_settings(GCP_PROJECT_ID="", WARM_POOL_DEPLOYMENT_NAME="wp-1"):
        assert resolve_deployment_scope() == "wp-1"


def test_unscoped_fallback_is_stable_and_nonempty():
    with override_settings(GCP_PROJECT_ID="", WARM_POOL_DEPLOYMENT_NAME=""):
        scope = resolve_deployment_scope()
        # Must be a fixed constant, not a per-call value: retry-key partitioning by
        # deployment_scope would silently break for unscoped/local-dev otherwise.
        assert scope == "shifter-local-deployment"
        assert resolve_deployment_scope() == scope
