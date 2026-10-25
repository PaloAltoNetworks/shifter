"""Server-owned deployment scope resolution (#2086, ADR-063-R1)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from shared.deployment import resolve_audit_deployment_scope, resolve_deployment_scope


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


def test_audit_scope_prefers_the_cloud_renderer_identity():
    with override_settings(
        AUDIT_DEPLOYMENT_SCOPE="aws:123456789012:us-east-2:dev",
        GCP_PROJECT_ID="",
        WARM_POOL_DEPLOYMENT_NAME="",
    ):
        assert resolve_audit_deployment_scope() == "aws:123456789012:us-east-2:dev"


def test_audit_scope_accepts_the_existing_gcp_project_identity():
    with override_settings(AUDIT_DEPLOYMENT_SCOPE="", GCP_PROJECT_ID="proj-abc", WARM_POOL_DEPLOYMENT_NAME=""):
        assert resolve_audit_deployment_scope() == "proj-abc"


def test_audit_scope_rejects_local_sentinel_in_a_deployed_runtime(monkeypatch):
    for name in ("DB_SECRET_ID", "DB_SECRET_ARN", "APP_SECRET_ID", "APP_SECRET_ARN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DB_SECRET_ID", "projects/example/secrets/db")

    with (
        override_settings(AUDIT_DEPLOYMENT_SCOPE="", GCP_PROJECT_ID="", WARM_POOL_DEPLOYMENT_NAME=""),
        pytest.raises(ImproperlyConfigured, match="AUDIT_DEPLOYMENT_SCOPE"),
    ):
        resolve_audit_deployment_scope()
