"""Inventory and validate repo runtime configuration surfaces.

The root installation config (``shifter.yaml``) remains the public
operator-authored contract.  This module records the checked-in runtime
configuration files that still bridge that contract into provider-specific
runtime env files, and validates their key-level shape without ever reading or
printing values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_ENV_KEY_RE = re.compile(r"^([A-Za-z_]\w*)=", re.ASCII)

GCP_STATIC_RUNTIME_ENV_PATH = Path("platform/k8s/gcp/overlays/gcp-dev/platform-runtime.env")
GCP_GENERATED_RUNTIME_ENV_PATH = Path("platform/k8s/gcp/overlays/gcp-dev/platform-runtime.generated.env")
GCP_SECRET_RUNTIME_ENV_PATH = Path("platform/k8s/gcp/overlays/gcp-dev/platform-runtime-secrets.env")
GCP_BACKEND_OWNER = "gcp backend"

GCP_GENERATED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "APP_SECRET_ID",
        "AGENT_STORAGE_BUCKET",
        "AUTH_PROVIDER",
        # Renderer-owned selected-backend identity (PLAT-2005): the GCP backend
        # runtime-env renderer (scripts/gcp/render_runtime_env.py) IS this backend's
        # identity source, so CLOUD_PROVIDER is generated, not a static overlay literal.
        "CLOUD_PROJECT_ID",
        "CLOUD_PROVIDER",
        "CSRF_COOKIE_SECURE",
        "DB_HOST",
        "DB_NAME",
        "DB_PORT",
        "DB_SECRET_ID",
        "DB_USER",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DJANGO_DEBUG",
        "DC_DOMAIN_PASSWORD_SECRET_ID",
        "EMAIL_BACKEND",
        "ENGINE_TASK_IMAGE",
        "GDC_ACCESS_SECRET_ID",
        "GDC_NETWORK_DNS_NAMESERVERS",
        "GDC_NETWORK_INTERFACE",
        "GDC_RANGE_NAMESPACE_PREFIX",
        "GDC_STATIC_IP_RESERVATION_COUNT",
        "GCP_PROJECT_ID",
        "GCP_RANGE_BACKEND",
        "GCP_RANGE_CELL_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "GUACAMOLE_API_BASE_URL",
        "GUACAMOLE_BASE_URL",
        "GUACAMOLE_POSTGRESQL_DATABASE",
        "GUACAMOLE_POSTGRESQL_HOSTNAME",
        "GUACAMOLE_POSTGRESQL_PORT",
        "GUACAMOLE_SECRET_ID",
        "IDENTITY_ALLOWED_EMAIL_DOMAIN",
        "IDENTITY_PLATFORM_API_KEY",
        "IDENTITY_PLATFORM_AUTH_DOMAIN",
        "IDENTITY_PLATFORM_ISSUER",
        "IDENTITY_PLATFORM_PROJECT_ID",
        "IDENTITY_PLATFORM_TOTP_DISPLAY_NAME",
        "PORTAL_NETWORK_CIDRS",
        "QUEUE_CMS_CONSUMER_ID",
        "QUEUE_CMS_PUBLISHER_ID",
        "QUEUE_ENGINE_CONSUMER_ID",
        "QUEUE_ENGINE_PUBLISHER_ID",
        "QUEUE_MC_CONSUMER_ID",
        "QUEUE_MC_PUBLISHER_ID",
        "RANGE_EVENTS_TOPIC_ID",
        "RANGE_NETWORK_CIDR",
        "RANGE_NETWORK_ID",
        "RANGE_NETWORK_REGION",
        "RANGE_VPC_CIDR",
        "RANGE_VPC_ID",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_SECRET_ID",
        "REDIS_TLS",
        "SESSION_COOKIE_SECURE",
        "SITE_URL",
        "STORAGE_BUCKET_NAME",
        "TF_STATE_BUCKET",
    }
)

GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "IDENTITY_ALLOWED_EMAILS",
        "PLATFORM_BOOTSTRAP_STAFF_EMAILS",
        "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS",
        # Transactional email (PLAT-002, #671) — emitted only when the operator
        # configures a SendGrid/Mailgun sender. EMAIL_BACKEND is always explicit
        # in generated runtime env; these are the extra sender-specific keys.
        # EMAIL_API_KEY_SECRET_ID is a Secret Manager reference, not the key
        # value. MAILGUN_SENDER_DOMAIN is emitted only for the Mailgun backend.
        "DEFAULT_FROM_EMAIL",
        "EMAIL_API_KEY_SECRET_ID",
        "GCP_RANGE_CELL_NETWORK_MODE",
        "GCP_RANGE_DC_DISK_SIZE_GB",
        "GCP_RANGE_DC_DISK_TYPE",
        "GCP_RANGE_DC_IMAGE",
        "GCP_RANGE_DC_MACHINE_TYPE",
        "GCP_RANGE_EGRESS_ALLOW_CIDRS",
        "GCP_RANGE_HOST_MGMT_SSH_PORT",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
        "GCP_RANGE_KALI_ANTHROPIC_MODEL",
        "GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL",
        "GCP_RANGE_KALI_DISK_SIZE_GB",
        "GCP_RANGE_KALI_DISK_TYPE",
        "GCP_RANGE_KALI_IMAGE",
        "GCP_RANGE_IMAGE_KEY_PROFILES_JSON",
        "GCP_RANGE_KALI_MACHINE_TYPE",
        "GCP_RANGE_LINUX_DISK_SIZE_GB",
        "GCP_RANGE_LINUX_DISK_TYPE",
        "GCP_RANGE_LINUX_IMAGE",
        "GCP_RANGE_LINUX_MACHINE_TYPE",
        "GCP_RANGE_PLANE",
        "GCP_RANGE_PRIVATE_GOOGLE_ACCESS",
        "GCP_RANGE_VERTEX_PROJECT_ID",
        "GCP_RANGE_VERTEX_REGION",
        "GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_WINDOWS_DISK_SIZE_GB",
        "GCP_RANGE_WINDOWS_DISK_TYPE",
        "GCP_RANGE_WINDOWS_IMAGE",
        "GCP_RANGE_WINDOWS_MACHINE_TYPE",
        "MAILGUN_SENDER_DOMAIN",
        "POLARIS_TESTS_BUCKET",
        "POLARIS_TESTS_KEY",
        "RANGE_NETWORK_ZONE",
    }
)

GCP_SECRET_RUNTIME_ENV_KEYS: frozenset[str] = frozenset()

# The generated runtime-env keys the standalone provisioner Job additionally receives
# (beyond the portal/worker platform image, which loads the whole generated env file).
# This is the subset of the generated GCP key set that the platform task runner forwards
# to the provisioner — it mirrors ``engine.ecs._GCP_PROVISIONER_ENV_KEYS`` intersected with
# the generated keys above. The installation package is standalone (it must not import the
# Django platform), so the set is declared here as data; a platform-side parity test
# (``tests/shared/cloud/test_gcp_runtime_role_parity.py``) fails if it drifts from the
# authoritative forwarding list. The backend bundle's generated-output ``process_roles``
# are derived from this set (portal/worker for every key, plus provisioner for these, plus
# range-task for the ``GCP_RANGE_*`` guest-configuration keys among them).
GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "AGENT_STORAGE_BUCKET",
        "CLOUD_PROJECT_ID",
        "CLOUD_PROVIDER",
        "DB_HOST",
        "DB_NAME",
        "DB_PORT",
        "DB_USER",
        "ENGINE_TASK_IMAGE",
        "GCP_PROJECT_ID",
        "GCP_RANGE_BACKEND",
        "GCP_RANGE_CELL_NETWORK_MODE",
        "GCP_RANGE_DC_DISK_SIZE_GB",
        "GCP_RANGE_DC_DISK_TYPE",
        "GCP_RANGE_DC_IMAGE",
        "GCP_RANGE_DC_MACHINE_TYPE",
        "GCP_RANGE_EGRESS_ALLOW_CIDRS",
        "GCP_RANGE_HOST_MGMT_SSH_PORT",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
        "GCP_RANGE_KALI_ANTHROPIC_MODEL",
        "GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL",
        "GCP_RANGE_KALI_DISK_SIZE_GB",
        "GCP_RANGE_KALI_DISK_TYPE",
        "GCP_RANGE_KALI_IMAGE",
        "GCP_RANGE_IMAGE_KEY_PROFILES_JSON",
        "GCP_RANGE_KALI_MACHINE_TYPE",
        "GCP_RANGE_LINUX_DISK_SIZE_GB",
        "GCP_RANGE_LINUX_DISK_TYPE",
        "GCP_RANGE_LINUX_IMAGE",
        "GCP_RANGE_LINUX_MACHINE_TYPE",
        "GCP_RANGE_PLANE",
        "GCP_RANGE_PRIVATE_GOOGLE_ACCESS",
        "GCP_RANGE_VERTEX_PROJECT_ID",
        "GCP_RANGE_VERTEX_REGION",
        "GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_WINDOWS_DISK_SIZE_GB",
        "GCP_RANGE_WINDOWS_DISK_TYPE",
        "GCP_RANGE_WINDOWS_IMAGE",
        "GCP_RANGE_WINDOWS_MACHINE_TYPE",
        "GDC_ACCESS_SECRET_ID",
        "GDC_NETWORK_DNS_NAMESERVERS",
        "GDC_NETWORK_INTERFACE",
        "GDC_RANGE_NAMESPACE_PREFIX",
        "GDC_STATIC_IP_RESERVATION_COUNT",
        "GOOGLE_CLOUD_PROJECT",
        "POLARIS_TESTS_BUCKET",
        "POLARIS_TESTS_KEY",
        "PORTAL_NETWORK_CIDRS",
        "RANGE_EVENTS_TOPIC_ID",
        "RANGE_NETWORK_CIDR",
        "RANGE_NETWORK_ID",
        "RANGE_NETWORK_REGION",
        "RANGE_NETWORK_ZONE",
        "RANGE_VPC_CIDR",
        "RANGE_VPC_ID",
        "STORAGE_BUCKET_NAME",
    }
)


@dataclass(frozen=True)
class RuntimeSurface:
    """A checked-in or operator-local runtime configuration surface."""

    path: str
    owner: str
    authority: str
    notes: str


@dataclass(frozen=True)
class RuntimeInventoryIssue:
    """A sanitized inventory validation problem.

    ``message`` must mention only file paths and env-key names, never values.
    """

    path: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.message}"


RUNTIME_SURFACES: tuple[RuntimeSurface, ...] = (
    RuntimeSurface(
        path="shifter.yaml",
        owner="installation",
        authority="operator-authored root installation config",
        notes="Public backend/deployment/settings contract; validated by shifter-config validate.",
    ),
    RuntimeSurface(
        path=".shifter.yaml",
        owner="mcp/ops",
        authority="checked-in MCP ops policy namespace",
        notes="Per-tool policy for the shifter-ops MCP server, not deployment secret storage.",
    ),
    RuntimeSurface(
        path=str(GCP_STATIC_RUNTIME_ENV_PATH),
        owner=GCP_BACKEND_OWNER,
        authority="checked-in static GCP runtime env",
        notes="Non-secret env keys that are stable for the gcp-dev overlay.",
    ),
    RuntimeSurface(
        path=str(GCP_GENERATED_RUNTIME_ENV_PATH),
        owner=GCP_BACKEND_OWNER,
        authority="comment-only generated GCP runtime env stub",
        notes="Tracked stub stays assignment-free; required keys are rendered from Terraform outputs at deploy time.",
    ),
    RuntimeSurface(
        path=str(GCP_SECRET_RUNTIME_ENV_PATH),
        owner=GCP_BACKEND_OWNER,
        authority="synthetic secret env placeholder",
        notes="Must not contain real assignments in source control.",
    ),
    RuntimeSurface(
        path=".env",
        owner="local operator",
        authority="gitignored local environment",
        notes="Local-only workstation values and secret references; never part of the checked-in runtime contract.",
    ),
    RuntimeSurface(
        path="shifter/shifter_platform/.env",
        owner="local developer",
        authority="gitignored local platform environment",
        notes="Local-only Django/compose values and secrets; use .env.example for checked-in shape.",
    ),
)


def _repo_path(repo_root: Path, relative_path: Path) -> Path:
    """Resolve a repo-relative runtime inventory path."""

    return repo_root / relative_path


def env_keys_from_file(path: Path) -> tuple[str, ...]:
    """Return assignment keys from an env file without exposing assignment values."""

    keys: list[str] = []
    # Normalize the path (collapsing any `..` traversal) before reading so the
    # bytes scanned come from the resolved target rather than the raw input.
    resolved = path.resolve()
    for line in resolved.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_KEY_RE.match(stripped)
        if match is not None:
            keys.append(match.group(1))
    return tuple(keys)


def _duplicate_key_issues(path: Path, keys: tuple[str, ...]) -> list[RuntimeInventoryIssue]:
    """Return sanitized issues for duplicate env assignment keys."""

    seen: set[str] = set()
    duplicates: set[str] = set()
    for key in keys:
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if not duplicates:
        return []
    return [
        RuntimeInventoryIssue(
            str(path),
            "duplicate env keys: " + ", ".join(sorted(duplicates)),
        )
    ]


def _missing_file_issue(path: Path) -> RuntimeInventoryIssue:
    """Return a sanitized issue for a missing runtime inventory file."""

    return RuntimeInventoryIssue(str(path), "required runtime inventory file is missing")


def _generated_stub_assignment_issues(path: Path, keys: tuple[str, ...]) -> list[RuntimeInventoryIssue]:
    """Return issues when the checked-in generated runtime stub has assignments."""

    if not keys:
        return []
    return [
        RuntimeInventoryIssue(
            str(path),
            "checked-in generated runtime stub must be comment-only; assignments found for env keys: "
            + ", ".join(sorted(set(keys))),
        )
    ]


def _set_delta_issues(
    *,
    path: Path,
    actual: set[str],
    required: frozenset[str],
    allowed_extra: frozenset[str] = frozenset(),
) -> list[RuntimeInventoryIssue]:
    """Return sanitized issues for missing and unregistered env keys."""

    issues: list[RuntimeInventoryIssue] = []
    missing = sorted(required - actual)
    extra = sorted(actual - required - allowed_extra)
    if missing:
        issues.append(RuntimeInventoryIssue(str(path), "missing env keys: " + ", ".join(missing)))
    if extra:
        issues.append(RuntimeInventoryIssue(str(path), "unregistered env keys: " + ", ".join(extra)))
    return issues


def validate_runtime_inventory(repo_root: str | Path) -> list[RuntimeInventoryIssue]:
    """Validate checked-in runtime env surfaces by path and key name only."""

    root = Path(repo_root)
    generated_path = _repo_path(root, GCP_GENERATED_RUNTIME_ENV_PATH)
    static_path = _repo_path(root, GCP_STATIC_RUNTIME_ENV_PATH)
    secret_path = _repo_path(root, GCP_SECRET_RUNTIME_ENV_PATH)
    issues: list[RuntimeInventoryIssue] = []

    for path in (generated_path, static_path, secret_path):
        if not path.is_file():
            issues.append(_missing_file_issue(path))
    if issues:
        return issues

    generated_keys = env_keys_from_file(generated_path)
    static_keys = env_keys_from_file(static_path)
    secret_keys = env_keys_from_file(secret_path)

    issues.extend(_duplicate_key_issues(generated_path, generated_keys))
    issues.extend(_duplicate_key_issues(static_path, static_keys))
    issues.extend(_duplicate_key_issues(secret_path, secret_keys))

    issues.extend(_generated_stub_assignment_issues(generated_path, generated_keys))
    issues.extend(
        _set_delta_issues(
            path=secret_path,
            actual=set(secret_keys),
            required=GCP_SECRET_RUNTIME_ENV_KEYS,
        )
    )

    overlap = sorted(GCP_GENERATED_RUNTIME_ENV_KEYS & set(static_keys))
    if overlap:
        issues.append(
            RuntimeInventoryIssue(
                str(GCP_GENERATED_RUNTIME_ENV_PATH),
                f"renderer-owned env keys duplicate keys from {GCP_STATIC_RUNTIME_ENV_PATH}: " + ", ".join(overlap),
            )
        )
    return issues
