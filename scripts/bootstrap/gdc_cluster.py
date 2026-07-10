"""Google Distributed Cloud VM Runtime substrate bootstrap operations."""

import json
import subprocess  # nosec B404
import sys
import tempfile
import time
from pathlib import Path
from textwrap import dedent

from bootstrap_core import (
    _GDC_APISERVER_BACKEND_PORT,
    _UNKNOWN_ERROR,
    _YAML_METADATA,
    GCP_IAP_TCP_SOURCE_RANGE,
    GDC_API_SERVICES,
    GDC_SERVICE_ACCOUNT_ROLES,
    Colors,
    GDCBootstrapConfig,
    GDCHost,
    _redact_argv_for_log,
    error,
    gcloud_resource_exists,
    get_latest_gcp_secret_payload,
    info,
    run_cmd,
    warn,
)


def render_gdc_cluster_config(config: GDCBootstrapConfig) -> str:
    """Render the hybrid-cluster config used by bmctl on the workstation."""
    lines = [
        "---",
        "gcrKeyPath: /root/bm-gcr.json",
        "sshPrivateKeyPath: /root/.ssh/id_rsa",
        "gkeConnectAgentServiceAccountKeyPath: /root/bm-gcr.json",
        "gkeConnectRegisterServiceAccountKeyPath: /root/bm-gcr.json",
        "cloudOperationsServiceAccountKeyPath: /root/bm-gcr.json",
        "---",
        "apiVersion: v1",
        "kind: Namespace",
        _YAML_METADATA,
        f"  name: {config.cluster_namespace}",
        "---",
        "apiVersion: baremetal.cluster.gke.io/v1",
        "kind: Cluster",
        _YAML_METADATA,
        f"  name: {config.cluster_id}",
        f"  namespace: {config.cluster_namespace}",
        "spec:",
        "  type: hybrid",
        f"  anthosBareMetalVersion: {config.bmctl_version}",
        "  gkeConnect:",
        f"    projectID: {config.project_id}",
        "  controlPlane:",
        "    nodePoolSpec:",
        f"      clusterName: {config.cluster_id}",
        "      nodes:",
    ]
    lines.extend(f"      - address: {host.vxlan_ip}" for host in config.control_plane_hosts)
    lines.extend(
        [
            "  clusterNetwork:",
            "    multipleNetworkInterfaces: true",
            "    pods:",
            "      cidrBlocks:",
            f"      - {config.pod_cidr}",
            "    services:",
            "      cidrBlocks:",
            f"      - {config.service_cidr}",
            "  loadBalancer:",
            "    mode: bundled",
            "    ports:",
            "      controlPlaneLBPort: 443",
            "    vips:",
            f"      controlPlaneVIP: {config.control_plane_vip}",
            f"      ingressVIP: {config.ingress_vip}",
            "    addressPools:",
            "    - name: ingress-pool",
            "      addresses:",
            f"      - {config.address_pool}",
            "  clusterOperations:",
            f"    location: {config.region}",
            f"    projectID: {config.project_id}",
        ]
    )
    if config.google_account_email:
        lines.extend(
            [
                "  clusterSecurity:",
                "    authorization:",
                "      clusterAdmin:",
                "        gcpAccounts:",
                f"        - {config.google_account_email}",
            ]
        )
    lines.extend(
        [
            "  storage:",
            "    lvpNodeMounts:",
            "      path: /mnt/localpv-disk",
            "      storageClassName: node-disk",
            "    lvpShare:",
            "      numPVUnderSharedPath: 5",
            "      path: /mnt/localpv-share",
            "      storageClassName: local-shared",
            "  nodeConfig:",
            "    podDensity:",
            "      maxPodsPerNode: 250",
            "---",
            "apiVersion: baremetal.cluster.gke.io/v1",
            "kind: NodePool",
            _YAML_METADATA,
            "  name: node-pool-1",
            f"  namespace: {config.cluster_namespace}",
            "spec:",
            f"  clusterName: {config.cluster_id}",
            "  nodes:",
        ]
    )
    lines.extend(f"  - address: {host.vxlan_ip}" for host in config.worker_hosts)
    return "\n".join(lines) + "\n"


def render_gdc_prepare_workstation_script(config: GDCBootstrapConfig) -> str:
    """Render the workstation prep script."""
    return dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        export DEBIAN_FRONTEND=noninteractive

        apt-get -qq update
        apt-get -qq install -y ca-certificates curl jq

        if ! command -v docker >/dev/null 2>&1; then
          curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
          sh /tmp/get-docker.sh
        fi
        systemctl enable --now docker

        if ! command -v kubectl >/dev/null 2>&1; then
          KUBECTL_VERSION="$(curl -fsSL https://storage.googleapis.com/kubernetes-release/release/stable.txt)"
          curl -fsSLo /usr/local/sbin/kubectl \
            "https://storage.googleapis.com/kubernetes-release/release/${{KUBECTL_VERSION}}/bin/linux/amd64/kubectl"
          chmod +x /usr/local/sbin/kubectl
        fi

        install -d -m 700 /root/.ssh {config.staging_dir} {config.cluster_workspace_dir}
        install -m 600 {config.staging_bundle_dir}/id_rsa /root/.ssh/id_rsa
        install -m 644 {config.staging_bundle_dir}/id_rsa.pub /root/.ssh/id_rsa.pub
        install -m 600 {config.staging_bundle_dir}/bm-gcr.json /root/bm-gcr.json
        install -m 755 {config.staging_bundle_dir}/bmctl /usr/local/sbin/bmctl
        # accept-new pins each freshly created node's host key on first contact
        # while still rejecting a changed key on later connections.
        printf 'Host *\\n  StrictHostKeyChecking accept-new\\n  BatchMode yes\\n' >/root/.ssh/config
        chmod 600 /root/.ssh/config
        """
    )


def render_gdc_prepare_hosts_script(config: GDCBootstrapConfig) -> str:
    """Render the host prep script that creates vxlan0 and hardening on all nodes."""
    peer_ips = " ".join(host.primary_ip for host in config.all_hosts)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "configure_node() {",
        '  local vxlan_ip="$1"',
        "  local default_iface",
        "  default_iface=\"$(ip route show default | awk '/default/ {print $5; exit}')\"",
        "  if ! ip link show vxlan0 >/dev/null 2>&1; then",
        '    ip link add vxlan0 type vxlan id 42 dev "$default_iface" dstport 8472',
        "  fi",
        f"  for peer_ip in {peer_ips}; do",
        '    bridge fdb append to 00:00:00:00:00:00 dst "$peer_ip" dev vxlan0 2>/dev/null || true',
        "  done",
        '  ip addr replace "${vxlan_ip}/24" dev vxlan0',
        "  ip link set up dev vxlan0",
        "",
        "  install -d -m 755 /mnt/localpv-disk /mnt/localpv-share",
        "  cat >/etc/sysctl.d/99-gdc-vmruntime-inotify.conf <<'EOF'",
        "fs.inotify.max_user_instances = 1024",
        "fs.inotify.max_user_watches = 1048576",
        "EOF",
        "  sysctl --load /etc/sysctl.d/99-gdc-vmruntime-inotify.conf",
        "}",
        "",
        "configure_remote_host() {",
        '  local host_ip="$1"',
        '  local vxlan_ip="$2"',
        "  ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes \\",
        '    "root@${host_ip}" "bash -s" -- "${vxlan_ip}" <<\'EOF\'',
        "set -euo pipefail",
        'vxlan_ip="$1"',
        "default_iface=\"$(ip route show default | awk '/default/ {print $5; exit}')\"",
        "if ! ip link show vxlan0 >/dev/null 2>&1; then",
        '  ip link add vxlan0 type vxlan id 42 dev "$default_iface" dstport 8472',
        "fi",
        f"for peer_ip in {peer_ips}; do",
        '  bridge fdb append to 00:00:00:00:00:00 dst "$peer_ip" dev vxlan0 2>/dev/null || true',
        "done",
        'ip addr replace "${vxlan_ip}/24" dev vxlan0',
        "ip link set up dev vxlan0",
        "install -d -m 755 /mnt/localpv-disk /mnt/localpv-share",
        "cat >/etc/sysctl.d/99-gdc-vmruntime-inotify.conf <<'EON'",
        "fs.inotify.max_user_instances = 1024",
        "fs.inotify.max_user_watches = 1048576",
        "EON",
        "sysctl --load /etc/sysctl.d/99-gdc-vmruntime-inotify.conf",
        "EOF",
        "}",
        "",
        f'configure_node "{config.workstation.vxlan_ip}"',
    ]
    lines.extend(f'configure_remote_host "{host.primary_ip}" "{host.vxlan_ip}"' for host in config.cluster_node_hosts)
    return "\n".join(lines) + "\n"


def render_gdc_create_cluster_script(config: GDCBootstrapConfig) -> str:
    """Render the cluster creation and VM Runtime enablement script."""
    return dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        export GOOGLE_APPLICATION_CREDENTIALS=/root/bm-gcr.json
        install -d -m 755 {config.cluster_workspace_dir}

        if [ ! -f {config.kubeconfig_path} ]; then
          bmctl create config -c {config.cluster_id} --force
          install -m 600 {config.staging_bundle_dir}/cluster.yaml \
            {config.cluster_workspace_dir}/{config.cluster_id}.yaml
          bmctl check preflight -c {config.cluster_id}
          bmctl create cluster -c {config.cluster_id}
        fi
        bmctl check vmruntimepfc --kubeconfig {config.kubeconfig_path}
        kubectl --kubeconfig {config.kubeconfig_path} patch vmruntime vmruntime --type merge \
          -p '{{"spec":{{"enabled":true}}}}'
        kubectl --kubeconfig {config.kubeconfig_path} wait \
          --for=jsonpath='{{.status.ready}}'=true vmruntime/vmruntime --timeout=10m
        """
    )


def render_gdc_install_helper_script(config: GDCBootstrapConfig) -> str:
    """Render helper scripts for repeated admin access on the workstation."""
    return dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        cat >/usr/local/bin/shifter-gdc-kubectl <<'EOF'
        #!/usr/bin/env bash
        set -euo pipefail
        exec env KUBECONFIG="{config.kubeconfig_path}" kubectl "$@"
        EOF
        chmod +x /usr/local/bin/shifter-gdc-kubectl

        cat >/usr/local/bin/shifter-gdc-kubeconfig <<'EOF'
        #!/usr/bin/env bash
        set -euo pipefail
        printf '%s\\n' "{config.kubeconfig_path}"
        EOF
        chmod +x /usr/local/bin/shifter-gdc-kubeconfig
        """
    )


def rewrite_gdc_kubeconfig_for_platform_access(kubeconfig: str, endpoint: str) -> str:
    """Repoint a bmctl kubeconfig at a platform-reachable control-plane endpoint."""
    host, _, port = endpoint.partition(":")
    server = f"https://{host}:{port or _GDC_APISERVER_BACKEND_PORT}"
    out: list[str] = []
    for line in kubeconfig.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith("server:"):
            out.append(f"{indent}server: {server}")
            out.append(f"{indent}insecure-skip-tls-verify: true")
            continue
        if stripped.startswith(("certificate-authority-data:", "certificate-authority:")):
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if kubeconfig.endswith("\n") else "")


def build_gdc_access_secret_payload(config: GDCBootstrapConfig, kubeconfig: str) -> str:
    """Build the provisioner-facing GDC access bundle stored in Secret Manager."""
    payload = {
        "cluster_id": config.cluster_id,
        "region": config.region,
        "vxlan_cidr": config.vxlan_cidr,
        "network_interface": "vxlan0",
        "range_namespace_prefix": "range",
        "dns_nameservers": ["8.8.8.8"],
        "static_ip_reservation_count": 4,
        "kubeconfig": kubeconfig,
    }
    return json.dumps(payload, indent=2)


def _gdc_ssh_read_file(config: GDCBootstrapConfig, remote_path: str) -> str | None:
    """Read a workstation file over gcloud ssh, returning None when absent."""
    result = subprocess.run(  # nosec B603 B607
        [
            "gcloud",
            "compute",
            "ssh",
            f"root@{config.workstation.name}",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            "--command",
            f"sudo cat {remote_path}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _service_account_key_is_active(config: GDCBootstrapConfig, key_payload: str) -> bool:
    """Return True when the service-account key embedded in the payload still exists."""
    try:
        private_key_id = json.loads(key_payload)["private_key_id"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError("Existing workstation service-account key payload is invalid") from exc

    result = subprocess.run(  # nosec B603 B607
        [
            "gcloud",
            "iam",
            "service-accounts",
            "keys",
            "list",
            "--iam-account",
            config.service_account_email,
            "--project",
            config.project_id,
            "--format=value(name)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else _UNKNOWN_ERROR
        raise RuntimeError(f"Failed to list service-account keys for {config.service_account_email}: {stderr}")

    active_key_ids = {line.rstrip("/").split("/")[-1] for line in result.stdout.splitlines() if line.strip()}
    return private_key_id in active_key_ids


def _fetch_existing_gdc_bootstrap_material(config: GDCBootstrapConfig) -> dict[str, str] | None:
    """Reuse the workstation bootstrap credentials when they already exist and remain valid."""
    if not gcloud_resource_exists(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            config.workstation.name,
            "--project",
            config.project_id,
            "--zone",
            config.zone,
        ]
    ):
        return None

    material = {
        "private_key": _gdc_ssh_read_file(config, "/root/.ssh/id_rsa"),
        "public_key": _gdc_ssh_read_file(config, "/root/.ssh/id_rsa.pub"),
        "service_account_key": _gdc_ssh_read_file(config, "/root/bm-gcr.json"),
    }
    if any(value is None or not value.strip() for value in material.values()):
        return None

    if not _service_account_key_is_active(config, material["service_account_key"]):
        warn(
            "Workstation bootstrap service-account key is no longer active; a fresh key will be created for this rerun"
        )
        return None

    info(f"Reusing existing bootstrap credentials from {config.workstation.name}")
    return material


def stage_gdc_bootstrap_assets(config: GDCBootstrapConfig, staging_dir: Path, dry_run: bool = False) -> dict[str, Path]:
    """Create the local assets that will be uploaded to the admin workstation."""
    assets_dir = staging_dir / config.cluster_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    private_key_path = assets_dir / "id_rsa"
    public_key_path = assets_dir / "id_rsa.pub"
    service_account_key_path = assets_dir / "bm-gcr.json"
    bmctl_binary_path = assets_dir / "bmctl"
    ssh_metadata_path = assets_dir / "ssh-metadata"
    cluster_config_path = assets_dir / "cluster.yaml"
    workstation_script = assets_dir / "prepare-workstation.sh"
    hosts_script = assets_dir / "prepare-hosts.sh"
    cluster_script = assets_dir / "create-cluster.sh"
    helper_script = assets_dir / "install-helper.sh"

    if dry_run:
        info(f"[DRY-RUN] Would generate bootstrap assets in {assets_dir}")
    else:
        existing_material = _fetch_existing_gdc_bootstrap_material(config)
        if existing_material:
            private_key_path.write_text(existing_material["private_key"])
            public_key_path.write_text(existing_material["public_key"])
            service_account_key_path.write_text(existing_material["service_account_key"])
        else:
            run_cmd(["ssh-keygen", "-t", "rsa", "-N", "", "-f", str(private_key_path)])
            run_cmd(
                [
                    "gcloud",
                    "iam",
                    "service-accounts",
                    "keys",
                    "create",
                    str(service_account_key_path),
                    "--iam-account",
                    config.service_account_email,
                    "--project",
                    config.project_id,
                ]
            )
        run_cmd(["gcloud", "storage", "cp", config.bmctl_gcs_source, str(bmctl_binary_path)])
        private_key_path.chmod(0o600)
        public_key_path.chmod(0o644)
        service_account_key_path.chmod(0o600)
        ssh_metadata_path.write_text(f"root:{public_key_path.read_text().strip()}\n")
        cluster_config_path.write_text(render_gdc_cluster_config(config))
        workstation_script.write_text(render_gdc_prepare_workstation_script(config))
        hosts_script.write_text(render_gdc_prepare_hosts_script(config))
        cluster_script.write_text(render_gdc_create_cluster_script(config))
        helper_script.write_text(render_gdc_install_helper_script(config))
        for script_path in (workstation_script, hosts_script, cluster_script, helper_script):
            script_path.chmod(0o755)

    return {
        "assets_dir": assets_dir,
        "private_key": private_key_path,
        "public_key": public_key_path,
        "service_account_key": service_account_key_path,
        "bmctl_binary": bmctl_binary_path,
        "ssh_metadata": ssh_metadata_path,
        "cluster_config": cluster_config_path,
        "workstation_script": workstation_script,
        "hosts_script": hosts_script,
        "cluster_script": cluster_script,
        "helper_script": helper_script,
    }


def ensure_gdc_apis(config: GDCBootstrapConfig, dry_run: bool = False) -> None:
    """Enable the GDC/GKE/GCP APIs required by the evaluation cluster."""
    run_cmd(["gcloud", "config", "set", "project", config.project_id], dry_run=dry_run)
    run_cmd(["gcloud", "services", "enable", *GDC_API_SERVICES, "--project", config.project_id], dry_run=dry_run)


def wait_for_gdc_service_account_visible(
    config: GDCBootstrapConfig,
    *,
    timeout_seconds: int = 60,
    poll_seconds: int = 2,
) -> None:
    """Wait for the shared GDC service account to become visible to follow-on IAM calls."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if gcloud_resource_exists(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "describe",
                config.service_account_email,
                "--project",
                config.project_id,
            ]
        ):
            return
        time.sleep(poll_seconds)
    raise RuntimeError(
        f"GDC service account {config.service_account_email} did not become visible within {timeout_seconds} seconds"
    )


def _is_retryable_gcp_iam_binding_error(message: str) -> bool:
    """Return True when a project IAM binding failed with a transient race."""
    normalized_message = message.lower()
    member_not_yet_visible = "does not exist" in normalized_message and "service account" in normalized_message
    concurrent_policy_change = (
        "concurrent policy change" in normalized_message
        or "the subject of a conflict" in normalized_message
        or ("etag" in normalized_message and "did not match" in normalized_message)
    )
    return member_not_yet_visible or concurrent_policy_change


def add_project_iam_binding_with_retry(
    project_id: str,
    member: str,
    role: str,
    *,
    dry_run: bool = False,
    max_attempts: int = 12,
    sleep_seconds: int = 5,
) -> None:
    """Bind a project IAM role, retrying member propagation and ETag races."""
    binding_cmd = [
        "gcloud",
        "projects",
        "add-iam-policy-binding",
        project_id,
        "--member",
        member,
        "--role",
        role,
        "--no-user-output-enabled",
    ]
    if dry_run:
        print(f"{Colors.BLUE}[DRY-RUN] Would run: {_redact_argv_for_log(binding_cmd)}{Colors.END}")
        return

    info(f"Running: {_redact_argv_for_log(binding_cmd)}")
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(binding_cmd, capture_output=True, text=True, check=False)  # nosec B603 B607
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode == 0:
            return

        combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if _is_retryable_gcp_iam_binding_error(combined_output) and attempt < max_attempts:
            warn(
                f"Transient IAM binding race for {role} on {member}; "
                f"retrying in {sleep_seconds}s ({attempt}/{max_attempts})"
            )
            time.sleep(sleep_seconds)
            continue

        error(f"Command failed: Command '{' '.join(binding_cmd)}' returned non-zero exit status {result.returncode}.")
        sys.exit(1)


def ensure_gdc_service_account(config: GDCBootstrapConfig, dry_run: bool = False) -> None:
    """Create the shared GDC service account and grant the required project roles."""
    service_account_exists = gcloud_resource_exists(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "describe",
            config.service_account_email,
            "--project",
            config.project_id,
        ]
    )

    if dry_run or not service_account_exists:
        run_cmd(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "create",
                config.service_account_name,
                "--project",
                config.project_id,
            ],
            dry_run=dry_run,
            check=False,
        )
        if not dry_run:
            wait_for_gdc_service_account_visible(config)

    member = f"serviceAccount:{config.service_account_email}"
    for role in GDC_SERVICE_ACCOUNT_ROLES:
        add_project_iam_binding_with_retry(config.project_id, member, role, dry_run=dry_run)


def ensure_gdc_access_secret(config: GDCBootstrapConfig, dry_run: bool = False) -> None:
    """Ensure the provisioner-facing GDC access secret exists."""
    if dry_run or not gcloud_resource_exists(
        [
            "gcloud",
            "secrets",
            "describe",
            config.gdc_access_secret_id,
            "--project",
            config.project_id,
        ]
    ):
        run_cmd(
            [
                "gcloud",
                "secrets",
                "create",
                config.gdc_access_secret_id,
                "--replication-policy",
                "automatic",
                "--project",
                config.project_id,
            ],
            dry_run=dry_run,
            check=False,
        )


def ensure_gdc_vm_image_secret(config: GDCBootstrapConfig, dry_run: bool = False) -> None:
    """Ensure the VM Runtime image-import Secret Manager secret exists."""
    if dry_run or not gcloud_resource_exists(
        [
            "gcloud",
            "secrets",
            "describe",
            config.gdc_vm_image_gcs_secret_id,
            "--project",
            config.project_id,
        ]
    ):
        run_cmd(
            [
                "gcloud",
                "secrets",
                "create",
                config.gdc_vm_image_gcs_secret_id,
                "--replication-policy",
                "automatic",
                "--project",
                config.project_id,
            ],
            dry_run=dry_run,
            check=False,
        )


def _ensure_gcloud_resource(describe_args: list[str], create_args: list[str], *, dry_run: bool) -> None:
    """Run `create_args` unless the resource described by `describe_args` already exists."""
    if dry_run or not gcloud_resource_exists(describe_args):
        run_cmd(create_args, dry_run=dry_run)


def _ensure_gdc_vpc_network(config: GDCBootstrapConfig, dry_run: bool) -> None:
    """Ensure the GDC custom VPC exists."""
    _ensure_gcloud_resource(
        ["gcloud", "compute", "networks", "describe", config.resolved_network_name, "--project", config.project_id],
        [
            "gcloud",
            "compute",
            "networks",
            "create",
            config.resolved_network_name,
            "--project",
            config.project_id,
            "--subnet-mode",
            "custom",
        ],
        dry_run=dry_run,
    )


def _ensure_gdc_subnetwork(config: GDCBootstrapConfig, dry_run: bool) -> None:
    """Ensure the GDC subnet exists with private Google access enabled."""
    _ensure_gcloud_resource(
        [
            "gcloud",
            "compute",
            "networks",
            "subnets",
            "describe",
            config.resolved_subnetwork_name,
            "--project",
            config.project_id,
            "--region",
            config.region,
        ],
        [
            "gcloud",
            "compute",
            "networks",
            "subnets",
            "create",
            config.resolved_subnetwork_name,
            "--project",
            config.project_id,
            "--network",
            config.resolved_network_name,
            "--region",
            config.region,
            "--range",
            config.subnet_cidr,
            "--enable-private-ip-google-access",
        ],
        dry_run=dry_run,
    )


def _ensure_gdc_cloud_nat(config: GDCBootstrapConfig, dry_run: bool) -> None:
    """Ensure the GDC router and Cloud NAT resources exist."""
    _ensure_gcloud_resource(
        [
            "gcloud",
            "compute",
            "routers",
            "describe",
            config.cloud_router_name,
            "--project",
            config.project_id,
            "--region",
            config.region,
        ],
        [
            "gcloud",
            "compute",
            "routers",
            "create",
            config.cloud_router_name,
            "--project",
            config.project_id,
            "--region",
            config.region,
            "--network",
            config.resolved_network_name,
        ],
        dry_run=dry_run,
    )

    _ensure_gcloud_resource(
        [
            "gcloud",
            "compute",
            "routers",
            "nats",
            "describe",
            config.cloud_nat_name,
            "--project",
            config.project_id,
            "--router",
            config.cloud_router_name,
            "--region",
            config.region,
        ],
        [
            "gcloud",
            "compute",
            "routers",
            "nats",
            "create",
            config.cloud_nat_name,
            "--project",
            config.project_id,
            "--router",
            config.cloud_router_name,
            "--region",
            config.region,
            "--auto-allocate-nat-external-ips",
            "--nat-custom-subnet-ip-ranges",
            config.resolved_subnetwork_name,
            "--enable-logging",
        ],
        dry_run=dry_run,
    )


def _gdc_firewall_rules(config: GDCBootstrapConfig) -> list[tuple[str, str, str]]:
    """Return the private-only firewall rules required by the GDC substrate."""
    return [
        (config.ssh_firewall_rule_name, "tcp:22", GCP_IAP_TCP_SOURCE_RANGE),
        (config.internal_firewall_rule_name, "tcp,udp,icmp", config.subnet_cidr),
        (config.lb_firewall_rule_name, "tcp:443,tcp:6444", config.subnet_cidr),
    ]


def _ensure_gdc_firewall_rules(config: GDCBootstrapConfig, dry_run: bool) -> None:
    """Ensure the GDC firewall rules exist."""
    for name, rules, source_ranges in _gdc_firewall_rules(config):
        _ensure_gcloud_resource(
            ["gcloud", "compute", "firewall-rules", "describe", name, "--project", config.project_id],
            [
                "gcloud",
                "compute",
                "firewall-rules",
                "create",
                name,
                "--project",
                config.project_id,
                "--network",
                config.resolved_network_name,
                "--direction",
                "INGRESS",
                "--allow",
                rules,
                "--source-ranges",
                source_ranges,
                "--target-tags",
                config.instance_tag,
            ],
            dry_run=dry_run,
        )


def ensure_gdc_network(config: GDCBootstrapConfig, dry_run: bool = False) -> None:
    """Create the custom VPC, subnet, NAT, and firewall rules used by the cluster."""
    _ensure_gdc_vpc_network(config, dry_run)
    _ensure_gdc_subnetwork(config, dry_run)
    _ensure_gdc_cloud_nat(config, dry_run)
    _ensure_gdc_firewall_rules(config, dry_run)


def gdc_instance_create_command(
    config: GDCBootstrapConfig,
    host: GDCHost,
    ssh_metadata_path: Path,
) -> list[str]:
    """Build the gcloud command to create a single cluster VM."""
    return [
        "gcloud",
        "compute",
        "instances",
        "create",
        host.name,
        "--project",
        config.project_id,
        "--zone",
        config.zone,
        "--machine-type",
        config.machine_type,
        "--boot-disk-size",
        f"{config.boot_disk_size_gb}G",
        "--boot-disk-type",
        config.boot_disk_type,
        "--image-family",
        "ubuntu-2204-lts",
        "--image-project",
        "ubuntu-os-cloud",
        "--subnet",
        config.resolved_subnetwork_name,
        "--no-address",
        "--private-network-ip",
        host.primary_ip,
        "--can-ip-forward",
        "--min-cpu-platform",
        "Intel Haswell",
        "--enable-nested-virtualization",
        "--service-account",
        config.service_account_email,
        "--scopes",
        "cloud-platform",
        "--tags",
        config.instance_tag,
        "--metadata",
        f"cluster_id={config.cluster_id},bmctl_version={config.bmctl_version},enable-oslogin=FALSE",
        "--metadata-from-file",
        f"ssh-keys={ssh_metadata_path}",
    ]


def ensure_gdc_instances(config: GDCBootstrapConfig, ssh_metadata_path: Path, dry_run: bool = False) -> None:
    """Create the workstation and cluster nodes if they do not already exist."""
    for host in config.all_hosts:
        if dry_run or not gcloud_resource_exists(
            [
                "gcloud",
                "compute",
                "instances",
                "describe",
                host.name,
                "--project",
                config.project_id,
                "--zone",
                config.zone,
            ]
        ):
            run_cmd(gdc_instance_create_command(config, host, ssh_metadata_path), dry_run=dry_run)


def get_gdc_instance_ssh_metadata(config: GDCBootstrapConfig, host_name: str) -> str:
    """Return the current ssh-keys metadata value for the given host."""
    result = subprocess.run(  # nosec B603 B607
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            host_name,
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            "--format=get(metadata.items[ssh-keys])",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else _UNKNOWN_ERROR
        raise RuntimeError(f"Failed to read ssh metadata for {host_name}: {stderr}")
    return result.stdout


def sync_gdc_instance_ssh_metadata(config: GDCBootstrapConfig, ssh_metadata_path: Path, dry_run: bool = False) -> None:
    """Ensure all instances trust the current bootstrap key pair."""
    expected_metadata = "" if dry_run else ssh_metadata_path.read_text().strip()
    for host in config.all_hosts:
        if not dry_run:
            current_metadata = get_gdc_instance_ssh_metadata(config, host.name).strip()
            if current_metadata == expected_metadata:
                continue
        run_cmd(
            [
                "gcloud",
                "compute",
                "instances",
                "add-metadata",
                host.name,
                "--project",
                config.project_id,
                "--zone",
                config.zone,
                "--metadata-from-file",
                f"ssh-keys={ssh_metadata_path}",
            ],
            dry_run=dry_run,
        )


def wait_for_gdc_ssh(config: GDCBootstrapConfig, host: GDCHost, dry_run: bool = False) -> None:
    """Wait until gcloud compute ssh succeeds for the given host."""
    if dry_run:
        info(f"[DRY-RUN] Would wait for SSH on {host.name}")
        return

    for attempt in range(1, 31):
        result = subprocess.run(  # nosec B603 B607
            [
                "gcloud",
                "compute",
                "ssh",
                f"root@{host.name}",
                "--tunnel-through-iap",
                "--project",
                config.project_id,
                "--zone",
                config.zone,
                "--command",
                "printf ready",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return
        info(f"Waiting for SSH on {host.name} (attempt {attempt}/30)")
        time.sleep(10)

    error(f"Timed out waiting for SSH on {host.name}")
    sys.exit(1)


def upload_gdc_assets(config: GDCBootstrapConfig, assets_dir: Path, dry_run: bool = False) -> None:
    """Upload the rendered bootstrap bundle to the admin workstation."""
    run_cmd(
        [
            "gcloud",
            "compute",
            "ssh",
            f"root@{config.workstation.name}",
            "--tunnel-through-iap",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            "--command",
            f"rm -rf {config.staging_bundle_dir} && mkdir -p {config.staging_dir}",
        ],
        dry_run=dry_run,
    )
    run_cmd(
        [
            "gcloud",
            "compute",
            "scp",
            "--recurse",
            "--tunnel-through-iap",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            str(assets_dir),
            f"root@{config.workstation.name}:{config.staging_dir}/",
        ],
        dry_run=dry_run,
    )


def run_gdc_workstation_script(
    config: GDCBootstrapConfig,
    script_name: str,
    dry_run: bool = False,
) -> None:
    """Execute a staged script on the admin workstation."""
    run_cmd(
        [
            "gcloud",
            "compute",
            "ssh",
            f"root@{config.workstation.name}",
            "--tunnel-through-iap",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            "--command",
            f"bash {config.staging_dir}/{config.cluster_id}/{script_name}",
        ],
        dry_run=dry_run,
    )


def fetch_gdc_kubeconfig(config: GDCBootstrapConfig, dry_run: bool = False) -> str:
    """Fetch the generated kubeconfig from the admin workstation."""
    if dry_run:
        return ""

    result = run_cmd(
        [
            "gcloud",
            "compute",
            "ssh",
            f"root@{config.workstation.name}",
            "--tunnel-through-iap",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            "--command",
            f"cat {config.kubeconfig_path}",
        ],
        capture=True,
    )
    if result is None or not result.stdout.strip():
        error("Failed to read the GDC kubeconfig from the admin workstation")
        sys.exit(1)
    kubeconfig = result.stdout
    if config.control_plane_platform_endpoint:
        kubeconfig = rewrite_gdc_kubeconfig_for_platform_access(kubeconfig, config.control_plane_platform_endpoint)
    return kubeconfig


def sync_gdc_access_secret(config: GDCBootstrapConfig, dry_run: bool = False) -> None:
    """Publish the current GDC kubeconfig and range-plane settings to Secret Manager."""
    ensure_gdc_access_secret(config, dry_run=dry_run)
    kubeconfig = fetch_gdc_kubeconfig(config, dry_run=dry_run)
    payload = build_gdc_access_secret_payload(config, kubeconfig)

    if dry_run:
        info(f"[DRY-RUN] Would add a new version to Secret Manager secret {config.gdc_access_secret_id}")
        return
    latest_payload = get_latest_gcp_secret_payload(config.gdc_access_secret_id, config.project_id)
    if latest_payload == payload:
        info(f"GDC access secret {config.gdc_access_secret_id} already matches the desired payload")
        return

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as handle:
        handle.write(payload)
        payload_path = Path(handle.name)

    try:
        run_cmd(
            [
                "gcloud",
                "secrets",
                "versions",
                "add",
                config.gdc_access_secret_id,
                "--data-file",
                str(payload_path),
                "--project",
                config.project_id,
            ]
        )
    finally:
        payload_path.unlink(missing_ok=True)


def sync_gdc_vm_image_secret(config: GDCBootstrapConfig, service_account_key_path: Path, dry_run: bool = False) -> None:
    """Publish the GCS image-import key to Secret Manager for range provisioning."""
    ensure_gdc_vm_image_secret(config, dry_run=dry_run)
    if not dry_run:
        latest_payload = get_latest_gcp_secret_payload(config.gdc_vm_image_gcs_secret_id, config.project_id)
        desired_payload = service_account_key_path.read_text()
        if latest_payload == desired_payload:
            info(
                f"GDC VM image secret {config.gdc_vm_image_gcs_secret_id} already matches "
                "the desired service-account key"
            )
            return
    run_cmd(
        [
            "gcloud",
            "secrets",
            "versions",
            "add",
            config.gdc_vm_image_gcs_secret_id,
            "--data-file",
            str(service_account_key_path),
            "--project",
            config.project_id,
        ],
        dry_run=dry_run,
    )
