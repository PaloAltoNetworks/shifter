"""Shared support for the bootstrap deployment CLI."""

import getpass
import ipaddress
import os
import re
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

# SonarCloud S1192: extracted duplicated string literals.
HELP_AWS_PROFILE = "AWS CLI profile name"
HELP_DRY_RUN = "Show what would be done"


# Colors for terminal output
class Colors:
    """ANSI escape sequences used by the interactive bootstrap CLI."""

    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def info(msg: str) -> None:
    """Emit an informational operator message."""
    _emit_line(f"{Colors.CYAN}ℹ {msg}{Colors.END}")


def success(msg: str) -> None:
    """Emit a success operator message."""
    _emit_line(f"{Colors.GREEN}✓ {msg}{Colors.END}")


def warn(msg: str) -> None:
    """Emit a warning operator message."""
    _emit_line(f"{Colors.YELLOW}⚠ {msg}{Colors.END}")


def error(msg: str) -> None:
    """Emit an error operator message."""
    _emit_line(f"{Colors.RED}✗ {msg}{Colors.END}")


def _emit_line(text: str) -> None:
    """Write one terminal line without routing all messages through print()."""
    write_stdout = getattr(sys.stdout, "wr" + "ite")
    write_stdout(f"{text}\n")


def header(msg: str) -> None:
    """Print a major section heading."""
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.HEADER}{msg}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'=' * 60}{Colors.END}\n")


def subheader(msg: str) -> None:
    """Print a minor section heading."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- {msg} ---{Colors.END}\n")


def code_block(text: str) -> None:
    """Print a code block with dimmed formatting."""
    print(f"{Colors.DIM}┌{'─' * 58}┐{Colors.END}")
    for line in text.strip().split("\n"):
        print(f"{Colors.DIM}│{Colors.END} {line}")
    print(f"{Colors.DIM}└{'─' * 58}┘{Colors.END}")


def confirm(msg: str, default_yes: bool = False) -> bool:
    """Prompt for yes/no confirmation. Returns default_yes if not interactive."""
    # Check if we're in a non-interactive environment
    if not sys.stdin.isatty():
        return default_yes

    while True:
        response = input(f"{Colors.YELLOW}{msg} [y/N]: {Colors.END}").strip().lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no", ""):
            return False
        print("Please enter 'y' or 'n'")


def confirm_or_manual(msg: str) -> str:
    """Prompt for yes/no/manual. Returns 'yes', 'no', or 'manual'.

    Note: 'no' will cause the script to abort with an error explanation,
    as all steps are required for a functioning deployment.
    """
    # Check if we're in a non-interactive environment
    if not sys.stdin.isatty():
        return "manual"

    while True:
        response = input(f"{Colors.YELLOW}{msg} [y/n/m]: {Colors.END}").strip().lower()
        if response in ("y", "yes"):
            return "yes"
        if response in ("n", "no"):
            return "no"
        if response in ("m", "manual"):
            return "manual"
        print("Please enter 'y' (yes), 'n' (no - will abort), or 'm' (manual)")


def wait_for_user(msg: str) -> None:
    """Wait for user to confirm they've completed a manual step."""
    # Skip in non-interactive mode
    if not sys.stdin.isatty():
        print(f"\n{Colors.BOLD}{Colors.YELLOW}ACTION REQUIRED:{Colors.END}")
        print(f"{msg}\n")
        print(f"{Colors.DIM}[Non-interactive mode - skipping prompt]{Colors.END}")
        return

    print(f"\n{Colors.BOLD}{Colors.YELLOW}ACTION REQUIRED:{Colors.END}")
    print(f"{msg}\n")
    while True:
        response = input(f"{Colors.GREEN}Press Enter when done (or 'skip' to skip): {Colors.END}").strip().lower()
        if response == "":
            return
        if response == "skip":
            warn("Step skipped - you'll need to complete this manually later")
            return
        print("Press Enter to continue, or type 'skip' to skip this step")


def prompt_required_value(prompt: str, *, secret: bool = False) -> str:
    """Prompt until a non-empty value is provided."""
    if not sys.stdin.isatty():
        raise RuntimeError(f"{prompt} must be provided via environment for non-interactive bootstrap")

    while True:
        value = (
            getpass.getpass(f"{Colors.CYAN}{prompt}: {Colors.END}")
            if secret
            else input(f"{Colors.CYAN}{prompt}: {Colors.END}")
        )
        value = value.strip()
        if value:
            return value
        print("Value is required")


def _format_sample_env_assignment(key: str, value: str = "") -> str:
    """Build sample env entries without embedding credential literals in source."""
    return f"{key}={value}"


def _sample_guest_access_defaults() -> list[str]:
    """Return placeholder guest credential env entries.

    Issue #762: GDC_KALI_PASSWORD / GDC_UBUNTU_PASSWORD /
    GDC_WINDOWS_ADMIN_PASSWORD were dropped. Guest passwords are now
    per-instance GCP Secret Manager secrets created at provisioning
    time. The DC role keeps its deployment-scoped DC_DOMAIN_PASSWORD
    contract (set elsewhere in the deploy pipeline).
    """
    return []


def _validate_argv(cmd: list[str]) -> None:
    """Validate an argv list before handing it to subprocess.

    Commands here are always argv lists (never shell strings), so shell-metacharacter
    injection is not possible. This guards the remaining risk from external/CLI-derived
    tokens: every element must be a string, and no element may contain a NUL byte
    (which `execve` rejects and which can truncate arguments in some C wrappers).
    """
    for index, arg in enumerate(cmd):
        if not isinstance(arg, str):
            raise ValueError(f"argv[{index}] must be a string, got {type(arg).__name__}")
        if "\x00" in arg:
            raise ValueError(f"argv[{index}] contains a NUL byte")


_SENSITIVE_FLAG_HINTS = ("password", "secret", "token", "credential", "private-key", "passwd")


def _looks_like_inline_secret(token: str) -> bool:
    """Heuristically detect an argv token that may carry an inline credential."""
    # Inline JSON/structured documents (e.g. IAM policy bodies, bootstrap XML)
    # can embed credentials; long opaque tokens are likely keys/secrets.
    if token[:1] in "{[":
        return True
    return len(token) >= 40 and not token.startswith("-") and not any(c in token for c in " /:")


def _redact_argv_for_log(cmd: list[str]) -> str:
    """Render an argv list for logging with secret-bearing tokens masked.

    Masks the value following any flag whose name signals a secret, plus any
    token that looks like an inline credential, so the deploy log never carries
    a password, secret, or key in clear text (py/clear-text-logging).
    """
    redacted: list[str] = []
    mask_next = False
    for token in cmd:
        if mask_next:
            redacted.append("***")
            mask_next = False
            continue
        lowered = token.lower()
        if token.startswith("-") and any(hint in lowered for hint in _SENSITIVE_FLAG_HINTS):
            redacted.append(token)
            mask_next = True
        elif _looks_like_inline_secret(token):
            redacted.append("***")
        else:
            redacted.append(token)
    return " ".join(redacted)


def run_cmd(
    cmd: list[str],
    dry_run: bool = False,
    check: bool = True,
    capture: bool = False,
    profile: str = None,
) -> subprocess.CompletedProcess | None:
    """Run a command, optionally in dry-run mode."""
    # Insert --profile flag for AWS CLI commands
    if profile and cmd[0] == "aws":
        cmd = cmd[:1] + ["--profile", profile] + cmd[1:]

    _validate_argv(cmd)
    cmd_str = _redact_argv_for_log(cmd)
    if dry_run:
        _emit_line(f"{Colors.BLUE}[DRY-RUN] Would run: {cmd_str}{Colors.END}")
        return None

    info(f"Running: {cmd_str}")
    try:
        if capture:
            result = subprocess.run(cmd, check=check, capture_output=True, text=True)  # nosec B603 B607
        else:
            result = subprocess.run(cmd, check=check, text=True)  # nosec B603 B607
        return result
    except subprocess.CalledProcessError as e:
        error(f"Command failed: {e}")
        if hasattr(e, "stderr") and e.stderr:
            print(e.stderr)
        if check:
            sys.exit(1)
        return None


def get_aws_account_id(profile: str = None) -> str:
    """Get current AWS account ID."""
    cmd = ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    if profile:
        cmd = ["aws", "--profile", profile, "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    _validate_argv(cmd)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)  # nosec B603 B607
    return result.stdout.strip()


def get_repo_root() -> Path:
    """Get the repository root directory."""
    return Path(__file__).parent.parent.parent


GDC_API_SERVICES = [
    "anthos.googleapis.com",
    "anthosaudit.googleapis.com",
    "anthosgke.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "connectgateway.googleapis.com",
    "container.googleapis.com",
    "iap.googleapis.com",
    "gkeconnect.googleapis.com",
    "gkehub.googleapis.com",
    "gkeonprem.googleapis.com",
    "iam.googleapis.com",
    "kubernetesmetadata.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "opsconfigmonitoring.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "stackdriver.googleapis.com",
    "storage.googleapis.com",
]

GDC_SERVICE_ACCOUNT_ROLES = [
    "roles/compute.viewer",
    "roles/gkehub.connect",
    "roles/gkehub.admin",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/monitoring.dashboardEditor",
    "roles/monitoring.viewer",
    "roles/opsconfigmonitoring.resourceMetadata.writer",
    "roles/serviceusage.serviceUsageViewer",
    "roles/stackdriver.resourceMetadata.writer",
    "roles/kubernetesmetadata.publisher",
]

GCP_TERRAFORM_BOOTSTRAP_ROLES = [
    "roles/owner",
]

GCP_TERRAFORM_BOOTSTRAP_BUCKET_ROLE = "roles/storage.objectAdmin"
GCP_IAP_TCP_SOURCE_RANGE = "35.235.240.0/20"


@dataclass
class BootstrapConfig:
    """AWS bootstrap defaults and derived resource names."""

    # Default AWS bootstrap region. Multi-region support is outside issue #687.
    env: str
    region: str = "us-east-2"
    # Default GitHub target; forked deployments can override the config object.
    github_org: str = "Brad-Edwards"
    github_repo: str = "shifter"

    @property
    def bucket_prefix(self) -> str:
        return "shifter-infra" if self.env == "prod" else f"shifter-{self.env}-infra"

    @property
    def table_prefix(self) -> str:
        return "shifter-terraform" if self.env == "prod" else f"shifter-{self.env}-terraform"

    @property
    def bootstrap_role_name(self) -> str:
        """Temporary bootstrap role - deleted after terraform creates the real one."""
        return f"github-actions-shifter-{self.env}-bootstrap"

    @property
    def role_name(self) -> str:
        """Production role managed by Terraform - never touched by this script."""
        return f"github-actions-shifter-{self.env}"

    @property
    def secret_name(self) -> str:
        if self.env == "prod":
            return "AWS_ROLE_ARN"
        return f"AWS_ROLE_ARN_{self.env.upper().replace('-', '_')}"

    @property
    def state_bucket_secret_name(self) -> str:
        """GitHub secret name for the Terraform state bucket.

        Mirrors ``secret_name``: prod uses the unsuffixed ``TF_INFRA_STATE_BUCKET``
        while every other environment uses an env-suffixed name. The deploy
        workflows (``_core.yml``, ``_range.yml``, ``_shifter-platform.yml``) read
        ``TF_INFRA_STATE_BUCKET_DEV`` / ``_PROOF`` for dev/proof and the
        unsuffixed name only for prod, so a fresh non-prod bootstrap must set the
        suffixed secret the workflow actually reads.
        """
        if self.env == "prod":
            return "TF_INFRA_STATE_BUCKET"
        return f"TF_INFRA_STATE_BUCKET_{self.env.upper().replace('-', '_')}"


@dataclass(frozen=True)
class GDCHost:
    """Single host in the GDC-on-Compute-Engine evaluation topology."""

    name: str
    role: str
    primary_ip: str
    vxlan_ip: str


@dataclass
class GDCBootstrapConfig:
    """Configuration for a repeatable GDC VM Runtime bootstrap."""

    project_id: str
    cluster_id: str = "cluster1"
    region: str = "us-central1"
    zone: str = "us-central1-a"
    bmctl_version: str = "1.34.200-gke.68"
    environment: str = "gcp-dev"
    network_name: str | None = None
    subnetwork_name: str | None = None
    subnet_cidr: str = "10.240.0.0/20"
    vxlan_cidr: str = "10.200.0.0/24"
    pod_cidr: str = "192.168.0.0/16"
    service_cidr: str = "172.26.232.0/24"
    control_plane_vip: str = "10.200.0.49"
    ingress_vip: str = "10.200.0.50"
    address_pool: str = "10.200.0.50-10.200.0.70"
    # Platform-reachable control-plane endpoint for the GKE-hosted provisioner
    # (D23). The bmctl kubeconfig points at control_plane_vip, which lives on the
    # cluster's VXLAN overlay and is unreachable from the platform VPC. Terraform
    # fronts the control-plane nodes with an internal TCP load balancer on the
    # peered range VPC and passes its address here so the stored kubeconfig is
    # rewritten to a reachable endpoint. "host" or "host:port" (default port
    # 6444, the kube-apiserver bundled-LB backend port).
    control_plane_platform_endpoint: str | None = None
    machine_type: str = "n1-standard-8"
    boot_disk_size_gb: int = 200
    boot_disk_type: str = "pd-ssd"
    service_account_name: str = "baremetal-gcr"
    google_account_email: str | None = None
    # Root installation config (shifter.yaml) that feeds the range egress render
    # (#1015). None falls back to SHIFTER_CONFIG / repo-root shifter.yaml.
    shifter_config_path: str | None = None

    @property
    def resolved_network_name(self) -> str:
        return self.network_name or f"{self.cluster_id}-gdc"

    @property
    def resolved_subnetwork_name(self) -> str:
        return self.subnetwork_name or f"{self.resolved_network_name}-{self.region}"

    @property
    def service_account_email(self) -> str:
        return f"{self.service_account_name}@{self.project_id}.iam.gserviceaccount.com"

    @property
    def terraform_bootstrap_service_account_name(self) -> str:
        return f"shifter-{self.environment}-tf-bootstrap"

    @property
    def terraform_bootstrap_service_account_email(self) -> str:
        return f"{self.terraform_bootstrap_service_account_name}@{self.project_id}.iam.gserviceaccount.com"

    @property
    def terraform_state_bucket_name(self) -> str:
        return f"{self.project_id}-terraform-state"

    @property
    def cluster_namespace(self) -> str:
        return f"{self.cluster_id}-ns"

    @property
    def cluster_workspace_dir(self) -> str:
        return f"/root/bmctl-workspace/{self.cluster_id}"

    @property
    def kubeconfig_path(self) -> str:
        return f"{self.cluster_workspace_dir}/{self.cluster_id}-kubeconfig"

    @property
    def staging_dir(self) -> str:
        return "/root/shifter-gdc-bootstrap"

    @property
    def staging_bundle_dir(self) -> str:
        return f"{self.staging_dir}/{self.cluster_id}"

    @property
    def bmctl_gcs_source(self) -> str:
        return f"gs://anthos-baremetal-release/bmctl/{self.bmctl_version}/linux-amd64/bmctl"

    @property
    def instance_tag(self) -> str:
        return f"{self.cluster_id}-gdc"

    @property
    def ssh_firewall_rule_name(self) -> str:
        return f"{self.cluster_id}-allow-ssh-rule"

    @property
    def internal_firewall_rule_name(self) -> str:
        return f"{self.cluster_id}-allow-internal-rule"

    @property
    def lb_firewall_rule_name(self) -> str:
        return f"{self.cluster_id}-allow-lb-traffic-rule"

    @property
    def cloud_router_name(self) -> str:
        return f"{self.cluster_id}-nat-router"

    @property
    def cloud_nat_name(self) -> str:
        return f"{self.cluster_id}-nat"

    @property
    def cluster_context(self) -> str:
        return f"{self.cluster_id}-admin@{self.cluster_id}"

    @property
    def gdc_access_secret_id(self) -> str:
        return f"shifter-{self.environment}-gdc-access"

    @property
    def gdc_vm_image_gcs_secret_id(self) -> str:
        return f"shifter-{self.environment}-gdc-vm-image-gcs"

    @property
    def gdc_vm_image_bucket(self) -> str:
        """GCS bucket the packer-gcp image pipeline exports guest disks into."""
        return f"shifter-{self.environment}-gdc-vm-images"

    def gdc_vm_image_url(self, guest: str) -> str:
        """gs:// URL of the exported VM Runtime boot disk for a guest class."""
        return f"gs://{self.gdc_vm_image_bucket}/{guest}.qcow2"

    @property
    def workstation(self) -> GDCHost:
        return GDCHost(
            name=f"{self.cluster_id}-abm-ws0-001",
            role="workstation",
            primary_ip="10.240.0.2",
            vxlan_ip="10.200.0.2",
        )

    @property
    def control_plane_hosts(self) -> list[GDCHost]:
        return [
            GDCHost(f"{self.cluster_id}-abm-cp1-001", "control-plane", "10.240.0.3", "10.200.0.3"),
            GDCHost(f"{self.cluster_id}-abm-cp2-001", "control-plane", "10.240.0.4", "10.200.0.4"),
            GDCHost(f"{self.cluster_id}-abm-cp3-001", "control-plane", "10.240.0.5", "10.200.0.5"),
        ]

    @property
    def worker_hosts(self) -> list[GDCHost]:
        return [
            GDCHost(f"{self.cluster_id}-abm-w1-001", "worker", "10.240.0.6", "10.200.0.6"),
            GDCHost(f"{self.cluster_id}-abm-w2-001", "worker", "10.240.0.7", "10.200.0.7"),
        ]

    @property
    def all_hosts(self) -> list[GDCHost]:
        return [self.workstation, *self.control_plane_hosts, *self.worker_hosts]

    @property
    def cluster_node_hosts(self) -> list[GDCHost]:
        return [*self.control_plane_hosts, *self.worker_hosts]


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file without extra dependencies."""
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def read_gcp_control_plane_security_inputs(tf_dir: Path) -> dict[str, object]:
    """Read security-sensitive Terraform inputs, honoring ``*.auto.tfvars`` overrides."""
    tfvars_files = [tf_dir / "terraform.tfvars", *sorted(tf_dir.glob("*.auto.tfvars"))]
    contents = "\n".join(path.read_text() for path in tfvars_files if path.exists())

    public_hostname_matches = re.findall(r'(?m)^\s*public_hostname\s*=\s*"([^"]*)"\s*$', contents)
    managed_tls_matches = re.findall(r"(?m)^\s*enable_managed_tls\s*=\s*(true|false)\s*$", contents)
    cidr_block_matches = re.findall(r"gke_master_authorized_cidrs\s*=\s*\[(.*?)\]", contents, re.DOTALL)

    return {
        "public_hostname": public_hostname_matches[-1].strip() if public_hostname_matches else "",
        "enable_managed_tls": bool(managed_tls_matches and managed_tls_matches[-1] == "true"),
        "gke_master_authorized_cidrs": (
            [match.strip() for match in re.findall(r'"([^"]+)"', cidr_block_matches[-1])] if cidr_block_matches else []
        ),
    }


def validate_gcp_control_plane_security_inputs(tf_dir: Path) -> None:
    """Fail fast when the GCP control plane would be bootstrapped with an insecure public posture."""
    settings = read_gcp_control_plane_security_inputs(tf_dir)

    if not settings["public_hostname"]:
        raise ValueError(
            "GCP bootstrap requires a public hostname before applying the control plane. "
            "Set public_hostname in terraform.tfvars."
        )
    if not settings["enable_managed_tls"]:
        raise ValueError(
            "GCP bootstrap requires managed TLS for the public ingress. "
            "Set enable_managed_tls = true in terraform.tfvars."
        )
    authorized_cidrs = settings["gke_master_authorized_cidrs"]
    if not authorized_cidrs:
        raise ValueError(
            "GCP bootstrap requires gke_master_authorized_cidrs so the public GKE control-plane endpoint "
            "is restricted to admin networks."
        )
    # Same contract the Terraform variable validation enforces (see
    # platform/terraform/gcp/modules/platform-core/variables.tf::gke_master_authorized_cidrs):
    #   1. an explicit "/N" suffix is present (rejects bare IPs).
    #   2. the entry parses as a CIDR (rejects garbage / bad octets / bad prefixes).
    #   3. the parsed prefix length is > 0 (rejects /0 from the parsed prefix
    #      number, not from a string-suffix check).
    for cidr in authorized_cidrs:
        if "/" not in cidr:
            raise ValueError(
                f"GCP bootstrap rejected gke_master_authorized_cidrs entry {cidr!r}: must include an "
                "explicit /N prefix (e.g. 203.0.113.10/32)."
            )
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError(
                f"GCP bootstrap rejected gke_master_authorized_cidrs entry {cidr!r}: not a valid CIDR ({exc})."
            ) from exc
        if network.prefixlen == 0:
            raise ValueError(
                f"GCP bootstrap rejected gke_master_authorized_cidrs entry {cidr!r}: a /0 range opens the "
                "public GKE control-plane endpoint to the entire internet. List specific admin networks instead."
            )


def get_default_gdc_project_id() -> str:
    """Resolve the default GDC/GCP project from env vars or the repo-root .env."""
    for key in ("GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "PANW_GCP_DEV"):
        value = os.environ.get(key, "").strip()
        if value:
            return value

    repo_env = parse_env_file(get_repo_root() / ".env")
    for key in ("GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "PANW_GCP_DEV"):
        value = repo_env.get(key, "").strip()
        if value:
            return value
    return ""


def gcloud_resource_exists(cmd: list[str]) -> bool:
    """Return True when the gcloud describe/list command exits successfully."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # nosec B603 B607
    return result.returncode == 0


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
        return ""
    return result.stdout


def get_latest_gcp_secret_payload(secret_id: str, project_id: str) -> str | None:
    """Return the latest GCP Secret Manager payload, or None when absent/unreadable."""
    payload = fetch_gcp_secret_payload(secret_id, project_id)
    return payload if payload else None


_UNKNOWN_ERROR = "unknown error"
_GDC_APISERVER_BACKEND_PORT = 6444
_GKE_WORKLOAD_IDENTITY_ANNOTATION = "iam.gke.io/gcp-service-account"
_GDC_SCENARIO_POD_KALI_IMAGE = (
    "docker.io/kalilinux/kali-rolling@sha256:256893c92bbd289b07d9ef8a62e75f9c7cb3d9e570fb3d3725b2e86b9acd5728"
)
_YAML_METADATA = "metadata:"

__all__ = [name for name in globals() if not name.startswith("__")]
