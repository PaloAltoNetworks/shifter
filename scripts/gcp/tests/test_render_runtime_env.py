"""Tests for the GCP runtime env renderer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module(module_filename: str, module_name: str):
    module_path = Path(__file__).resolve().parents[1] / module_filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _outputs(
    *,
    public_hostname: str = "portal.example.test",
    managed_tls_enabled: bool = True,
    identity_allowed_email_domain: str = "paloaltonetworks.com",
    identity_allowed_emails: list[str] | None = None,
) -> dict[str, object]:
    return {
        "assets_bucket_name": {"value": "shifter-gcp-dev-gcp-dev-assets"},
        "terraform_state_bucket_name": {"value": "shifter-gcp-dev-terraform-state"},
        "platform_events_topic_id": {"value": "projects/shifter-gcp-dev/topics/shifter-gcp-dev-events"},
        "platform_event_subscriptions": {
            "value": {
                "cms": "projects/shifter-gcp-dev/subscriptions/shifter-gcp-dev-cms",
                "engine": "projects/shifter-gcp-dev/subscriptions/shifter-gcp-dev-engine",
                "mc": "projects/shifter-gcp-dev/subscriptions/shifter-gcp-dev-mc",
                "experiments": "projects/shifter-gcp-dev/subscriptions/shifter-gcp-dev-experiments",
            }
        },
        "runtime_secret_ids": {
            "value": {
                "app": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-app",
                "db": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db",
                "guacamole-json-auth": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-guacamole-json-auth",
                "redis": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-redis",
            }
        },
        "identity_platform_api_key": {"value": "identity-platform-api-key"},
        "identity_platform_project_id": {"value": "shifter-gcp-dev"},
        "identity_allowed_email_domain": {"value": identity_allowed_email_domain},
        "identity_allowed_emails": {"value": list(identity_allowed_emails or [])},
        "control_plane_database": {
            "value": {
                "private_ip": "10.0.0.10",
                "port": 5432,
            }
        },
        "control_plane_cache": {
            "value": {
                "host": "10.0.0.20",
                "port": 6379,
                "tls_enabled": True,
            }
        },
        "guacamole_database": {
            "value": {
                "host": "10.0.0.10",
                "port": 5432,
                "database_name": "guacamole",
            }
        },
        "artifact_registry_image_roots": {
            "value": {
                "pulumi-provisioner": (
                    "us-central1-docker.pkg.dev/shifter-gcp-dev/shifter-gcp-dev-pulumi-provisioner/pulumi-provisioner"
                ),
            }
        },
        "public_ingress_ip_address": {"value": "10.0.0.30"},
        "public_hostname": {"value": public_hostname},
        "managed_tls_enabled": {"value": managed_tls_enabled},
        "range_network_id": {"value": "projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range"},
        "range_network_cidr": {"value": "10.50.0.0/16"},
        "range_network_region": {"value": "us-central1"},
        "portal_network_cidrs": {"value": ["10.40.0.0/20", "10.44.0.0/16"]},
    }


def test_render_env_emits_production_security_profile():
    """The GCP runtime is always production-secure and addressed via https://<hostname>."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs())

    # Production runtime security profile — unconditional.
    assert "DJANGO_DEBUG=false\n" in rendered
    assert "SESSION_COOKIE_SECURE=true\n" in rendered
    assert "CSRF_COOKIE_SECURE=true\n" in rendered
    assert "AUTH_PROVIDER=identity_platform\n" in rendered
    # Edge: the public hostname over HTTPS only — no http:// origin, no ingress-IP anywhere.
    assert "SITE_URL=https://portal.example.test\n" in rendered
    assert "DJANGO_CSRF_TRUSTED_ORIGINS=https://portal.example.test\n" in rendered
    assert "DJANGO_ALLOWED_HOSTS=portal.example.test,localhost,127.0.0.1\n" in rendered
    assert "http://portal.example.test" not in rendered
    assert "10.0.0.30" not in rendered  # ingress IP is not an accepted application host
    # Other rendered keys.
    assert "TF_STATE_BUCKET=shifter-gcp-dev-terraform-state\n" in rendered
    assert "IDENTITY_PLATFORM_API_KEY=identity-platform-api-key\n" in rendered
    assert "IDENTITY_PLATFORM_PROJECT_ID=shifter-gcp-dev\n" in rendered
    assert "IDENTITY_PLATFORM_AUTH_DOMAIN=shifter-gcp-dev.firebaseapp.com\n" in rendered
    assert "GDC_ACCESS_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-gdc-access\n" in rendered
    assert "RANGE_NETWORK_ID=projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range\n" in rendered
    assert "RANGE_NETWORK_CIDR=10.50.0.0/16\n" in rendered
    assert "RANGE_NETWORK_REGION=us-central1\n" in rendered
    assert "PORTAL_NETWORK_CIDRS=10.40.0.0/20,10.44.0.0/16\n" in rendered
    assert "GDC_RANGE_NAMESPACE_PREFIX=range\n" in rendered
    assert "GDC_STATIC_IP_RESERVATION_COUNT=4\n" in rendered
    assert "RANGE_VPC_ID=projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range\n" in rendered
    assert "RANGE_VPC_CIDR=10.50.0.0/16\n" in rendered


@pytest.mark.parametrize(
    ("missing_kwargs", "expected_substring"),
    [
        ({"public_hostname": ""}, "public_hostname"),
        ({"public_hostname": "   "}, "public_hostname"),
        ({"managed_tls_enabled": False}, "managed_tls_enabled"),
        ({"identity_allowed_email_domain": ""}, "identity_allowed_email_domain"),
    ],
)
def test_render_env_fails_closed_on_insecure_inputs(missing_kwargs, expected_substring):
    """Renderer refuses an insecure runtime: public_hostname + managed_tls_enabled + identity domain are required."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    with pytest.raises(ValueError, match=expected_substring):
        module.render_env(_outputs(**missing_kwargs))


def test_render_env_renders_identity_allow_list_from_terraform_outputs():
    """IDENTITY_ALLOWED_EMAIL_DOMAIN / IDENTITY_ALLOWED_EMAILS come from Terraform outputs, not literals/env."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    default_rendered = module.render_env(_outputs())
    assert "IDENTITY_ALLOWED_EMAIL_DOMAIN=paloaltonetworks.com\n" in default_rendered
    assert "IDENTITY_ALLOWED_EMAILS=" not in default_rendered  # empty list -> no key

    custom_rendered = module.render_env(
        _outputs(
            identity_allowed_email_domain="contractors.example.com",
            identity_allowed_emails=["alice@partner.test", "bob@partner.test"],
        )
    )
    assert "IDENTITY_ALLOWED_EMAIL_DOMAIN=contractors.example.com\n" in custom_rendered
    assert "IDENTITY_ALLOWED_EMAILS=alice@partner.test,bob@partner.test\n" in custom_rendered


def test_render_env_emits_redis_tls_and_secret_id_for_authenticated_cache():
    """GCP Memorystore posture (#963/ADR-008-R6) propagates to the runtime env:
    REDIS_TLS marks the TLS mode and REDIS_SECRET_ID points at the Secret Manager
    bundle that carries the AUTH token. Host/port stay in the ConfigMap-bound env;
    the password never does.
    """
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs())

    assert "REDIS_HOST=10.0.0.20\n" in rendered
    assert "REDIS_PORT=6379\n" in rendered
    assert "REDIS_TLS=true\n" in rendered
    assert "REDIS_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-redis\n" in rendered


def test_render_env_never_emits_redis_password_or_url():
    """Structural secret-leakage gate: the runtime env contract is ConfigMap-bound,
    so it must never carry the Redis AUTH token. The token flows through Secret
    Manager + entrypoint hydration only (ADR-008-R6, #963)."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs())

    # Negative assertions — exact key names the entrypoint exports and any
    # plausible URL/password keys the renderer could leak.
    forbidden_keys = (
        "REDIS_PASSWORD",
        "REDIS_AUTH",
        "REDIS_AUTH_STRING",
        "REDIS_URL",
        "REDIS_DSN",
    )
    for key in forbidden_keys:
        assert f"{key}=" not in rendered, f"runtime env must not contain {key}; AUTH material belongs in Secret Manager"
    # And no `rediss://` URL anywhere — the renderer never builds a URL.
    assert "rediss://" not in rendered
    assert "redis://" not in rendered


def test_render_env_fails_closed_when_cache_payload_lacks_tls_flag():
    """ADR-008-R6 fail-closed: the GCP runtime is the Memorystore-AUTH/TLS
    boundary, so the renderer refuses to emit Redis env vars when the
    Terraform state's control_plane_cache lacks tls_enabled=true. A stale
    state or misconfigured environment surfaces here, not as an opaque
    Django channels_redis startup error."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    outputs = _outputs()
    # Simulate a stale / pre-#963 Terraform output shape (no tls_enabled).
    outputs["control_plane_cache"] = {"value": {"host": "10.0.0.20", "port": 6379}}

    with pytest.raises(ValueError, match="tls_enabled"):
        module.render_env(outputs)


def test_render_env_fails_closed_when_redis_secret_id_missing():
    """ADR-008-R6 fail-closed: the GCP runtime must publish the Memorystore
    Secret Manager bundle ID; refuse to render without it."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    outputs = _outputs()
    # Drop the redis entry from runtime_secret_ids while keeping tls_enabled.
    outputs["runtime_secret_ids"] = {
        "value": {
            "app": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-app",
            "db": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db",
            "guacamole-json-auth": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-guacamole-json-auth",
        }
    }

    with pytest.raises(ValueError, match='runtime_secret_ids\\["redis"\\]'):
        module.render_env(outputs)


def test_render_env_preserves_bootstrap_admin_lists_from_environment(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_STAFF_EMAILS", "bedwards@paloaltonetworks.com")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", "bedwards@paloaltonetworks.com")

    rendered = module.render_env(_outputs())

    assert "PLATFORM_BOOTSTRAP_STAFF_EMAILS=bedwards@paloaltonetworks.com\n" in rendered
    assert "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=bedwards@paloaltonetworks.com\n" in rendered
