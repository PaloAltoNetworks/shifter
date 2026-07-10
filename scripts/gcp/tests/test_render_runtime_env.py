"""Tests for the GCP runtime env renderer."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PINNED_IMAGE_TAG = "abc1234"


def _load_module_from_path(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_module(module_filename: str, module_name: str):
    return _load_module_from_path(Path(__file__).resolve().parents[1] / module_filename, module_name)


runtime_inventory = _load_module_from_path(
    REPO_ROOT / "shifter/installation/runtime_inventory.py",
    "installation_runtime_inventory_for_gcp_tests",
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
        "GCP_RANGE_PLANE": "compute-engine",
        "GCP_RANGE_CELL_NETWORK_MODE": "vpc-per-range",
        "RANGE_NETWORK_ZONE": "us-central1-b",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@example.iam.gserviceaccount.com",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES": "https://www.googleapis.com/auth/cloud-platform",
        "GCP_RANGE_LINUX_IMAGE": "projects/debian-cloud/global/images/family/debian-12",
        "GCP_RANGE_LINUX_MACHINE_TYPE": "e2-small",
        "GCP_RANGE_LINUX_DISK_SIZE_GB": "20",
        "GCP_RANGE_LINUX_DISK_TYPE": "pd-balanced",
        "GCP_RANGE_KALI_IMAGE": "projects/kali/global/images/kali",
        "GCP_RANGE_KALI_MACHINE_TYPE": "e2-standard-2",
        "GCP_RANGE_KALI_DISK_SIZE_GB": "40",
        "GCP_RANGE_KALI_DISK_TYPE": "pd-balanced",
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
        "GCP_RANGE_VERTEX_PROJECT_ID": "shifter-gcp-dev",
        "GCP_RANGE_VERTEX_REGION": "us-east5",
        "GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL": "range-vertex@shifter-gcp-dev.iam.gserviceaccount.com",
        "GCP_RANGE_KALI_ANTHROPIC_MODEL": "claude-sonnet-4-6",
        "GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL": "claude-haiku-4-5",
        "POLARIS_TESTS_BUCKET": "shifter-gcp-dev-polaris-tests",
        "POLARIS_TESTS_KEY": "polaris/tests/polaris-tests.tar.gz",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _outputs(
    *,
    public_hostname: str = "portal.example.test",
    managed_tls_enabled: bool = True,
    identity_allowed_email_domain: str = "paloaltonetworks.com",
    identity_allowed_emails: list[str] | None = None,
    email_config: dict | None = None,
) -> dict[str, object]:
    outputs = {
        "assets_bucket_name": {"value": "shifter-gcp-dev-gcp-dev-assets"},
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
    if email_config is not None:
        outputs["email_config"] = {"value": email_config}
    return outputs


def test_render_env_emits_production_security_profile():
    """The GCP runtime is always production-secure and addressed via https://<hostname>."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)

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
    assert "IDENTITY_PLATFORM_PROJECT_ID=shifter-gcp-dev\n" in rendered
    assert "IDENTITY_PLATFORM_AUTH_DOMAIN=shifter-gcp-dev.firebaseapp.com\n" in rendered
    assert "GDC_ACCESS_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-gdc-access\n" in rendered
    assert "RANGE_NETWORK_ID=projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range\n" in rendered
    assert "RANGE_NETWORK_CIDR=10.50.0.0/16\n" in rendered
    assert "RANGE_NETWORK_REGION=us-central1\n" in rendered
    assert "PORTAL_NETWORK_CIDRS=10.40.0.0/20,10.44.0.0/16\n" in rendered
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
        "shifter-gcp-dev/shifter-gcp-dev-pulumi-provisioner/pulumi-provisioner:abc1234\n"
    ) in rendered


def test_render_env_keys_match_runtime_inventory(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    assert _rendered_keys(module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)) == set(
        GCP_GENERATED_RUNTIME_ENV_KEYS
    )

    monkeypatch.setenv("PLATFORM_BOOTSTRAP_STAFF_EMAILS", "admin@example.com")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", "admin@example.com")
    _seed_gce_range_env(monkeypatch)
    rendered = module.render_env(
        _outputs(
            identity_allowed_emails=["alice@example.com", "bob@example.com"],
            email_config=_FULL_MAILGUN_EMAIL_CONFIG,
        ),
        image_tag=PINNED_IMAGE_TAG,
    )

    assert _rendered_keys(rendered) == set(GCP_GENERATED_RUNTIME_ENV_KEYS | GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS)


def test_render_env_forwards_gce_range_cell_contract(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    _seed_gce_range_env(monkeypatch)

    rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)

    assert "GCP_RANGE_BACKEND=gce\n" in rendered
    assert "GCP_RANGE_CELL_NETWORK_MODE=vpc-per-range\n" in rendered
    assert "RANGE_NETWORK_ZONE=us-central1-b\n" in rendered
    assert "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL=range-host@example.iam.gserviceaccount.com\n" in rendered
    assert "GCP_RANGE_LINUX_IMAGE=projects/debian-cloud/global/images/family/debian-12\n" in rendered
    assert "GCP_RANGE_EGRESS_ALLOW_CIDRS=10.60.0.0/16\n" in rendered


def test_render_env_still_supports_gdc_backend_override(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gdc")

    rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)

    assert "GCP_RANGE_BACKEND=gdc\n" in rendered


def test_render_env_cell_project_id_env_override_wins(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("GCP_RANGE_CELL_PROJECT_ID", "prod-real-project")

    rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)

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
            "--image-tag",
            PINNED_IMAGE_TAG,
            "--output",
            str(output_path),
        ],
    )

    assert module.main() == 0

    assert output_path.read_text() == module.render_env(outputs, image_tag=PINNED_IMAGE_TAG)


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
        module.render_env(_outputs(**missing_kwargs), image_tag=PINNED_IMAGE_TAG)


@pytest.mark.parametrize("image_tag", ["", "  ", "latest"])
def test_render_env_rejects_missing_or_moving_image_tags(image_tag):
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    with pytest.raises(ValueError, match="image_tag"):
        module.render_env(_outputs(), image_tag=image_tag)


def test_render_env_renders_identity_allow_list_from_terraform_outputs():
    """IDENTITY_ALLOWED_EMAIL_DOMAIN / IDENTITY_ALLOWED_EMAILS come from Terraform outputs, not literals/env."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    default_rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)
    assert "IDENTITY_ALLOWED_EMAIL_DOMAIN=paloaltonetworks.com\n" in default_rendered
    assert "IDENTITY_ALLOWED_EMAILS=" not in default_rendered  # empty list -> no key

    custom_rendered = module.render_env(
        _outputs(
            identity_allowed_email_domain="contractors.example.com",
            identity_allowed_emails=["alice@partner.test", "bob@partner.test"],
        ),
        image_tag=PINNED_IMAGE_TAG,
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

    rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)

    assert "REDIS_HOST=10.0.0.20\n" in rendered
    assert "REDIS_PORT=6379\n" in rendered
    assert "REDIS_TLS=true\n" in rendered
    assert "REDIS_SECRET_ID=projects/shifter-gcp-dev/secrets/shifter-gcp-dev-redis\n" in rendered


def test_render_env_never_emits_redis_password_or_url():
    """Structural secret-leakage gate: the runtime env contract is ConfigMap-bound,
    so it must never carry the Redis AUTH token. The token flows through Secret
    Manager + entrypoint hydration only (ADR-008-R6, #963)."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)

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
        module.render_env(outputs, image_tag=PINNED_IMAGE_TAG)


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
        module.render_env(outputs, image_tag=PINNED_IMAGE_TAG)


def test_render_env_emits_console_backend_when_email_unconfigured():
    """Email is optional, but the runtime backend choice is explicit."""
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)

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
        image_tag=PINNED_IMAGE_TAG,
    )

    assert f"EMAIL_BACKEND={SENDGRID_BACKEND}\n" in rendered
    assert "DEFAULT_FROM_EMAIL=noreply@shifter.example.test\n" in rendered
    assert f"EMAIL_API_KEY_SECRET_ID={EMAIL_SECRET_ID}\n" in rendered
    assert "MAILGUN_SENDER_DOMAIN=" not in rendered


def test_render_env_emits_mailgun_sender_domain():
    module = _load_module("render_runtime_env.py", "render_runtime_env")

    rendered = module.render_env(_outputs(email_config=_FULL_MAILGUN_EMAIL_CONFIG), image_tag=PINNED_IMAGE_TAG)

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
        image_tag=PINNED_IMAGE_TAG,
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
        module.render_env(_outputs(email_config=email_config), image_tag=PINNED_IMAGE_TAG)


def test_render_env_preserves_bootstrap_admin_lists_from_environment(monkeypatch):
    module = _load_module("render_runtime_env.py", "render_runtime_env")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_STAFF_EMAILS", "admin@example.com")
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", "admin@example.com")

    rendered = module.render_env(_outputs(), image_tag=PINNED_IMAGE_TAG)

    assert "PLATFORM_BOOTSTRAP_STAFF_EMAILS=admin@example.com\n" in rendered
    assert "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=admin@example.com\n" in rendered
