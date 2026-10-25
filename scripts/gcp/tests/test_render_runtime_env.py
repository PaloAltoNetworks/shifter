"""Tests for the GCP runtime env renderer."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PINNED_ENGINE_DIGEST = "sha256:" + "1" * 64


def _load_module_from_path(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_module(module_filename: str, module_name: str):
    return _load_module_from_path(Path(__file__).resolve().parents[1] / module_filename, module_name)


# The GCP key inventories moved to runtime_inventory_gcp (#1826, S104 split).
# Load that module directly: it has no package imports, so it loads standalone
# without pulling in the installation package (runtime_inventory.py now uses a
# relative import that a bare file load cannot resolve).
runtime_inventory = _load_module_from_path(
    REPO_ROOT / "shifter/installation/runtime_inventory_gcp.py",
    "installation_runtime_inventory_gcp_for_gcp_tests",
)
GCP_GENERATED_RUNTIME_ENV_KEYS = runtime_inventory.GCP_GENERATED_RUNTIME_ENV_KEYS
GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS = runtime_inventory.GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS


def _rendered_keys(rendered: str) -> set[str]:
    return {line.split("=", 1)[0] for line in rendered.splitlines() if line and not line.startswith("#")}


MAILGUN_BACKEND = "anymail.backends.mailgun.EmailBackend"
SENDGRID_BACKEND = "anymail.backends.sendgrid.EmailBackend"
EMAIL_SECRET_ID = "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-email"

# A complete Mailgun email_config exercises every optional email key
# (EMAIL_BACKEND, DEFAULT_FROM_EMAIL, EMAIL_API_KEY_SECRET_ID,
# MAILGUN_SENDER_DOMAIN) so the runtime-inventory key-match test can assert the
# full optional set renders.
_FULL_MAILGUN_EMAIL_CONFIG = {
    "backend": MAILGUN_BACKEND,
    "from_email": "noreply@shifter.example.test",
    "sender_domain": "mg.shifter.example.test",
    "api_key_secret_id": EMAIL_SECRET_ID,
}


def _seed_gce_range_env(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "GCP_RANGE_BACKEND": "gce",
        "GCP_PROVISIONER_SERVICE_ACCOUNT_EMAIL": "provisioner@example.iam.gserviceaccount.com",
        "GCP_RANGE_PLANE": "compute-engine",
        "GCP_RANGE_CELL_NETWORK_MODE": "vpc-per-range",
        "RANGE_NETWORK_ZONE": "us-central1-b",
        "RANGE_NETWORK_ZONES": "us-central1-a,us-east4-a,us-east1-b",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@example.iam.gserviceaccount.com",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES": "https://www.googleapis.com/auth/cloud-platform",
        "GCP_RANGE_HOST_IDENTITY_POOL_SIZE": "200",
        "GCP_RANGE_LINUX_IMAGE": "projects/debian-cloud/global/images/family/debian-12",
        "GCP_RANGE_LINUX_MACHINE_TYPE": "e2-small",
        "GCP_RANGE_LINUX_DISK_SIZE_GB": "20",
        "GCP_RANGE_LINUX_DISK_TYPE": "pd-balanced",
        "GCP_RANGE_KALI_IMAGE": "projects/kali/global/images/kali",
        "GCP_RANGE_KALI_MACHINE_TYPE": "e2-standard-2",
        "GCP_RANGE_KALI_DISK_SIZE_GB": "40",
        "GCP_RANGE_KALI_DISK_TYPE": "pd-balanced",
        "GCP_RANGE_IMAGE_KEY_PROFILES_JSON": json.dumps(
            {
                "kali": {
                    "example-vm": {
                        "source_image": "projects/test/global/images/family/shifter-example-vm",
                        "machine_type": "e2-standard-8",
                        "disk_size_gb": 210,
                        "disk_type": "pd-balanced",
                    }
                }
            },
            indent=2,
        ),
        "GCP_RANGE_WINDOWS_IMAGE": "projects/windows-cloud/global/images/family/windows-2022",
        "GCP_RANGE_WINDOWS_MACHINE_TYPE": "e2-standard-4",
        "GCP_RANGE_WINDOWS_DISK_SIZE_GB": "80",
        "GCP_RANGE_WINDOWS_DISK_TYPE": "pd-ssd",
        "GCP_RANGE_DC_IMAGE": "projects/windows-cloud/global/images/family/windows-2022",
        "GCP_RANGE_DC_MACHINE_TYPE": "e2-standard-4",
        "GCP_RANGE_DC_DISK_SIZE_GB": "80",
        "GCP_RANGE_DC_DISK_TYPE": "pd-ssd",
        "GCP_RANGE_EGRESS_ALLOW_CIDRS": "10.60.0.0/16",
        "GCP_RANGE_PRIVATE_GOOGLE_ACCESS": "true",
        "GCP_RANGE_HOST_MGMT_SSH_PORT": "2222",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _outputs(
    *,
    public_hostname: str = "portal.example.test",
    managed_tls_enabled: bool = True,
    identity_allowed_email_domain: str = "paloaltonetworks.com",
    dynamic_secret_project_id: str | None = None,
    identity_allowed_emails: list[str] | None = None,
    email_config: dict | None = None,
    ctf_content_bucket_name: str = "",
    native_identity: dict | None = None,
) -> dict[str, object]:
    outputs = {
        "assets_bucket_name": {"value": "shifter-gcp-dev-gcp-dev-assets"},
        "ctf_content_bucket_name": {"value": ctf_content_bucket_name},
        "terraform_state_bucket_name": {"value": "shifter-gcp-dev-terraform-state"},
        "platform_events_topic_id": {"value": "projects/shifter-gcp-dev/topics/shifter-gcp-dev-events"},
        "platform_event_subscriptions": {
            "value": {
                "cms": "projects/shifter-gcp-dev/subscriptions/shifter-gcp-dev-cms",
                "engine": "projects/shifter-gcp-dev/subscriptions/shifter-gcp-dev-engine",
                "mc": "projects/shifter-gcp-dev/subscriptions/shifter-gcp-dev-mc",
            }
        },
        "runtime_secret_ids": {
            "value": {
                "app": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-app",
                "db": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db",
                "db-provisioner": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db-provisioner",
                "db-migration": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db-migration",
                "guacamole-json-auth": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-guacamole-json-auth",
                "redis": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-redis",
            }
        },
        "identity_platform_api_key": {"value": "identity-platform-api-key"},
        "identity_platform_project_id": {"value": "shifter-gcp-dev"},
        "dynamic_secret_project_id": {
            "value": (
                "shifter-gcp-dev-range-secrets" if dynamic_secret_project_id is None else dynamic_secret_project_id
            )
        },
        "provisioner_static_secret_refs": {"value": {}},
        "identity_allowed_email_domain": {"value": identity_allowed_email_domain},
        "identity_allowed_emails": {"value": list(identity_allowed_emails or [])},
        "control_plane_database": {
            "value": {
                "private_ip": "10.0.0.10",
                "port": 5432,
                "database_name": "shifter",
                "user_name": "portal_runtime",
                "provisioner_user_name": "provisioner_runtime",
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
        "portal_network_cidrs": {"value": ["10.46.0.0/20"]},
        "access_network_cidrs": {"value": ["10.47.0.0/20"]},
    }
    if email_config is not None:
        outputs["email_config"] = {"value": email_config}
    if native_identity is not None:
        outputs["native_identity"] = {"value": native_identity}
        outputs["workload_service_accounts"] = {
            "value": {name: user + ".gserviceaccount.com" for name, user in native_identity["database_users"].items()}
        }
    return outputs


def test_render_env_emits_production_security_profile():
    """The GCP runtime is always production-secure and addressed via https://<hostname>."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

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
    # Real deploy project (from the Identity Platform project) so google clients
    # bill the correct quota/consumer project, not the overlay placeholder.
    assert "GCP_PROJECT_ID=shifter-gcp-dev\n" in rendered
    assert "GOOGLE_CLOUD_PROJECT=shifter-gcp-dev\n" in rendered
    assert "GCP_DYNAMIC_SECRET_PROJECT_ID=shifter-gcp-dev-range-secrets\n" in rendered
    # #1742: DB_NAME/DB_USER/CLOUD_PROJECT_ID are literals the provisioner-launcher
    # emits and the restrict-provisioner-jobs admission policy validates against the
    # platform-runtime ConfigMap, so they MUST be rendered here or every GCP range
    # Job is denied.
    assert "DB_NAME=shifter\n" in rendered
    assert "DB_USER=portal_runtime\n" in rendered
    assert "PROVISIONER_DB_USER=provisioner_runtime\n" in rendered
    assert "PROVISIONER_DB_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db-provisioner\n" in rendered
    assert "DB_MIGRATION_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db-migration\n" in rendered
    assert "AUDIT_DEPLOYMENT_SCOPE=gcp:shifter-gcp-dev\n" in rendered
    assert "SKIP_MIGRATIONS=1\n" in rendered
    assert "CLOUD_PROJECT_ID=shifter-gcp-dev\n" in rendered
    assert "IDENTITY_PLATFORM_PROJECT_ID=shifter-gcp-dev\n" in rendered
    assert "IDENTITY_PLATFORM_AUTH_DOMAIN=shifter-gcp-dev.firebaseapp.com\n" in rendered
    assert "GDC_ACCESS_SECRET_ID=" not in rendered
    assert (
        "DC_DOMAIN_PASSWORD_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-dc-domain-password\n" in rendered
    )
    assert "RANGE_NETWORK_ID=projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range\n" in rendered
    assert "RANGE_NETWORK_CIDR=10.50.0.0/16\n" in rendered
    assert "RANGE_NETWORK_REGION=us-central1\n" in rendered
    assert "PORTAL_NETWORK_CIDRS=10.46.0.0/20\n" in rendered
    assert "ACCESS_NETWORK_CIDRS=10.47.0.0/20\n" in rendered
    assert "GCP_RANGE_BACKEND=gce\n" in rendered
    # Range project derived from the range VPC self-link (real range project),
    # independent of the control-plane GCP_PROJECT_ID placeholder.
    assert "GCP_RANGE_CELL_PROJECT_ID=shifter-gcp-dev\n" in rendered
    assert "GDC_RANGE_NAMESPACE_PREFIX=range\n" in rendered
    assert "GDC_STATIC_IP_RESERVATION_COUNT=4\n" in rendered
    assert "RANGE_VPC_ID=projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range\n" in rendered
    assert "RANGE_VPC_CIDR=10.50.0.0/16\n" in rendered
    assert (
        "ENGINE_TASK_IMAGE=us-central1-docker.pkg.dev/"
        "shifter-gcp-dev/shifter-gcp-dev-pulumi-provisioner/pulumi-provisioner@" + PINNED_ENGINE_DIGEST + "\n"
    ) in rendered


def test_render_env_publishes_static_refs_from_terraform_and_ignores_env_override(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    outputs = _outputs()
    outputs["provisioner_static_secret_refs"] = {
        "value": {
            "GDC_ACCESS_SECRET_ID": "projects/owner-project/secrets/gdc-access",
            "GDC_VM_IMAGE_GCS_SECRET_ID": "projects/image-project/secrets/image-key",
        }
    }
    monkeypatch.setenv("GDC_VM_IMAGE_GCS_SECRET_ID", "projects/wrong-project/secrets/wrong-key")

    rendered = module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)

    assert "GDC_ACCESS_SECRET_ID=projects/owner-project/secrets/gdc-access\n" in rendered
    assert "GDC_VM_IMAGE_GCS_SECRET_ID=projects/image-project/secrets/image-key\n" in rendered
    assert "wrong-project" not in rendered


def test_render_env_drops_static_ref_missing_from_terraform_grant_map(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env_without_static_override")
    outputs = _outputs()
    monkeypatch.setenv(
        "GDC_VM_IMAGE_GCS_SECRET_ID",
        "projects/ungranted-project/secrets/ungranted-key",
    )

    rendered = module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)

    assert "GDC_VM_IMAGE_GCS_SECRET_ID=" not in rendered
    assert "ungranted-project" not in rendered


def test_retired_guest_model_inputs_cannot_reenter_runtime(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_without_guest_provider")
    monkeypatch.setenv("GCP_RANGE_VERTEX_PROJECT_ID", "retired-project")
    monkeypatch.setenv("GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID", "projects/retired-project/secrets/shared-key")
    monkeypatch.setenv("GCP_RANGE_KALI_ANTHROPIC_MODEL", "retired-model")
    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)
    assert "retired-" not in rendered
    outputs = _outputs()
    outputs["provisioner_static_secret_refs"] = {
        "value": {"GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID": "projects/retired-project/secrets/shared-key"}
    }
    with pytest.raises(ValueError):
        module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)


@pytest.mark.parametrize(
    "refs",
    [
        {"UNSUPPORTED": "projects/owner-project/secrets/input"},
        {"GDC_ACCESS_SECRET_ID": "bare-secret-name"},
    ],
)
def test_render_env_rejects_invalid_static_ref_contract(refs):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    outputs = _outputs()
    outputs["provisioner_static_secret_refs"] = {"value": refs}

    with pytest.raises(ValueError, match="provisioner_static_secret_refs"):
        module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_emits_cloud_provider():
    """The GCP backend renderer IS the source of the renderer-owned CLOUD_PROVIDER identity

    (PLAT-2005): this module's own backend identity, not a static overlay literal or a
    branch-name inference.
    """
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    assert "CLOUD_PROVIDER=gcp\n" in rendered


def test_render_env_defaults_model_access_to_disabled_without_catalog_body():
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)
    assert "MODEL_ACCESS_ENABLED=false\n" in rendered
    assert "MODEL_ACCESS_CATALOG_PATH=\n" in rendered
    assert "MODEL_ACCESS_CATALOG_DIGEST=\n" in rendered
    assert "model-access-policy/v1" not in rendered


def test_render_env_rejects_incomplete_model_access_projection(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("MODEL_ACCESS_ENABLED", "true")
    with pytest.raises(ValueError, match="path and digest"):
        module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)


_OPENVPN_POOL = {
    "endpoint": "203.0.113.7",
    "subnet_cidr": "10.49.0.0/24",
    "issuer_secret": "projects/p/secrets/shifter-test-vpn-issuer",
    "control_audience": "https://portal.example.com/vpn-control",
    "service_account_email": "shifter-test-vpn@p.iam.gserviceaccount.com",
    "service_account_id": "123456789012345678901",
}


@pytest.mark.parametrize(("configured", "rendered_value"), [(None, "false"), ("", "false"), ("TRUE", "true")])
def test_render_env_always_renders_the_openvpn_opt_in(monkeypatch, configured, rendered_value):
    """Unset renders false, so turning the opt-in off revokes a stale true (#2030)."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    if configured is None:
        monkeypatch.delenv("RANGE_OPENVPN_ENABLED", raising=False)
    else:
        monkeypatch.setenv("RANGE_OPENVPN_ENABLED", configured)
    outputs = {**_outputs(), "openvpn_pool": {"value": _OPENVPN_POOL}}
    rendered = module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)
    assert f"RANGE_OPENVPN_ENABLED={rendered_value}\n" in rendered


def test_render_env_wires_the_shared_pool_only_when_enabled(monkeypatch):
    """The portal and provisioner learn the pool from Terraform; off blanks every key (#2480)."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("RANGE_OPENVPN_ENABLED", "true")
    outputs = {**_outputs(), "openvpn_pool": {"value": _OPENVPN_POOL}}
    rendered = module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST).splitlines()
    for line in (
        "RANGE_OPENVPN_ENDPOINT=203.0.113.7",
        "RANGE_OPENVPN_POOL_CIDRS=10.49.0.0/24",
        "RANGE_OPENVPN_ISSUER_SECRET_ID=projects/p/secrets/shifter-test-vpn-issuer",
        "VPN_CONTROL_AUDIENCE=https://portal.example.com/vpn-control",
        "VPN_CONTROLLER_SERVICE_ACCOUNT_EMAIL=shifter-test-vpn@p.iam.gserviceaccount.com",
        "VPN_CONTROLLER_SERVICE_ACCOUNT_ID=123456789012345678901",
    ):
        assert line in rendered

    monkeypatch.setenv("RANGE_OPENVPN_ENABLED", "false")
    disabled = module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST).splitlines()
    assert "RANGE_OPENVPN_ENDPOINT=" in disabled and "VPN_CONTROLLER_SERVICE_ACCOUNT_ID=" in disabled


def test_render_env_refuses_an_opt_in_without_a_deployed_pool(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("RANGE_OPENVPN_ENABLED", "true")
    with pytest.raises(ValueError, match="openvpn_pool"):
        module.render_env({**_outputs(), "openvpn_pool": {"value": None}}, engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_rejects_a_non_boolean_openvpn_opt_in(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("RANGE_OPENVPN_ENABLED", "yes")
    with pytest.raises(ValueError, match="RANGE_OPENVPN_ENABLED"):
        module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_omits_mission_control_lease_when_unset():
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)
    # Absent -> omitted so the Django runtime applies the canonical defaults.
    assert "MISSION_CONTROL_LEASE_POLICY_JSON" not in rendered


def test_render_env_passes_through_configured_mission_control_lease(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv(
        "MISSION_CONTROL_LEASE_POLICY_JSON",
        '{"initial_days": 7, "extension_days": 3, "maximum_days": 90, "extensions_enabled": false}',
    )
    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)
    line = next(row for row in rendered.splitlines() if row.startswith("MISSION_CONTROL_LEASE_POLICY_JSON="))
    assert json.loads(line.split("=", 1)[1]) == {
        "initial_days": 7,
        "extension_days": 3,
        "maximum_days": 90,
        "extensions_enabled": False,
    }


def test_render_env_rejects_malformed_mission_control_lease(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("MISSION_CONTROL_LEASE_POLICY_JSON", "{not json")
    with pytest.raises(ValueError, match="MISSION_CONTROL_LEASE_POLICY_JSON"):
        module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)


@pytest.mark.parametrize("value", ["", "   "])
def test_render_env_rejects_present_but_blank_mission_control_lease(monkeypatch, value):
    # Present but blank is a broken substitution, distinct from an unset variable.
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("MISSION_CONTROL_LEASE_POLICY_JSON", value)
    with pytest.raises(ValueError, match="present but blank"):
        module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_passes_through_range_telemetry_policy(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv(
        "GCP_RANGE_TELEMETRY_POLICY_JSON",
        '{"vpc_flow_logs": {"enabled": true, "flow_sampling": 0.25}, "nat_logs": {"enabled": false}}',
    )

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    line = next(row for row in rendered.splitlines() if row.startswith("GCP_RANGE_TELEMETRY_POLICY_JSON="))
    assert json.loads(line.split("=", 1)[1]) == {
        "nat_logs": {"enabled": False},
        "vpc_flow_logs": {"enabled": True, "flow_sampling": 0.25},
    }


def test_render_env_omits_range_telemetry_policy_when_unset():
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    # Absent -> omitted so the provisioner applies the default-on policy.
    assert "GCP_RANGE_TELEMETRY_POLICY_JSON" not in rendered


@pytest.mark.parametrize(("value", "message"), [("", "present but blank"), ("[]", "JSON object"), ("{x", "valid JSON")])
def test_render_env_rejects_malformed_range_telemetry_policy(monkeypatch, value, message):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("GCP_RANGE_TELEMETRY_POLICY_JSON", value)

    with pytest.raises(ValueError, match=message):
        module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_keys_match_runtime_inventory(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    assert _rendered_keys(module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)) == set(
        GCP_GENERATED_RUNTIME_ENV_KEYS
    )

    monkeypatch.setenv("PLATFORM_BOOTSTRAP_STAFF_EMAILS", "admin@example.com")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", "admin@example.com")
    monkeypatch.setenv(
        "MISSION_CONTROL_LEASE_POLICY_JSON",
        '{"initial_days":7,"extension_days":3,"maximum_days":90,"extensions_enabled":false}',
    )
    monkeypatch.setenv("GCP_RANGE_TELEMETRY_POLICY_JSON", '{"nat_logs":{"enabled":true}}')
    _seed_gce_range_env(monkeypatch)
    outputs = _outputs(
        identity_allowed_emails=["alice@example.com", "bob@example.com"],
        email_config=_FULL_MAILGUN_EMAIL_CONFIG,
        ctf_content_bucket_name="private-ctf-content",
        native_identity={
            "enabled": True,
            "openfga_enabled": False,
            "instance_connection_name": "shifter-gcp-dev:us-central1:platform-pg",
            "database_users": {
                name: f"synthetic-{name}@shifter-gcp-dev.iam"
                for name in ("portal", "workers", "ctf-scheduler", "provisioner-launcher", "provisioner")
            },
        },
    )
    outputs["provisioner_static_secret_refs"] = {
        "value": {
            key: f"projects/static-project/secrets/{key.lower().replace('_', '-')}"
            for key in (
                "GDC_ACCESS_SECRET_ID",
                "GDC_VM_IMAGE_GCS_SECRET_ID",
                "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID",
                "GDC_VMSERIES_IMAGE_GCS_SECRET_ID",
            )
        }
    }
    rendered = module.render_env(
        outputs,
        engine_image=PINNED_ENGINE_DIGEST,
    )

    assert _rendered_keys(rendered) == set(GCP_GENERATED_RUNTIME_ENV_KEYS | GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS)


def test_native_database_runtime_has_no_password_secret_reference():
    module = _load_module("render_runtime_env.py", "render_runtime_env_native")
    users = {
        name: f"synthetic-{name}@shifter-gcp-dev.iam"
        for name in ("portal", "workers", "ctf-scheduler", "provisioner-launcher", "provisioner")
    }
    outputs = _outputs(
        native_identity={
            "enabled": True,
            "openfga_enabled": False,
            "instance_connection_name": "shifter-gcp-dev:us-central1:platform-pg",
            "database_users": users,
        }
    )
    rendered = module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)
    values = dict(line.split("=", 1) for line in rendered.splitlines() if line and not line.startswith("#"))
    assert values["DB_AUTH_MODE"] == "cloud-sql-proxy"
    assert values["DB_HOST"] == "127.0.0.1"
    assert values["DB_USER"] == users["portal"]
    assert values["PROVISIONER_DB_USER"] == users["provisioner"]
    assert values["DB_SECRET_ID"] == ""
    assert values["PROVISIONER_DB_SECRET_ID"] == ""
    assert "DB_MIGRATION_SECRET_ID" in values
    assert json.loads(values["GCP_DATABASE_IAM_USERS_JSON"]) == users
    assert "DB_PASSWORD" not in values


@pytest.mark.parametrize("fault", ["missing-user", "wrong-user-project", "wrong-instance-project", "unknown-workload"])
def test_native_database_renderer_rejects_untrusted_login_metadata(fault):
    module = _load_module("render_runtime_env.py", "render_runtime_env_native_invalid")
    users = {
        name: f"synthetic-{name}@shifter-gcp-dev.iam"
        for name in ("portal", "workers", "ctf-scheduler", "provisioner-launcher", "provisioner")
    }
    native = {
        "enabled": True,
        "openfga_enabled": False,
        "instance_connection_name": "shifter-gcp-dev:us-central1:platform-pg",
        "database_users": users,
    }
    if fault == "missing-user":
        users.pop("provisioner")
    elif fault == "wrong-user-project":
        users["portal"] = "synthetic-portal@other-project.iam"
    elif fault == "wrong-instance-project":
        native["instance_connection_name"] = "other-project:us-central1:platform-pg"
    else:
        users["operator"] = "synthetic-operator@shifter-gcp-dev.iam"
    with pytest.raises(ValueError, match="native"):
        module.render_env(_outputs(native_identity=native), engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_projects_ctf_content_location_without_private_references():
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(
        _outputs(ctf_content_bucket_name="private-ctf-content"),
        engine_image=PINNED_ENGINE_DIGEST,
    )

    assert "SHIFTER_CTF_CONTENT_BUCKET=private-ctf-content\n" in rendered
    assert "SHIFTER_CTF_CONTENT_PREFIX=ctf/content-bundles\n" in rendered
    assert "SHIFTER_CTF_CONTENT_MAX_BYTES=8388608\n" in rendered
    assert "SHIFTER_CTF_CONTENT_REFERENCES_JSON" not in rendered


def test_render_env_forwards_gce_range_cell_contract(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    _seed_gce_range_env(monkeypatch)

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    assert "GCP_RANGE_BACKEND=gce\n" in rendered
    assert "GCP_PROVISIONER_SERVICE_ACCOUNT_EMAIL=provisioner@example.iam.gserviceaccount.com\n" in rendered
    assert "GCP_RANGE_CELL_NETWORK_MODE=vpc-per-range\n" in rendered
    assert "RANGE_NETWORK_ZONE=us-central1-b\n" in rendered
    assert "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL=range-host@example.iam.gserviceaccount.com\n" in rendered
    assert "GCP_RANGE_HOST_IDENTITY_POOL_SIZE=200\n" in rendered
    assert "GCP_RANGE_LINUX_IMAGE=projects/debian-cloud/global/images/family/debian-12\n" in rendered
    assert "GCP_RANGE_EGRESS_ALLOW_CIDRS=10.60.0.0/16\n" in rendered
    mapping_line = next(line for line in rendered.splitlines() if line.startswith("GCP_RANGE_IMAGE_KEY_PROFILES_JSON="))
    mapping = mapping_line.split("=", 1)[1]
    assert mapping == json.dumps(json.loads(mapping), separators=(",", ":"), sort_keys=True)


def test_render_env_rejects_duplicate_image_profile_keys(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv(
        "GCP_RANGE_IMAGE_KEY_PROFILES_JSON",
        '{"kali":{"example-vm":{},"example-vm":{}}}',
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_still_supports_gdc_backend_override(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gdc")

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    assert "GCP_RANGE_BACKEND=gdc\n" in rendered


def test_render_env_cell_project_id_env_override_wins(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("GCP_RANGE_CELL_PROJECT_ID", "prod-real-project")

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    assert "GCP_RANGE_CELL_PROJECT_ID=prod-real-project\n" in rendered


def test_main_writes_rendered_runtime_env(tmp_path, monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    outputs_path = tmp_path / "terraform-output.json"
    output_path = tmp_path / "platform-runtime.generated.env"
    outputs = _outputs()
    outputs_path.write_text(json.dumps(outputs))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "render_runtime_env.py",
            "--terraform-output-json",
            str(outputs_path),
            "--engine-image-digest",
            PINNED_ENGINE_DIGEST,
            "--output",
            str(output_path),
        ],
    )

    assert module.main() == 0

    assert output_path.read_text() == module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)


@pytest.mark.parametrize(
    ("missing_kwargs", "expected_substring"),
    [
        ({"public_hostname": ""}, "public_hostname"),
        ({"public_hostname": "   "}, "public_hostname"),
        ({"managed_tls_enabled": False}, "managed_tls_enabled"),
        ({"identity_allowed_email_domain": ""}, "identity_allowed_email_domain"),
        ({"dynamic_secret_project_id": ""}, "dynamic_secret_project_id"),
    ],
)
def test_render_env_fails_closed_on_insecure_inputs(missing_kwargs, expected_substring):
    """Renderer refuses an insecure runtime: public_hostname + managed_tls_enabled + identity domain are required."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    with pytest.raises(ValueError, match=expected_substring):
        module.render_env(_outputs(**missing_kwargs), engine_image=PINNED_ENGINE_DIGEST)


@pytest.mark.parametrize("engine_image", ["", "  ", "latest"])
def test_render_env_rejects_missing_or_mutable_engine_image(engine_image):
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    with pytest.raises(ValueError, match="engine_image"):
        module.render_env(_outputs(), engine_image=engine_image)


def test_render_env_accepts_engine_image_tag_for_bootstrap():
    # The GDC bootstrap path passes a version tag; ENGINE_TASK_IMAGE uses root:tag.
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), engine_image="1.2.3")

    assert (
        "ENGINE_TASK_IMAGE=us-central1-docker.pkg.dev/"
        "shifter-gcp-dev/shifter-gcp-dev-pulumi-provisioner/pulumi-provisioner:1.2.3\n"
    ) in rendered


def test_render_env_renders_identity_allow_list_from_terraform_outputs():
    """IDENTITY_ALLOWED_EMAIL_DOMAIN / IDENTITY_ALLOWED_EMAILS come from Terraform outputs, not literals/env."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    default_rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)
    assert "IDENTITY_ALLOWED_EMAIL_DOMAIN=paloaltonetworks.com\n" in default_rendered
    assert "IDENTITY_ALLOWED_EMAILS=" not in default_rendered  # empty list -> no key

    custom_rendered = module.render_env(
        _outputs(
            identity_allowed_email_domain="contractors.example.com",
            identity_allowed_emails=["alice@partner.test", "bob@partner.test"],
        ),
        engine_image=PINNED_ENGINE_DIGEST,
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

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    assert "REDIS_HOST=10.0.0.20\n" in rendered
    assert "REDIS_PORT=6379\n" in rendered
    assert "REDIS_TLS=true\n" in rendered
    assert "REDIS_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-redis\n" in rendered


def test_render_env_never_emits_redis_password_or_url():
    """Structural secret-leakage gate: the runtime env contract is ConfigMap-bound,
    so it must never carry the Redis AUTH token. The token flows through Secret
    Manager + entrypoint hydration only (ADR-008-R6, #963)."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

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
        module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)


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
            "db-provisioner": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db-provisioner",
            "db-migration": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-db-migration",
            "guacamole-json-auth": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-guacamole-json-auth",
        }
    }

    with pytest.raises(ValueError, match='runtime_secret_ids\\["redis"\\]'):
        module.render_env(outputs, engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_emits_console_backend_when_email_unconfigured():
    """Email is optional, but the runtime backend choice is explicit."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    assert "EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend\n" in rendered
    for key in ("DEFAULT_FROM_EMAIL", "EMAIL_API_KEY_SECRET_ID", "MAILGUN_SENDER_DOMAIN"):
        assert f"{key}=" not in rendered


def test_render_env_emits_sendgrid_email_config():
    """A SendGrid email_config renders the backend, sender, and secret reference
    but no Mailgun sender domain."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(
        _outputs(
            email_config={
                "backend": SENDGRID_BACKEND,
                "from_email": "noreply@shifter.example.test",
                "api_key_secret_id": EMAIL_SECRET_ID,
            }
        ),
        engine_image=PINNED_ENGINE_DIGEST,
    )

    assert f"EMAIL_BACKEND={SENDGRID_BACKEND}\n" in rendered
    assert "DEFAULT_FROM_EMAIL=noreply@shifter.example.test\n" in rendered
    assert f"EMAIL_API_KEY_SECRET_ID={EMAIL_SECRET_ID}\n" in rendered
    assert "MAILGUN_SENDER_DOMAIN=" not in rendered


def test_render_env_emits_mailgun_sender_domain():
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(email_config=_FULL_MAILGUN_EMAIL_CONFIG), engine_image=PINNED_ENGINE_DIGEST)

    assert f"EMAIL_BACKEND={MAILGUN_BACKEND}\n" in rendered
    assert "MAILGUN_SENDER_DOMAIN=mg.shifter.example.test\n" in rendered


def test_render_env_never_emits_email_api_key_value():
    """Structural secret-leakage gate: the runtime env carries only the secret
    REFERENCE; the ESP API key is hydrated by entrypoint.sh from Secret Manager."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(
        _outputs(
            email_config={
                "backend": SENDGRID_BACKEND,
                "from_email": "noreply@shifter.example.test",
                "api_key_secret_id": EMAIL_SECRET_ID,
                # An api_key value here must never be rendered even if present.
                "api_key": "SG.must-not-render",
            }
        ),
        engine_image=PINNED_ENGINE_DIGEST,
    )

    assert "SG.must-not-render" not in rendered
    for key in ("EMAIL_API_KEY", "SENDGRID_API_KEY", "MAILGUN_API_KEY"):
        assert f"{key}=" not in rendered


@pytest.mark.parametrize(
    ("email_config", "expected_missing"),
    [
        # no secret id
        ({"backend": SENDGRID_BACKEND, "from_email": "noreply@shifter.example.test"}, "api_key_secret_id"),
        # no backend
        ({"api_key_secret_id": EMAIL_SECRET_ID, "from_email": "noreply@shifter.example.test"}, "backend"),
        # enabled SendGrid without a From address -> would send as webmaster@localhost
        ({"backend": SENDGRID_BACKEND, "api_key_secret_id": EMAIL_SECRET_ID}, "from_email"),
        # enabled Mailgun without its required sender domain
        (
            {
                "backend": MAILGUN_BACKEND,
                "from_email": "noreply@shifter.example.test",
                "api_key_secret_id": EMAIL_SECRET_ID,
            },
            "sender_domain",
        ),
    ],
)
def test_render_env_fails_closed_on_incomplete_email(email_config, expected_missing):
    """An enabled email_config that cannot actually send (missing backend, secret
    id, From address, or — for Mailgun — sender domain) fails at render time
    rather than silently dropping mail or sending as webmaster@localhost."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    with pytest.raises(ValueError, match=expected_missing):
        module.render_env(_outputs(email_config=email_config), engine_image=PINNED_ENGINE_DIGEST)


def test_render_env_preserves_bootstrap_admin_lists_from_environment(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_STAFF_EMAILS", "admin@example.com")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", "admin@example.com")

    rendered = module.render_env(_outputs(), engine_image=PINNED_ENGINE_DIGEST)

    assert "PLATFORM_BOOTSTRAP_STAFF_EMAILS=admin@example.com\n" in rendered
    assert "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=admin@example.com\n" in rendered
