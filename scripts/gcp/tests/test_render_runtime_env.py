"""Tests for the GCP runtime env renderer."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(module_filename: str, module_name: str):
    module_path = Path(__file__).resolve().parents[1] / module_filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _outputs(
    *,
    public_hostname: str = "",
    managed_tls_enabled: bool = False,
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
            }
        },
        "identity_platform_api_key": {"value": "identity-platform-api-key"},
        "identity_platform_project_id": {"value": "shifter-gcp-dev"},
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
                    "us-central1-docker.pkg.dev/shifter-gcp-dev/"
                    "shifter-gcp-dev-pulumi-provisioner/pulumi-provisioner"
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


def test_render_env_uses_ip_fallback_in_debug_mode():
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs())

    assert "DJANGO_DEBUG=true\n" in rendered
    assert "TF_STATE_BUCKET=shifter-gcp-dev-terraform-state\n" in rendered
    assert "SESSION_COOKIE_SECURE=false\n" in rendered
    assert "CSRF_COOKIE_SECURE=false\n" in rendered
    assert "AUTH_PROVIDER=oidc\n" in rendered
    assert "SITE_URL=http://10.0.0.30\n" in rendered
    assert "DJANGO_ALLOWED_HOSTS=10.0.0.30,localhost,127.0.0.1\n" in rendered
    assert "IDENTITY_PLATFORM_API_KEY=identity-platform-api-key\n" in rendered
    assert "IDENTITY_PLATFORM_PROJECT_ID=shifter-gcp-dev\n" in rendered
    assert "IDENTITY_PLATFORM_AUTH_DOMAIN=shifter-gcp-dev.firebaseapp.com\n" in rendered
    assert "IDENTITY_ALLOWED_EMAIL_DOMAIN=paloaltonetworks.com\n" in rendered
    assert "GDC_ACCESS_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-gdc-access\n" in rendered
    assert "RANGE_NETWORK_ID=projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range\n" in rendered
    assert "RANGE_NETWORK_CIDR=10.50.0.0/16\n" in rendered
    assert "RANGE_NETWORK_REGION=us-central1\n" in rendered
    assert "PORTAL_NETWORK_CIDRS=10.40.0.0/20,10.44.0.0/16\n" in rendered
    assert "GDC_RANGE_NAMESPACE_PREFIX=range\n" in rendered
    assert "GDC_NETWORK_INTERFACE=vxlan0\n" in rendered
    assert "GDC_NETWORK_DNS_NAMESERVERS=8.8.8.8\n" in rendered
    assert "GDC_STATIC_IP_RESERVATION_COUNT=4\n" in rendered
    assert "RANGE_VPC_ID=projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range\n" in rendered
    assert "RANGE_VPC_CIDR=10.50.0.0/16\n" in rendered


def test_render_env_keeps_ip_fallback_until_secure_promotion():
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(public_hostname="portal.example.test", managed_tls_enabled=True))

    assert "SITE_URL=http://10.0.0.30\n" in rendered
    assert "DJANGO_ALLOWED_HOSTS=portal.example.test,10.0.0.30,localhost,127.0.0.1\n" in rendered
    assert (
        "DJANGO_CSRF_TRUSTED_ORIGINS=http://10.0.0.30,http://portal.example.test\n"
        in rendered
    )


def test_render_env_enables_secure_portal_mode_with_hostname_and_tls():
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(
        _outputs(public_hostname="portal.example.test", managed_tls_enabled=True),
        secure_portal_mode=True,
    )

    assert "DJANGO_DEBUG=false\n" in rendered
    assert "SESSION_COOKIE_SECURE=true\n" in rendered
    assert "CSRF_COOKIE_SECURE=true\n" in rendered
    assert "AUTH_PROVIDER=identity_platform\n" in rendered
    assert "SITE_URL=https://portal.example.test\n" in rendered
    assert "DJANGO_ALLOWED_HOSTS=portal.example.test,10.0.0.30,localhost,127.0.0.1\n" in rendered
    assert "IDENTITY_PLATFORM_API_KEY=identity-platform-api-key\n" in rendered
    assert "IDENTITY_PLATFORM_AUTH_DOMAIN=shifter-gcp-dev.firebaseapp.com\n" in rendered


def test_render_env_preserves_bootstrap_admin_lists_from_environment(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_STAFF_EMAILS", "bedwards@paloaltonetworks.com")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", "bedwards@paloaltonetworks.com")
    monkeypatch.setenv("IDENTITY_ALLOWED_EMAILS", "external@example.com")

    rendered = module.render_env(
        _outputs(public_hostname="portal.example.test", managed_tls_enabled=True),
        secure_portal_mode=True,
    )

    assert "PLATFORM_BOOTSTRAP_STAFF_EMAILS=bedwards@paloaltonetworks.com\n" in rendered
    assert "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=bedwards@paloaltonetworks.com\n" in rendered
    assert "IDENTITY_ALLOWED_EMAILS=external@example.com\n" in rendered


def test_render_env_secure_portal_mode_requires_hostname_and_managed_tls():
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    try:
        module.render_env(_outputs(), secure_portal_mode=True)
    except ValueError as exc:
        assert "public_hostname" in str(exc)
        assert "managed_tls_enabled" in str(exc)
    else:
        raise AssertionError("secure portal mode should reject missing hostname/TLS inputs")
