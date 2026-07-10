"""GCP control-plane Terraform, Helm, identity, and runtime bootstrap operations."""

import importlib.util
import ipaddress
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from bootstrap_core import (
    _GDC_APISERVER_BACKEND_PORT,
    _GDC_SCENARIO_POD_KALI_IMAGE,
    _GKE_WORKLOAD_IDENTITY_ANNOTATION,
    _UNKNOWN_ERROR,
    GCP_TERRAFORM_BOOTSTRAP_BUCKET_ROLE,
    GCP_TERRAFORM_BOOTSTRAP_ROLES,
    Colors,
    GDCBootstrapConfig,
    _sample_guest_access_defaults,
    code_block,
    confirm,
    error,
    gcloud_resource_exists,
    get_repo_root,
    header,
    info,
    prompt_required_value,
    run_cmd,
    subheader,
    success,
    validate_gcp_control_plane_security_inputs,
    wait_for_user,
    warn,
)
from gdc_cluster import (
    add_project_iam_binding_with_retry,
    ensure_gdc_apis,
    ensure_gdc_instances,
    ensure_gdc_network,
    ensure_gdc_service_account,
    run_gdc_workstation_script,
    stage_gdc_bootstrap_assets,
    sync_gdc_access_secret,
    sync_gdc_instance_ssh_metadata,
    sync_gdc_vm_image_secret,
    upload_gdc_assets,
    wait_for_gdc_ssh,
)

_GUACAMOLE_RUNTIME_RESOURCE_NAME = "guacamole-runtime"
_K8S_PART_OF_LABEL = "app.kubernetes.io/part-of"


def _load_python_script_module(script_path: Path, module_name: str) -> ModuleType:
    """Load a local Python script as a module without changing repo packaging."""
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Python module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_output_value(outputs: dict[str, dict[str, object]], key: str) -> object:
    """Return the Terraform output value for a key or raise a clear error."""
    try:
        return outputs[key]["value"]
    except KeyError as exc:
        raise KeyError(f"Missing Terraform output: {key}") from exc


def _get_string_mapping_output(outputs: dict[str, dict[str, object]], key: str) -> dict[str, str]:
    """Return a Terraform output value as a string mapping."""
    value = _get_output_value(outputs, key)
    if not isinstance(value, dict):
        raise TypeError(f"Terraform output {key} must be a mapping")
    return {str(item_key): str(item_value) for item_key, item_value in value.items()}


def _merge_csv_env_values(*groups: list[str]) -> str:
    """Merge comma-separated values while preserving order and uniqueness."""
    ordered: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw_value in group:
            for part in raw_value.split(","):
                value = part.strip().lower()
                if not value or value in seen:
                    continue
                seen.add(value)
                ordered.append(value)
    return ",".join(ordered)


def _unique_nonempty_strings(values: list[str | None]) -> list[str]:
    """Return non-empty strings in first-seen order."""
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = (raw_value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _host_as_single_address_cidr(value: object) -> str | None:
    """Convert a Terraform host/IP output into a /32 or /128 CIDR."""
    if value is None:
        return None
    host = str(value).strip()
    if not host:
        return None
    if "/" in host:
        return host
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(f"Expected IP address Terraform output, got {host!r}") from exc
    prefix = 32 if address.version == 4 else 128
    return f"{address}/{prefix}"


def render_gcp_platform_runtime_env(
    config: GDCBootstrapConfig,
    *,
    bootstrap_operator_email: str | None = None,
) -> str:
    """Render the static, project-aware runtime env contract for the GKE control plane."""
    gdc_vm_image_secret = f"projects/{config.project_id}/secrets/{config.gdc_vm_image_gcs_secret_id}"
    bootstrap_values = load_bootstrap_env_values()
    bootstrap_staff_emails = _merge_csv_env_values(
        [bootstrap_values.get("PLATFORM_BOOTSTRAP_STAFF_EMAILS", "")],
        [bootstrap_operator_email or ""],
    )
    bootstrap_superuser_emails = _merge_csv_env_values(
        [bootstrap_values.get("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", "")],
        [bootstrap_operator_email or ""],
    )
    lines = [
        "CLOUD_PROVIDER=gcp",
        f"ENVIRONMENT={config.environment}",
        f"CLOUD_REGION={config.region}",
        f"GCP_REGION={config.region}",
        f"GCP_PROJECT_ID={config.project_id}",
        f"GOOGLE_CLOUD_PROJECT={config.project_id}",
        # GCE range cells are the default GCP range backend; the GDC VM Runtime
        # block below is retained and re-selected with GCP_RANGE_BACKEND=gdc.
        "GCP_RANGE_BACKEND=gce",
        "ENGINE_TASK_NAMESPACE=shifter-jobs",
        "ENGINE_TASK_SERVICE_ACCOUNT_NAME=provisioner",
        "ENGINE_TASK_IMAGE_PULL_POLICY=Always",
        "GDC_VM_STORAGE_CLASS=local-shared",
        f"GDC_VM_IMAGE_GCS_SECRET_ID={gdc_vm_image_secret}",
        "# Palo Alto VM-Series on GDC VM Runtime. These are required before creating",
        "# a GCP/GDC NGFW; values are intentionally explicit because this is not a",
        "# generic firewall path.",
        "GDC_VMSERIES_IMAGE_URL=",
        "GDC_VMSERIES_BOOTSTRAP_BUCKET=",
        "GDC_VMSERIES_STORAGE_CLASS=local-shared",
        f"GDC_VMSERIES_IMAGE_GCS_SECRET_ID={gdc_vm_image_secret}",
        "GDC_VMSERIES_NAMESPACE_PREFIX=ngfw",
        "GDC_VMSERIES_MGMT_NETWORK_NAME=pod-network",
        "GDC_VMSERIES_MGMT_IP_CIDR=",
        "GDC_VMSERIES_DATA_NETWORK_NAME=",
        "GDC_VMSERIES_DATA_IP_CIDR=",
        "GDC_VMSERIES_ROUTE_NEXT_HOP_IP=",
        "GDC_VMSERIES_VCPUS=4",
        "GDC_VMSERIES_MEMORY=8Gi",
        "GDC_VMSERIES_DISK_SIZE_GIB=81",
        "GDC_VMSERIES_BOOTSTRAP_DISK_SIZE_GIB=1",
        "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID=",
        "# Guest access defaults for VM Runtime assets.",
        *_sample_guest_access_defaults(),
        "# VM Runtime boot images, exported by the packer-gcp pipeline to the GDC",
        "# VM image bucket. DISK_SIZE_GIB must be >= the exported qcow2 virtual",
        "# size (the GCE builder disk size): ubuntu 20, kali 40, windows/dc 64.",
        f"GDC_KALI_IMAGE_URL={config.gdc_vm_image_url('kali')}",
        "GDC_KALI_VCPUS=2",
        "GDC_KALI_MEMORY=4Gi",
        "GDC_KALI_DISK_SIZE_GIB=40",
        f"GDC_UBUNTU_IMAGE_URL={config.gdc_vm_image_url('ubuntu')}",
        "GDC_UBUNTU_VCPUS=1",
        "GDC_UBUNTU_MEMORY=2Gi",
        "GDC_UBUNTU_DISK_SIZE_GIB=20",
        f"GDC_WINDOWS_IMAGE_URL={config.gdc_vm_image_url('windows')}",
        "GDC_WINDOWS_VCPUS=2",
        "GDC_WINDOWS_MEMORY=8Gi",
        "GDC_WINDOWS_DISK_SIZE_GIB=64",
        f"GDC_DC_IMAGE_URL={config.gdc_vm_image_url('dc')}",
        "GDC_DC_VCPUS=2",
        "GDC_DC_MEMORY=8Gi",
        "GDC_DC_DISK_SIZE_GIB=64",
        "# Optional overrides for lower-fidelity in-range scenario Pods.",
        "GDC_SCENARIO_POD_IMAGE_PULL_POLICY=IfNotPresent",
        f"GDC_SCENARIO_POD_KALI_IMAGE={_GDC_SCENARIO_POD_KALI_IMAGE}",
        "GDC_SCENARIO_POD_UBUNTU_IMAGE=docker.io/library/ubuntu:24.04",
        f"PLATFORM_BOOTSTRAP_STAFF_EMAILS={bootstrap_staff_emails}",
        f"PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS={bootstrap_superuser_emails}",
    ]
    return "".join(f"{line}\n" for line in lines)


def parse_env_contract(rendered: str) -> dict[str, str]:
    """Parse KEY=VALUE env contract text into a mapping, ignoring blank lines and comments."""
    values: dict[str, str] = {}
    for raw_line in rendered.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"Invalid env contract line: {raw_line!r}")
        values[key] = value
    return values


def validate_image_tag(image_tag: str) -> str:
    """Return a non-moving image tag suitable for deployment manifests."""
    tag = image_tag.strip()
    if not tag:
        raise ValueError("image tag must be non-empty")
    if tag == "latest":
        raise ValueError("image tag must be immutable; refusing to use latest")
    return tag


def resolve_gcp_control_plane_image_tag() -> str:
    """Resolve the immutable tag used for all GCP control-plane images."""
    env_tag = os.environ.get("SHIFTER_IMAGE_TAG", "").strip()
    if env_tag:
        return validate_image_tag(env_tag)

    github_sha = os.environ.get("GITHUB_SHA", "").strip()
    if github_sha:
        return validate_image_tag(github_sha[:7])

    result = run_cmd(
        ["git", "-C", str(get_repo_root()), "rev-parse", "--short=7", "HEAD"],
        check=False,
        capture=True,
    )
    if result is None:
        raise RuntimeError("Unable to resolve image tag from git")
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else _UNKNOWN_ERROR
        raise RuntimeError(f"Unable to resolve image tag from git: {stderr}")
    return validate_image_tag(result.stdout.strip())


def parse_simple_env_file(path: Path) -> dict[str, str]:
    """Parse a basic KEY=VALUE env file into a mapping."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed_value = value.strip()
        if len(parsed_value) >= 2 and parsed_value[0] == parsed_value[-1] and parsed_value[0] in {"'", '"'}:
            parsed_value = parsed_value[1:-1]
        values[key.strip()] = parsed_value
    return values


def load_bootstrap_env_values() -> dict[str, str]:
    """Load bootstrap values from repo-local env files, then overlay the process environment."""
    repo_root = get_repo_root()
    values: dict[str, str] = {}
    for env_path in [repo_root / ".env", repo_root.parent / "shifter" / ".env"]:
        values.update(parse_simple_env_file(env_path))
    values.update(os.environ)
    return values


def resolve_gcp_bootstrap_operator_credentials(env_values: dict[str, str] | None = None) -> tuple[str, str] | None:
    """Resolve the first operator email/password for the GCP identity bootstrap."""
    values = load_bootstrap_env_values() if env_values is None else env_values

    email = (
        values.get("GCP_BOOTSTRAP_ADMIN_EMAIL")
        or values.get("SHIFTER_BOOTSTRAP_ADMIN_EMAIL")
        or values.get("BOOTSTRAP_ADMIN_EMAIL")
    )
    password = (
        values.get("GCP_BOOTSTRAP_ADMIN_PASSWORD")
        or values.get("SHIFTER_BOOTSTRAP_ADMIN_PASSWORD")
        or values.get("BOOTSTRAP_ADMIN_PASSWORD")
    )
    if not email or not password:
        return None
    return email.strip().lower(), password.strip()


def prompt_for_gcp_bootstrap_operator_credentials() -> tuple[str, str]:
    """Collect the first GCP operator email/password interactively."""
    header("Configure GCP Operator Login")
    print(
        "Bootstrap will create the first corporate Shifter operator in Identity Platform.\n"
        "They will enroll TOTP MFA on first sign-in.\n"
    )

    email = prompt_required_value("Operator email").lower()
    password = prompt_required_value("Operator password", secret=True)
    return email, password


def _resolve_operator_email_domain(outputs: dict[str, dict[str, object]] | None) -> tuple[str, str]:
    """Resolve the required operator email domain and its source (Terraform output, else env)."""
    if outputs is not None:
        tf_value = outputs.get("identity_allowed_email_domain", {}).get("value")
        if isinstance(tf_value, str) and tf_value.strip():
            return tf_value.strip().lower(), "Terraform output identity_allowed_email_domain"
    env_value = os.environ.get("SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN", "").strip().lower()
    if env_value:
        return env_value, "SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN"
    return "", ""


def _validate_gcp_bootstrap_operator_email(
    email: str,
    outputs: dict[str, dict[str, object]] | None = None,
) -> None:
    """Validate the bootstrap operator email against the Identity Platform allow-list.

    The shape check (must contain a single `@`, non-empty local + domain parts)
    is always enforced. The domain restriction is derived, in order:

    1. The ``identity_allowed_email_domain`` Terraform output (when ``outputs``
       is supplied) — this is the same value the Identity Platform
       ``beforeCreate`` hook uses, so the bootstrap operator the bootstrap
       script writes into ``PLATFORM_BOOTSTRAP_*`` will actually be able to
       sign in to the deployed portal.
    2. The ``SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN`` environment variable as a
       fallback for callers that have not yet run Terraform (e.g., unit tests
       or dry-run flows). Unset means "accept any well-formed email" — only
       legitimate when no Identity Platform deployment is in scope.
    """
    if email.count("@") != 1:
        raise ValueError("GCP operator email must contain exactly one '@' character")
    local, _, domain = email.partition("@")
    if not local or not domain:
        raise ValueError("GCP operator email must have a non-empty local part and domain")

    required_domain, source = _resolve_operator_email_domain(outputs)

    if required_domain and not email.lower().endswith(f"@{required_domain}"):
        raise ValueError(
            f"GCP operator email must use the {required_domain} domain "
            f"(constraint from {source}). Bootstrap-time validation matches the "
            "Identity Platform allow-list, so an operator whose domain fails "
            "here cannot subsequently sign in to the deployed portal."
        )


def _gcp_identity_access_token() -> str:
    """Return a gcloud access token for Identity Platform admin calls."""
    result = subprocess.run(  # nosec B603 B607
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else _UNKNOWN_ERROR
        raise RuntimeError(f"Failed to acquire a GCP access token for Identity Platform: {stderr}")
    return result.stdout.strip()


def _gcp_identity_admin_request(
    *,
    config: GDCBootstrapConfig,
    outputs: dict[str, dict[str, object]],
    path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Call one validated Identity Platform admin endpoint."""
    del outputs
    access_token = _gcp_identity_access_token()
    url = f"https://identitytoolkit.googleapis.com/v1{path}"
    parsed_url = urllib_parse.urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "identitytoolkit.googleapis.com" or parsed_url.query:
        raise RuntimeError(f"Refusing to call unexpected Identity Platform endpoint: {url}")
    request = urllib_request.Request(  # noqa: S310 - URL is validated immediately above
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": config.project_id,
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=30) as response:  # nosec B310  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:  # pragma: no cover - exercised via unit tests with monkeypatch
        body = exc.read().decode("utf-8") if exc.fp is not None else ""
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        message = parsed.get("error", {}).get("message", exc.reason)
        raise RuntimeError(str(message)) from exc


def ensure_gcp_identity_platform_operator(
    config: GDCBootstrapConfig,
    outputs: dict[str, dict[str, object]],
    dry_run: bool = False,
) -> str | None:
    """Create the first GCP operator account if it does not already exist."""
    credentials = resolve_gcp_bootstrap_operator_credentials()
    if credentials is None:
        if dry_run:
            info("[DRY-RUN] Would prompt for the first GCP operator email and password")
            return None
        credentials = prompt_for_gcp_bootstrap_operator_credentials()

    email, password = credentials
    _validate_gcp_bootstrap_operator_email(email, outputs=outputs)

    if dry_run:
        info(f"[DRY-RUN] Would create or verify the Identity Platform operator account for {email}")
        return email

    try:
        _gcp_identity_admin_request(
            config=config,
            outputs=outputs,
            path=f"/projects/{config.project_id}/accounts",
            payload={
                "email": email,
                "password": password,
                "displayName": "Shifter Operator",
                "emailVerified": True,
            },
        )
        success(f"Created Identity Platform operator {email}")
        return email
    except RuntimeError as exc:
        if "EMAIL_EXISTS" in str(exc):
            info(f"Identity Platform operator {email} already exists")
            return email
        raise


def _render_gcp_runtime_env(
    config: GDCBootstrapConfig,
    outputs: dict[str, dict[str, object]],
    *,
    image_tag: str,
    bootstrap_operator_email: str | None,
) -> dict[str, str]:
    """Render and merge bootstrap-owned and platform-owned runtime env values."""
    runtime_renderer = _load_python_script_module(
        get_repo_root() / "scripts" / "gcp" / "render_runtime_env.py",
        "bootstrap_render_runtime_env",
    )
    return {
        **parse_env_contract(
            render_gcp_platform_runtime_env(config, bootstrap_operator_email=bootstrap_operator_email)
        ),
        **parse_env_contract(runtime_renderer.render_env(outputs, image_tag=image_tag)),
    }


def _gcp_private_service_cidrs(outputs: dict[str, dict[str, object]]) -> list[str]:
    """Return private-service CIDRs for Helm network policy values."""
    control_plane_database = _get_output_value(outputs, "control_plane_database")
    control_plane_cache = _get_output_value(outputs, "control_plane_cache")
    guacamole_database = _get_output_value(outputs, "guacamole_database")
    return _unique_nonempty_strings(
        [
            _host_as_single_address_cidr(control_plane_database.get("private_ip")),
            _host_as_single_address_cidr(control_plane_cache.get("host")),
            _host_as_single_address_cidr(guacamole_database.get("host")),
            str(_get_output_value(outputs, "gke_services_cidr")).strip(),
        ]
    )


def _helm_service_account_values(service_accounts: dict[str, str]) -> dict[str, object]:
    """Return workload-identity annotations for chart service accounts."""
    return {
        "portal": {"annotations": {_GKE_WORKLOAD_IDENTITY_ANNOTATION: service_accounts["portal"]}},
        "workers": {"annotations": {_GKE_WORKLOAD_IDENTITY_ANNOTATION: service_accounts["workers"]}},
        "ctfScheduler": {"annotations": {_GKE_WORKLOAD_IDENTITY_ANNOTATION: service_accounts["ctf-scheduler"]}},
        "provisioner": {"annotations": {_GKE_WORKLOAD_IDENTITY_ANNOTATION: service_accounts["provisioner"]}},
    }


def _helm_image_values(image_roots: dict[str, str], image_tag: str) -> dict[str, object]:
    """Return pinned image references for chart workloads."""
    return {
        "portal": {"repository": image_roots["portal"], "tag": image_tag, "pullPolicy": "Always"},
        "guacd": {"repository": image_roots["guacd"], "tag": image_tag, "pullPolicy": "Always"},
        "guacamoleClient": {
            "repository": image_roots["guacamole-client"],
            "tag": image_tag,
            "pullPolicy": "Always",
        },
    }


def _helm_ingress_values(
    outputs: dict[str, dict[str, object]],
    *,
    public_hostname: str,
    managed_tls_enabled: bool,
) -> dict[str, object]:
    """Return public ingress chart values."""
    return {
        "enabled": True,
        "class": "gce",
        "staticIpName": _get_output_value(outputs, "public_ingress_ip_name"),
        "host": public_hostname,
        "managedTls": {
            "enabled": managed_tls_enabled,
            "certificateName": "platform-managed-cert",
            "frontendConfigName": "platform-frontend-config",
        },
    }


def _helm_backend_config_values(edge_policy_name: str) -> dict[str, object]:
    """Return backend-config values for public services."""
    backend = {"enabled": True, "securityPolicyName": edge_policy_name}
    return {
        "portal": {"backendConfig": {**backend, "name": "portal-web"}},
        "guacamoleClient": {"backendConfig": {**backend, "name": "guacamole-client"}},
    }


def _helm_network_policy_values(
    private_service_cidrs: list[str],
    range_cluster_api_cidrs: list[str],
    range_cluster_api_port: int,
) -> dict[str, object]:
    """Return network-policy CIDR values for the Helm release."""
    return {
        "enabled": True,
        "gclbSourceRanges": [
            "35.191.0.0/16",  # NOSONAR - Google Cloud Load Balancer health check/proxy range.
            "130.211.0.0/22",  # NOSONAR - Google Cloud Load Balancer health check/proxy range.
        ],
        "googleApiCidrs": [
            "199.36.153.4/30",  # NOSONAR - restricted.googleapis.com VIP range.
            "199.36.153.8/30",  # NOSONAR - private.googleapis.com VIP range.
        ],
        "privateServiceCidrs": private_service_cidrs,
        "rangeClusterApiCidrs": range_cluster_api_cidrs,
        "rangeClusterApiPort": range_cluster_api_port,
    }


def render_gcp_helm_values(
    config: GDCBootstrapConfig,
    outputs: dict[str, dict[str, object]],
    *,
    image_tag: str,
    bootstrap_operator_email: str | None = None,
) -> dict[str, object]:
    """Render non-secret Helm values for the Shifter release from Terraform outputs."""
    pinned_image_tag = validate_image_tag(image_tag)
    image_roots = _get_string_mapping_output(outputs, "artifact_registry_image_roots")
    service_accounts = _get_output_value(outputs, "workload_service_accounts")
    public_hostname = str(_get_output_value(outputs, "public_hostname")).strip()
    managed_tls_enabled = bool(_get_output_value(outputs, "managed_tls_enabled"))
    runtime_env = _render_gcp_runtime_env(
        config,
        outputs,
        image_tag=pinned_image_tag,
        bootstrap_operator_email=bootstrap_operator_email,
    )
    edge_policy_name = str(_get_output_value(outputs, "cloud_armor_security_policy_name")).strip()
    # The range-provisioning Jobs reach the GDC range cluster apiserver through
    # the internal TCP load balancer on the peered range VPC. Allow egress to
    # exactly that endpoint host/port; empty until the endpoint is wired.
    range_cluster_host, _, range_cluster_port = (config.control_plane_platform_endpoint or "").partition(":")
    range_cluster_api_cidrs = _unique_nonempty_strings([_host_as_single_address_cidr(range_cluster_host)])

    return {
        "releaseNamespace": "shifter-system",
        "serviceAccounts": _helm_service_account_values(service_accounts),
        "runtimeEnv": runtime_env,
        # Reference only: the guacamole-runtime Kubernetes Secret is synced out
        # of band from Secret Manager (see sync_gcp_guacamole_runtime_secret).
        # Secret values must never enter Helm values or release history (#1180).
        "guacamoleRuntimeSecret": {"name": _GUACAMOLE_RUNTIME_RESOURCE_NAME},
        "images": _helm_image_values(image_roots, pinned_image_tag),
        "ingress": _helm_ingress_values(
            outputs,
            public_hostname=public_hostname,
            managed_tls_enabled=managed_tls_enabled,
        ),
        "services": _helm_backend_config_values(edge_policy_name),
        "networkPolicy": _helm_network_policy_values(
            _gcp_private_service_cidrs(outputs),
            range_cluster_api_cidrs,
            int(range_cluster_port or _GDC_APISERVER_BACKEND_PORT),
        ),
    }


def fetch_gcp_secret_payload(secret_id: str, project_id: str) -> str:
    """Return the latest Secret Manager payload for the given secret resource/name."""
    secret_name = secret_id.rstrip("/").split("/")[-1]
    result = subprocess.run(  # nosec B603 B607
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            "--secret",
            secret_name,
            "--project",
            project_id,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else _UNKNOWN_ERROR
        raise RuntimeError(f"Failed to read Secret Manager payload for {secret_name}: {stderr}")
    return result.stdout


def get_latest_gcp_secret_payload(secret_id: str, project_id: str) -> str | None:
    """Return the latest secret payload when one exists, otherwise None."""
    try:
        return fetch_gcp_secret_payload(secret_id, project_id)
    except RuntimeError as exc:
        message = str(exc).lower()
        if "not found" in message or "has no versions" in message:
            return None
        raise


def _is_retryable_gcp_terraform_init_error(message: str) -> bool:
    """Return True when terraform init failed due to bootstrap key or bucket IAM propagation."""
    normalized_message = message.lower()
    return "invalid jwt signature" in normalized_message or (
        "failed to get existing workspaces" in normalized_message
        and "403" in normalized_message
        and (
            "storage.objects.list" in normalized_message
            or "access to the google cloud storage bucket" in normalized_message
        )
    )


def _is_retryable_gcp_terraform_apply_error(message: str) -> bool:
    """Return True when terraform apply failed due to temporary bootstrap auth propagation."""
    normalized_message = message.lower()
    return "invalid jwt signature" in normalized_message or (
        "permission denied" in normalized_message
        or ("permission '" in normalized_message and " denied" in normalized_message)
        or " denied on resource " in normalized_message
        or "iam_permission_denied" in normalized_message
        or "does not have" in normalized_message
        or "error 403" in normalized_message
    )


def run_gcp_terraform_init_with_retry(
    config: GDCBootstrapConfig,
    tf_state_bucket: str,
    credentials_path: Path,
    *,
    max_attempts: int = 12,
    sleep_seconds: int = 5,
) -> None:
    """Run terraform init and retry only documented GCS backend IAM propagation failures."""
    init_cmd = [
        "terraform",
        "init",
        "-reconfigure",
        f"-backend-config=bucket={tf_state_bucket}",
        f"-backend-config=prefix=shifter/{config.environment}/platform-core",
        f"-backend-config=credentials={credentials_path}",
    ]
    info(f"Running: {' '.join(init_cmd)}")

    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(init_cmd, capture_output=True, text=True, check=False)  # nosec B603 B607
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode == 0:
            return

        combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if _is_retryable_gcp_terraform_init_error(combined_output) and attempt < max_attempts:
            warn(
                "Terraform bootstrap credentials are still propagating; "
                f"retrying terraform init in {sleep_seconds}s ({attempt}/{max_attempts})"
            )
            time.sleep(sleep_seconds)
            continue

        error(f"Command failed: Command '{' '.join(init_cmd)}' returned non-zero exit status {result.returncode}.")
        sys.exit(1)


def run_gcp_terraform_apply_with_retry(
    config: GDCBootstrapConfig, *, max_attempts: int = 24, sleep_seconds: int = 5
) -> None:
    """Run terraform apply and retry only temporary bootstrap-auth propagation failures."""
    apply_cmd = ["terraform", "apply", "-auto-approve", f"-var=project_id={config.project_id}"]
    info(f"Running: {' '.join(apply_cmd)}")

    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(apply_cmd, capture_output=True, text=True, check=False)  # nosec B603 B607
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode == 0:
            return

        combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if _is_retryable_gcp_terraform_apply_error(combined_output) and attempt < max_attempts:
            warn(
                "Terraform apply hit a temporary bootstrap-auth propagation error; "
                f"retrying in {sleep_seconds}s ({attempt}/{max_attempts})"
            )
            time.sleep(sleep_seconds)
            continue

        error(f"Command failed: Command '{' '.join(apply_cmd)}' returned non-zero exit status {result.returncode}.")
        sys.exit(1)


def _run_gcp_bootstrap_probe(cmd: list[str], credentials_path: Path) -> subprocess.CompletedProcess[str]:
    """Run a gcloud probe using the temporary bootstrap credential file."""
    env = os.environ.copy()
    env["CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"] = str(credentials_path)
    env["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)
    return subprocess.run(  # nosec B603 B607
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def wait_for_gcp_terraform_bootstrap_access(
    config: GDCBootstrapConfig,
    credentials_path: Path,
    *,
    max_attempts: int = 24,
    sleep_seconds: int = 5,
) -> None:
    """Wait until the bootstrap credentials can read the project resources Terraform manages."""
    probe_cmds = [
        [
            "gcloud",
            "storage",
            "buckets",
            "describe",
            f"gs://{config.terraform_state_bucket_name}",
            "--project",
            config.project_id,
        ],
        [
            "gcloud",
            "storage",
            "buckets",
            "list",
            "--project",
            config.project_id,
        ],
        [
            "gcloud",
            "artifacts",
            "repositories",
            "list",
            "--location",
            config.region,
            "--project",
            config.project_id,
        ],
    ]

    for attempt in range(1, max_attempts + 1):
        failures: list[str] = []
        for probe_cmd in probe_cmds:
            result = _run_gcp_bootstrap_probe(probe_cmd, credentials_path)
            if result.returncode == 0:
                continue
            failures.append("\n".join(part for part in (result.stdout, result.stderr) if part).strip())

        if not failures:
            return

        combined_output = "\n".join(failures).strip()
        if _is_retryable_gcp_terraform_apply_error(combined_output) and attempt < max_attempts:
            warn(
                "Terraform bootstrap credentials are not usable yet; "
                f"retrying readiness probes in {sleep_seconds}s ({attempt}/{max_attempts})"
            )
            time.sleep(sleep_seconds)
            continue

        error("Bootstrap credentials never became usable for Terraform-managed GCP resources.")
        if combined_output:
            print(combined_output, file=sys.stderr)
        sys.exit(1)


def prune_stale_gcp_terraform_bootstrap_keys(config: GDCBootstrapConfig) -> None:
    """Delete any leftover user-managed keys on the bootstrap service account before minting a fresh one."""
    result = subprocess.run(  # nosec B603 B607
        [
            "gcloud",
            "iam",
            "service-accounts",
            "keys",
            "list",
            "--iam-account",
            config.terraform_bootstrap_service_account_email,
            "--project",
            config.project_id,
            "--managed-by=user",
            "--format=value(name.basename())",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else _UNKNOWN_ERROR
        raise RuntimeError(f"Failed to list Terraform bootstrap service-account keys: {stderr}")

    key_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for key_id in key_ids:
        run_cmd(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "keys",
                "delete",
                key_id,
                "--iam-account",
                config.terraform_bootstrap_service_account_email,
                "--project",
                config.project_id,
                "--quiet",
            ],
            check=False,
        )


def _ensure_terraform_bootstrap_service_account(config: GDCBootstrapConfig) -> None:
    """Create the Terraform-bootstrap service account if it does not already exist."""
    if not gcloud_resource_exists(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "describe",
            config.terraform_bootstrap_service_account_email,
            "--project",
            config.project_id,
        ]
    ):
        run_cmd(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "create",
                config.terraform_bootstrap_service_account_name,
                "--project",
                config.project_id,
            ],
            check=False,
        )


def _grant_terraform_bootstrap_iam(config: GDCBootstrapConfig, member: str, bucket_url: str) -> None:
    """Grant the bootstrap service account the project roles and state-bucket binding."""
    for role in GCP_TERRAFORM_BOOTSTRAP_ROLES:
        add_project_iam_binding_with_retry(config.project_id, member, role)
    run_cmd(
        [
            "gcloud",
            "storage",
            "buckets",
            "add-iam-policy-binding",
            bucket_url,
            "--member",
            member,
            "--role",
            GCP_TERRAFORM_BOOTSTRAP_BUCKET_ROLE,
        ]
    )


def _revoke_terraform_bootstrap_iam(
    config: GDCBootstrapConfig,
    member: str,
    bucket_url: str,
    key_id: str,
    previous_env: dict[str, str | None],
) -> None:
    """Restore env vars and revoke the bootstrap key, project roles, and bucket binding."""
    for key, value in previous_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    if key_id:
        run_cmd(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "keys",
                "delete",
                key_id,
                "--iam-account",
                config.terraform_bootstrap_service_account_email,
                "--project",
                config.project_id,
                "--quiet",
            ],
            check=False,
        )

    for role in GCP_TERRAFORM_BOOTSTRAP_ROLES:
        run_cmd(
            [
                "gcloud",
                "projects",
                "remove-iam-policy-binding",
                config.project_id,
                "--member",
                member,
                "--role",
                role,
                "--no-user-output-enabled",
            ],
            check=False,
        )
    run_cmd(
        [
            "gcloud",
            "storage",
            "buckets",
            "remove-iam-policy-binding",
            bucket_url,
            "--member",
            member,
            "--role",
            GCP_TERRAFORM_BOOTSTRAP_BUCKET_ROLE,
        ],
        check=False,
    )


@contextmanager
def gcp_terraform_bootstrap_credentials(config: GDCBootstrapConfig) -> Iterator[Path]:
    """Provision temporary ADC-compatible credentials for Terraform bootstrap."""
    _ensure_terraform_bootstrap_service_account(config)

    member = f"serviceAccount:{config.terraform_bootstrap_service_account_email}"
    bucket_url = f"gs://{config.terraform_state_bucket_name}"
    _grant_terraform_bootstrap_iam(config, member, bucket_url)

    env_keys = ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_BACKEND_CREDENTIALS", "GOOGLE_CREDENTIALS")
    previous_env = {key: os.environ.get(key) for key in env_keys}
    key_id = ""

    with tempfile.TemporaryDirectory(prefix="shifter-gcp-tf-creds-") as temp_dir:
        credentials_path = Path(temp_dir) / "terraform-bootstrap.json"
        prune_stale_gcp_terraform_bootstrap_keys(config)
        run_cmd(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "keys",
                "create",
                str(credentials_path),
                "--iam-account",
                config.terraform_bootstrap_service_account_email,
                "--project",
                config.project_id,
            ]
        )
        key_id = str(json.loads(credentials_path.read_text()).get("private_key_id", "")).strip()

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)
        os.environ.pop("GOOGLE_BACKEND_CREDENTIALS", None)
        os.environ.pop("GOOGLE_CREDENTIALS", None)

        try:
            yield credentials_path
        finally:
            _revoke_terraform_bootstrap_iam(config, member, bucket_url, key_id, previous_env)


# Generated GCP range egress bridge tfvars (range_egress_mode +
# range_egress_allowed_cidrs). Rendered from shifter.yaml; gitignored.
RANGE_EGRESS_BRIDGE_FILENAME = "range_egress.auto.tfvars"


def resolve_shifter_config_path(config: GDCBootstrapConfig, repo_root: Path) -> Path:
    """Resolve the root installation config (shifter.yaml) that feeds the range egress render.

    Precedence: explicit ``--shifter-config`` (``config.shifter_config_path``), the
    ``SHIFTER_CONFIG`` environment variable, then the repo-root ``shifter.yaml``.

    A missing root config is a hard deploy failure: the deployed range firewall must be
    rendered from the single authoritative source, never silently defaulted to
    ``status-quo`` (the drift #1015 closes). Fails loud naming only the resolved path and
    the docs reference, never the config contents.
    """
    candidate = config.shifter_config_path or os.environ.get("SHIFTER_CONFIG")
    config_path = Path(candidate) if candidate else (repo_root / "shifter.yaml")
    if not config_path.exists():
        error(
            "Range egress render requires a root installation config (shifter.yaml). "
            f"Looked for: {config_path}. Provide --shifter-config or set SHIFTER_CONFIG. "
            "See docs/dev/deploy-secrets.md."
        )
        sys.exit(1)
    return config_path


def render_range_egress_tfvars(repo_root: Path, config_path: Path, output_path: Path, dry_run: bool = False) -> None:
    """Render the range egress bridge tfvars from ``config_path`` via ``shifter-config render``.

    Reuses the installation package's CLI (loader + RangeEgressPolicy + renderer) so the
    deployed firewall is generated from ``settings.range_egress`` rather than transcribed
    (ADR-017-R4). The config path and output path are passed as argv; the config contents
    are never read, echoed, or logged here.
    """
    run_cmd(
        [
            "uv",
            "run",
            "--project",
            str(repo_root / "shifter" / "installation"),
            "shifter-config",
            "render",
            str(config_path),
            "--output",
            str(output_path),
        ],
        dry_run=dry_run,
    )


def ensure_gcp_artifact_registry_service_identity(config: GDCBootstrapConfig, dry_run: bool = False) -> None:
    """Force-create the Artifact Registry service agent before Terraform grants it IAM."""
    service = "artifactregistry.googleapis.com"
    if dry_run:
        info(f"[DRY-RUN] Would provision the {service} service identity (P4SA)")
        return

    # Terraform also enables the service, but the service identity must exist
    # before Terraform grants that identity the CMEK encrypter role.
    run_cmd(["gcloud", "services", "enable", service, "--project", config.project_id])

    access_token = _gcp_identity_access_token()
    url = (
        "https://serviceusage.googleapis.com/v1beta1/"
        f"projects/{config.project_id}/services/{service}:generateServiceIdentity"
    )
    parsed_url = urllib_parse.urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "serviceusage.googleapis.com" or parsed_url.query:
        raise RuntimeError(f"Refusing to call unexpected Service Usage endpoint: {url}")
    request = urllib_request.Request(  # noqa: S310 - URL is validated immediately above
        url,
        data=b"",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": config.project_id,
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=30) as response:  # nosec B310  # noqa: S310
            json.loads(response.read().decode("utf-8"))
        success(f"Ensured {service} service identity exists")
    except urllib_error.HTTPError as exc:  # pragma: no cover - exercised via unit tests with monkeypatch
        body = exc.read().decode("utf-8") if exc.fp is not None else ""
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        message = parsed.get("error", {}).get("message", exc.reason)
        raise RuntimeError(f"Failed to provision {service} service identity: {message}") from exc


def apply_gcp_control_plane_terraform(
    config: GDCBootstrapConfig, dry_run: bool = False
) -> dict[str, dict[str, object]]:
    """Apply the GCP control-plane Terraform environment for the active project."""
    repo_root = get_repo_root()
    tf_dir = repo_root / "platform" / "terraform" / "gcp" / "environments" / config.environment
    if not tf_dir.exists():
        error(f"GCP Terraform directory not found: {tf_dir}")
        sys.exit(1)
    try:
        validate_gcp_control_plane_security_inputs(tf_dir)
    except ValueError as exc:
        error(str(exc))
        sys.exit(1)

    # Range egress single-source preflight (#1015): resolve and validate the root
    # config before any Terraform/state side effects so a missing config fails the
    # deploy up front instead of applying a stale/status-quo allowlist.
    shifter_config_path = resolve_shifter_config_path(config, repo_root)

    tf_state_bucket = config.terraform_state_bucket_name
    if not gcloud_resource_exists(
        ["gcloud", "storage", "buckets", "describe", f"gs://{tf_state_bucket}", "--project", config.project_id]
    ):
        run_cmd(
            [
                "gcloud",
                "storage",
                "buckets",
                "create",
                f"gs://{tf_state_bucket}",
                "--project",
                config.project_id,
                "--location",
                config.region,
                "--uniform-bucket-level-access",
            ],
            dry_run=dry_run,
        )

    run_cmd(
        ["gcloud", "storage", "buckets", "update", f"gs://{tf_state_bucket}", "--versioning"],
        dry_run=dry_run,
    )

    # Render the range egress bridge tfvars from shifter.yaml before Terraform consumes
    # the variables, so the deployed firewall matches settings.range_egress (#1015).
    render_range_egress_tfvars(repo_root, shifter_config_path, tf_dir / RANGE_EGRESS_BRIDGE_FILENAME, dry_run=dry_run)

    # Provision the Artifact Registry service agent before Terraform grants it
    # CMEK permissions; fresh projects do not have the identity yet.
    ensure_gcp_artifact_registry_service_identity(config, dry_run=dry_run)

    original_dir = os.getcwd()
    os.chdir(tf_dir)
    try:
        if dry_run:
            run_cmd(
                [
                    "terraform",
                    "init",
                    "-reconfigure",
                    f"-backend-config=bucket={tf_state_bucket}",
                    f"-backend-config=prefix=shifter/{config.environment}/platform-core",
                ],
                dry_run=dry_run,
            )
            run_cmd(
                [
                    "terraform",
                    "apply",
                    "-auto-approve",
                    f"-var=project_id={config.project_id}",
                ],
                dry_run=dry_run,
            )
            return {}

        with gcp_terraform_bootstrap_credentials(config) as credentials_path:
            run_gcp_terraform_init_with_retry(config, tf_state_bucket, credentials_path)
            wait_for_gcp_terraform_bootstrap_access(config, credentials_path)
            run_gcp_terraform_apply_with_retry(config)

            output_result = subprocess.run(  # nosec B603 B607
                ["terraform", "output", "-json"],
                capture_output=True,
                text=True,
                check=False,
            )
            if output_result.returncode != 0:
                stderr = output_result.stderr.strip() if output_result.stderr else _UNKNOWN_ERROR
                raise RuntimeError(f"Failed to capture Terraform outputs: {stderr}")
            return json.loads(output_result.stdout)
    finally:
        os.chdir(original_dir)


def stage_gcp_control_plane_values(
    config: GDCBootstrapConfig,
    outputs: dict[str, dict[str, object]],
    staging_root: Path,
    *,
    image_tag: str,
    bootstrap_operator_email: str | None = None,
) -> Path:
    """Stage the generated Helm values file for the Shifter release."""
    values = render_gcp_helm_values(
        config,
        outputs,
        image_tag=image_tag,
        bootstrap_operator_email=bootstrap_operator_email,
    )
    values_path = staging_root / "shifter.values.generated.json"
    values_path.write_text(json.dumps(values, indent=2, sort_keys=True))
    return values_path


def render_gcp_guacamole_runtime_secret_manifest(
    guacamole_db_payload: dict[str, str],
    guacamole_json_auth_value: str,
) -> dict[str, object]:
    """Render the Kubernetes Secret manifest consumed by guacamole-client."""
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": _GUACAMOLE_RUNTIME_RESOURCE_NAME,
            "namespace": "shifter-platform",
            "labels": {_K8S_PART_OF_LABEL: "shifter"},
        },
        "type": "Opaque",
        "stringData": {
            "POSTGRESQL_USER": guacamole_db_payload["username"],
            "POSTGRESQL_PASSWORD": guacamole_db_payload["password"],
            "JSON_SECRET_KEY": guacamole_json_auth_value,
        },
    }


def sync_gcp_guacamole_runtime_secret(
    config: GDCBootstrapConfig,
    outputs: dict[str, dict[str, object]],
    *,
    dry_run: bool = False,
) -> bool:
    """Sync guacamole-client runtime credentials to Kubernetes without writing them to disk."""
    if dry_run:
        info("[DRY-RUN] Would sync guacamole-runtime Kubernetes Secret from GCP Secret Manager")
        return False

    runtime_secret_ids = _get_string_mapping_output(outputs, "runtime_secret_ids")
    guacamole_db_payload = json.loads(fetch_gcp_secret_payload(runtime_secret_ids["guacamole-db"], config.project_id))
    guacamole_json_auth_value = fetch_gcp_secret_payload(
        runtime_secret_ids["guacamole-json-auth"],
        config.project_id,
    ).strip()
    manifest = render_gcp_guacamole_runtime_secret_manifest(guacamole_db_payload, guacamole_json_auth_value)
    result = subprocess.run(  # nosec B603 B607
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(manifest),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError("Failed to sync guacamole-runtime Kubernetes Secret")
    status = result.stdout.strip().lower()
    return "created" in status or "configured" in status


def restart_gcp_guacamole_client(dry_run: bool = False) -> None:
    """Restart guacamole-client so updated external Secret values are picked up."""
    run_cmd(
        ["kubectl", "-n", "shifter-platform", "rollout", "restart", "deployment/guacamole-client"],
        dry_run=dry_run,
    )
    run_cmd(
        ["kubectl", "-n", "shifter-platform", "rollout", "status", "deployment/guacamole-client", "--timeout=5m"],
        dry_run=dry_run,
    )


def push_gcp_control_plane_images(
    outputs: dict[str, dict[str, object]],
    *,
    image_tag: str,
    dry_run: bool = False,
) -> None:
    """Build and push the control-plane images to Artifact Registry."""
    pinned_image_tag = validate_image_tag(image_tag)
    image_roots = _get_string_mapping_output(outputs, "artifact_registry_image_roots")
    artifact_registry_host = str(image_roots["portal"]).split("/")[0]
    repo_root = get_repo_root()

    run_cmd(["gcloud", "auth", "configure-docker", artifact_registry_host, "--quiet"], dry_run=dry_run)

    image_builds = [
        (
            f"{image_roots['portal']}:{pinned_image_tag}",
            repo_root / "shifter",
            repo_root / "shifter" / "shifter_platform" / "Dockerfile",
        ),
        (
            f"{image_roots['pulumi-provisioner']}:{pinned_image_tag}",
            # The Dockerfile copies engine/provisioner/ and sibling cyberscript/
            # paths, both relative to shifter/.
            repo_root / "shifter",
            repo_root / "shifter" / "engine" / "provisioner" / "Dockerfile",
        ),
        (
            f"{image_roots['guacd']}:{pinned_image_tag}",
            repo_root / "shifter" / "engine" / "guacd",
            repo_root / "shifter" / "engine" / "guacd" / "Dockerfile",
        ),
        (
            f"{image_roots['guacamole-client']}:{pinned_image_tag}",
            repo_root / "shifter" / "engine" / "guacamole",
            repo_root / "shifter" / "engine" / "guacamole" / "Dockerfile",
        ),
    ]

    for tag, context_dir, dockerfile in image_builds:
        run_cmd(
            ["docker", "build", "-f", str(dockerfile), "-t", tag, str(context_dir)],
            dry_run=dry_run,
        )
        run_cmd(["docker", "push", tag], dry_run=dry_run)


def install_gke_gcloud_auth_plugin_user_space(dry_run: bool = False) -> None:
    """Install the GKE kubectl auth plugin into ~/.local/bin without root privileges."""
    if dry_run:
        info("Would install gke-gcloud-auth-plugin into ~/.local/bin via apt package extraction")
        return

    if not shutil.which("apt") or not shutil.which("dpkg-deb"):
        error(
            "gke-gcloud-auth-plugin is required for kubectl access to GKE and is not installed. "
            "User-space install requires both apt and dpkg-deb."
        )
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="gke-auth-plugin-") as temp_dir:
        temp_path = Path(temp_dir)
        subprocess.run(  # nosec B603 B607
            ["apt", "download", "google-cloud-cli-gke-gcloud-auth-plugin"],
            cwd=temp_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        deb_packages = sorted(temp_path.glob("google-cloud-cli-gke-gcloud-auth-plugin_*.deb"))
        if not deb_packages:
            error("Unable to locate downloaded google-cloud-cli-gke-gcloud-auth-plugin package.")
            sys.exit(1)

        extract_dir = temp_path / "extract"
        subprocess.run(  # nosec B603 B607
            ["dpkg-deb", "-x", str(deb_packages[0]), str(extract_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        source_binary = extract_dir / "usr" / "lib" / "google-cloud-sdk" / "bin" / "gke-gcloud-auth-plugin"
        if not source_binary.exists():
            error("Downloaded gke-gcloud-auth-plugin package did not contain the expected binary.")
            sys.exit(1)

        destination_dir = Path.home() / ".local" / "bin"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_binary = destination_dir / "gke-gcloud-auth-plugin"
        shutil.copy2(source_binary, destination_binary)
        destination_binary.chmod(0o755)


def _gcloud_components_install_gke_plugin(dry_run: bool = False) -> bool:
    """Install the GKE auth plugin via the gcloud component manager when available."""
    if not shutil.which("gcloud"):
        return False
    if dry_run:
        info("[DRY-RUN] Would run: gcloud components install gke-gcloud-auth-plugin --quiet")
        return True
    result = subprocess.run(  # nosec B603 B607
        ["gcloud", "components", "install", "gke-gcloud-auth-plugin", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode == 0


def _install_gke_plugin_via_apt(dry_run: bool = False) -> None:
    """Install the GKE auth plugin via apt as a fallback."""
    if not shutil.which("apt-get"):
        error(
            "gke-gcloud-auth-plugin is required for kubectl access to GKE and is not installed. "
            "Automatic installation requires the gcloud component manager or apt-based package tooling."
        )
        sys.exit(1)
    if os.geteuid() == 0:
        command_prefix: list[str] = []
    elif shutil.which("sudo"):
        command_prefix = ["sudo"]
    else:
        install_gke_gcloud_auth_plugin_user_space(dry_run=dry_run)
        return
    run_cmd([*command_prefix, "apt-get", "update"], dry_run=dry_run)
    run_cmd(
        [*command_prefix, "apt-get", "install", "-y", "google-cloud-cli-gke-gcloud-auth-plugin"],
        dry_run=dry_run,
    )


def ensure_gke_gcloud_auth_plugin(dry_run: bool = False) -> None:
    """Ensure the kubectl GKE auth plugin is present on the bootstrap host."""
    if shutil.which("gke-gcloud-auth-plugin"):
        return

    warn("Installing gke-gcloud-auth-plugin for kubectl access to GKE")

    if not _gcloud_components_install_gke_plugin(dry_run=dry_run):
        _install_gke_plugin_via_apt(dry_run=dry_run)

    if dry_run:
        return

    if not shutil.which("gke-gcloud-auth-plugin"):
        error("gke-gcloud-auth-plugin install completed but the binary is still unavailable on PATH.")
        sys.exit(1)


def helm_release_exists(release_name: str, namespace: str) -> bool:
    """Return True when the named Helm release already exists in the target namespace."""
    result = subprocess.run(  # nosec B603 B607
        ["helm", "status", release_name, "--namespace", namespace],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _kubectl_get_resource_names(get_args: list[str], namespace: str, description: str) -> list[str] | None:
    """Run `kubectl get` and return resource names, or None if the namespace does not exist."""
    result = subprocess.run(  # nosec B603 B607
        ["kubectl", "-n", namespace, "get", *get_args, "-o", "name", "--ignore-not-found"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip().lower() if result.stderr else ""
        if f'namespaces "{namespace}" not found' in stderr:
            return None
        raise RuntimeError(f"Failed to inspect {description} resources in namespace {namespace}: {result.stderr}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def list_gcp_helm_cutover_resources(namespace: str) -> list[str]:
    """List legacy Shifter resources in a namespace that must be purged before Helm takes ownership."""
    labeled = _kubectl_get_resource_names(
        [
            "deploy,svc,sa,cm,secret,ingress,rs,pod,job,cronjob,sts,ds",
            "-l",
            f"{_K8S_PART_OF_LABEL}=shifter",
        ],
        namespace,
        "legacy Helm-cutover",
    )
    if labeled is None:
        return []

    explicit_resource_names = {
        "shifter-platform": ["configmap/platform-runtime", "secret/guacamole-runtime"],
        "shifter-jobs": ["serviceaccount/provisioner"],
    }
    explicit_resources = explicit_resource_names.get(namespace, [])
    named: list[str] = []
    if explicit_resources:
        named_result = _kubectl_get_resource_names(explicit_resources, namespace, "explicit Helm-cutover")
        if named_result is None:
            return []
        named = named_result

    return sorted(set(labeled + named))


def prepare_gcp_helm_cutover(dry_run: bool = False) -> None:
    """Delete legacy unmanaged Shifter resources before the first Helm-managed install."""
    release_name = "shifter"
    release_namespace = "shifter-system"
    managed_namespaces = ["shifter-system", "shifter-platform", "shifter-jobs"]

    if helm_release_exists(release_name, release_namespace):
        return

    found_resources = {namespace: list_gcp_helm_cutover_resources(namespace) for namespace in managed_namespaces}
    if not any(found_resources.values()):
        return

    warn("No Helm release exists yet. Deleting legacy Shifter resources before Helm cutover.")
    for namespace, resources_to_delete in found_resources.items():
        if not resources_to_delete:
            continue
        run_cmd(
            [
                "kubectl",
                "-n",
                namespace,
                "delete",
                *resources_to_delete,
                "--ignore-not-found=true",
                "--wait=true",
                "--timeout=10m",
            ],
            dry_run=dry_run,
        )


def _get_kubernetes_namespace(name: str) -> dict[str, object] | None:
    """Return namespace JSON or None when the namespace does not exist."""
    result = subprocess.run(  # nosec B603 B607
        ["kubectl", "get", "namespace", name, "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return json.loads(result.stdout)

    stderr = result.stderr.strip().lower() if result.stderr else ""
    if f'namespaces "{name}" not found' in stderr:
        return None

    raise RuntimeError(f"Failed to inspect namespace {name}: {result.stderr}")


def _wait_for_namespace_absent(name: str, timeout_seconds: int = 300, poll_seconds: int = 2) -> None:
    """Wait until a namespace no longer exists."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        namespace = _get_kubernetes_namespace(name)
        if namespace is None:
            return
        time.sleep(poll_seconds)

    raise RuntimeError(f"Namespace {name} is still terminating after {timeout_seconds} seconds")


def _wait_for_namespace_active(name: str, timeout_seconds: int = 120, poll_seconds: int = 2) -> None:
    """Wait until a namespace exists and is Active."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        namespace = _get_kubernetes_namespace(name)
        if namespace and namespace.get("status", {}).get("phase") == "Active":
            return
        time.sleep(poll_seconds)

    raise RuntimeError(f"Namespace {name} did not become Active within {timeout_seconds} seconds")


def ensure_gcp_control_plane_namespaces(dry_run: bool = False) -> None:
    """Ensure Helm target namespaces exist outside of the release lifecycle."""
    namespace_specs = {
        "shifter-platform": {
            _K8S_PART_OF_LABEL: "shifter",
            "shifter.dev/plane": "control",
            "pod-security.kubernetes.io/enforce": "restricted",
            "pod-security.kubernetes.io/audit": "restricted",
            "pod-security.kubernetes.io/warn": "restricted",
        },
        "shifter-jobs": {
            _K8S_PART_OF_LABEL: "shifter",
            "shifter.dev/plane": "jobs",
            "pod-security.kubernetes.io/enforce": "restricted",
            "pod-security.kubernetes.io/audit": "restricted",
            "pod-security.kubernetes.io/warn": "restricted",
        },
    }

    for namespace_name, labels in namespace_specs.items():
        namespace = _get_kubernetes_namespace(namespace_name)
        if namespace and namespace.get("metadata", {}).get("deletionTimestamp"):
            warn(f"Namespace {namespace_name} is terminating; waiting for deletion before recreating it")
            if not dry_run:
                _wait_for_namespace_absent(namespace_name)

        manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": namespace_name,
                "labels": labels,
            },
        }

        if dry_run:
            info(f"Would apply namespace manifest for {namespace_name}")
            continue

        subprocess.run(  # nosec B603 B607
            ["kubectl", "apply", "-f", "-"],
            input=json.dumps(manifest),
            text=True,
            check=True,
            capture_output=True,
        )
        _wait_for_namespace_active(namespace_name)


def deploy_gcp_control_plane_with_helm(
    config: GDCBootstrapConfig,
    outputs: dict[str, dict[str, object]],
    values_path: Path,
    dry_run: bool = False,
) -> None:
    """Deploy Shifter onto GKE via Helm and wait for a healthy release."""
    cluster_name = str(_get_output_value(outputs, "gke_cluster_name"))
    cluster_location = str(_get_output_value(outputs, "gke_cluster_location"))
    chart_path = get_repo_root() / "platform" / "charts" / "shifter"
    environment_values_path = chart_path / f"values-{config.environment}.yaml"

    if not environment_values_path.exists():
        error(f"Missing Helm values override for environment {config.environment}: {environment_values_path}")
        sys.exit(1)

    ensure_gke_gcloud_auth_plugin(dry_run=dry_run)

    run_cmd(
        [
            "gcloud",
            "container",
            "clusters",
            "get-credentials",
            cluster_name,
            "--location",
            cluster_location,
            "--project",
            config.project_id,
        ],
        dry_run=dry_run,
    )
    prepare_gcp_helm_cutover(dry_run=dry_run)
    ensure_gcp_control_plane_namespaces(dry_run=dry_run)
    guacamole_runtime_changed = sync_gcp_guacamole_runtime_secret(config, outputs, dry_run=dry_run)
    run_cmd(
        [
            "helm",
            "upgrade",
            "--install",
            "shifter",
            str(chart_path),
            "--namespace",
            "shifter-system",
            "--create-namespace",
            "--values",
            str(environment_values_path),
            "--values",
            str(values_path),
            "--atomic",
            "--wait",
            "--timeout",
            "15m",
            "--history-max",
            "10",
        ],
        dry_run=dry_run,
    )
    if guacamole_runtime_changed:
        restart_gcp_guacamole_client(dry_run=dry_run)


def get_gcp_managed_certificate_status(
    certificate_name: str = "platform-managed-cert",
    namespace: str = "shifter-platform",
) -> str:
    """Return the current managed certificate status from the cluster."""
    result = subprocess.run(  # nosec B603 B607
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "managedcertificate",
            certificate_name,
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else _UNKNOWN_ERROR
        raise RuntimeError(f"Failed to inspect managed certificate {certificate_name}: {stderr}")

    payload = json.loads(result.stdout)
    return str(payload.get("status", {}).get("certificateStatus", "")).strip()


def wait_for_gcp_managed_certificate_active(
    timeout_seconds: int = 1800,
    poll_seconds: int = 10,
) -> None:
    """Wait until the GKE managed certificate reports Active."""
    deadline = time.time() + timeout_seconds
    last_status = ""
    while time.time() < deadline:
        status = get_gcp_managed_certificate_status()
        last_status = status or "UNKNOWN"
        normalized_status = last_status.lower()
        if normalized_status == "active":
            success("GKE managed certificate is active")
            return
        if normalized_status.startswith("failed"):
            raise RuntimeError(f"GKE managed certificate entered terminal status: {last_status}")
        info(f"Waiting for GKE managed certificate to become Active (current status: {last_status})")
        time.sleep(poll_seconds)

    raise RuntimeError(
        f"GKE managed certificate did not become Active within {timeout_seconds} seconds "
        f"(last status: {last_status or 'UNKNOWN'})"
    )


def verify_gcp_public_portal(hostname: str) -> None:
    """Verify the public Shifter endpoints are reachable over HTTPS."""
    health_result = subprocess.run(  # nosec B603 B607
        ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", f"https://{hostname}/health/"],
        capture_output=True,
        text=True,
        check=False,
    )
    health_code = health_result.stdout.strip()
    if health_result.returncode != 0 or health_code != "200":
        raise RuntimeError(
            f"Portal health check failed for https://{hostname}/health/ "
            f"(exit={health_result.returncode}, code={health_code or 'n/a'})"
        )

    mission_control_result = subprocess.run(  # nosec B603 B607
        ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", f"https://{hostname}/mission-control/"],
        capture_output=True,
        text=True,
        check=False,
    )
    mission_control_code = mission_control_result.stdout.strip()
    if mission_control_result.returncode != 0 or mission_control_code not in {"200", "301", "302", "303", "307", "308"}:
        raise RuntimeError(
            f"Mission Control endpoint failed for https://{hostname}/mission-control/ "
            f"(exit={mission_control_result.returncode}, code={mission_control_code or 'n/a'})"
        )

    success(f"Verified public portal over HTTPS at https://{hostname}/")


def walkthrough_gcp_dns_setup_and_wait_for_tls(
    outputs: dict[str, dict[str, object]],
    dry_run: bool = False,
) -> None:
    """Guide the operator through DNS cutover and wait for the managed certificate to become active."""
    header("Point Domain to GCP Load Balancer")

    hostname = str(_get_output_value(outputs, "public_hostname")).strip()
    ingress_ip = str(_get_output_value(outputs, "public_ingress_ip_address")).strip()

    print("The GCP ingress and global IP now exist.\n")
    subheader("Create or update this DNS record")
    print(f"  {Colors.BOLD}Type:{Colors.END}  A")
    print(f"  {Colors.BOLD}Name:{Colors.END}  {hostname}")
    print(f"  {Colors.BOLD}Value:{Colors.END} {ingress_ip}")
    print(
        f"\n{Colors.DIM}If the hostname is proxied through Cloudflare or another CDN, "
        f"disable proxying until the Google-managed certificate reports Active.{Colors.END}"
    )

    if dry_run:
        info(f"[DRY-RUN] Would wait for DNS to point {hostname} at {ingress_ip} and verify HTTPS")
        return

    wait_for_user(
        f"Update DNS so {hostname} points to {ingress_ip}.\n"
        "Once the record is live, bootstrap will wait for the managed certificate and verify the portal."
    )
    wait_for_gcp_managed_certificate_active()
    verify_gcp_public_portal(hostname)


def bootstrap_gcp_control_plane(config: GDCBootstrapConfig, dry_run: bool = False) -> dict[str, dict[str, object]]:
    """Bootstrap the GCP control-plane infrastructure and workloads for gcp-dev."""
    header(f"Deploying {config.environment} Shifter Platform")
    outputs = apply_gcp_control_plane_terraform(config, dry_run=dry_run)
    if dry_run:
        return outputs

    bootstrap_operator_email = ensure_gcp_identity_platform_operator(config, outputs, dry_run=dry_run)
    image_tag = resolve_gcp_control_plane_image_tag()
    push_gcp_control_plane_images(outputs, image_tag=image_tag, dry_run=dry_run)
    with tempfile.TemporaryDirectory(prefix="shifter-gcp-platform-") as staging_root_name:
        values_path = stage_gcp_control_plane_values(
            config,
            outputs,
            Path(staging_root_name),
            image_tag=image_tag,
            bootstrap_operator_email=bootstrap_operator_email,
        )
        deploy_gcp_control_plane_with_helm(config, outputs, values_path, dry_run=dry_run)
    walkthrough_gcp_dns_setup_and_wait_for_tls(outputs, dry_run=dry_run)
    success(f"{config.environment} Shifter platform deployed")
    return outputs


def gdc_bootstrap_cluster(config: GDCBootstrapConfig, dry_run: bool = False) -> dict[str, str]:
    """Bootstrap the repeatable GDC-on-Compute-Engine VM Runtime cluster."""
    if not config.project_id:
        error("GDC bootstrap requires a GCP project ID. Set PANW_GCP_DEV or pass --project-id.")
        sys.exit(1)

    header(f"Bootstrapping {config.cluster_id} GDC Cluster")

    info(f"GCP Project: {config.project_id}")
    info(f"Region / Zone: {config.region} / {config.zone}")
    info(f"Network: {config.resolved_network_name} ({config.subnet_cidr})")
    info(f"Service Account: {config.service_account_email}")
    info(f"VM Runtime VIPs: control-plane={config.control_plane_vip}, ingress={config.ingress_vip}")

    if not dry_run and not confirm("Create or reconcile these GDC bootstrap resources?"):
        warn("Aborted by user")
        sys.exit(0)

    ensure_gdc_apis(config, dry_run=dry_run)
    ensure_gdc_service_account(config, dry_run=dry_run)

    with tempfile.TemporaryDirectory(prefix="shifter-gdc-bootstrap-") as staging_dir_name:
        staged_assets = stage_gdc_bootstrap_assets(config, Path(staging_dir_name), dry_run=dry_run)
        ensure_gdc_network(config, dry_run=dry_run)
        ensure_gdc_instances(config, staged_assets["ssh_metadata"], dry_run=dry_run)
        sync_gdc_instance_ssh_metadata(config, staged_assets["ssh_metadata"], dry_run=dry_run)

        for host in config.all_hosts:
            wait_for_gdc_ssh(config, host, dry_run=dry_run)

        upload_gdc_assets(config, staged_assets["assets_dir"], dry_run=dry_run)
        run_gdc_workstation_script(config, "prepare-workstation.sh", dry_run=dry_run)
        run_gdc_workstation_script(config, "prepare-hosts.sh", dry_run=dry_run)
        run_gdc_workstation_script(config, "create-cluster.sh", dry_run=dry_run)
        run_gdc_workstation_script(config, "install-helper.sh", dry_run=dry_run)
        sync_gdc_access_secret(config, dry_run=dry_run)
        sync_gdc_vm_image_secret(config, staged_assets["service_account_key"], dry_run=dry_run)

    control_plane_outputs = bootstrap_gcp_control_plane(config, dry_run=dry_run)

    success("GDC bootstrap complete")
    print("\nNext commands:")
    ssh_command = (
        f"gcloud compute ssh root@{config.workstation.name} --tunnel-through-iap "
        f"--project {config.project_id} --zone {config.zone}"
    )
    code_block(
        f"""{ssh_command}
shifter-gdc-kubectl get nodes
shifter-gdc-kubeconfig"""
    )

    return {
        "project_id": config.project_id,
        "cluster_id": config.cluster_id,
        "region": config.region,
        "zone": config.zone,
        "network_name": config.resolved_network_name,
        "subnetwork_name": config.resolved_subnetwork_name,
        "workstation": config.workstation.name,
        "kubeconfig_path": config.kubeconfig_path,
        "gdc_access_secret_id": config.gdc_access_secret_id,
        "gdc_vm_image_gcs_secret_id": config.gdc_vm_image_gcs_secret_id,
        "gke_cluster_name": (
            str(_get_output_value(control_plane_outputs, "gke_cluster_name")) if control_plane_outputs else ""
        ),
    }
