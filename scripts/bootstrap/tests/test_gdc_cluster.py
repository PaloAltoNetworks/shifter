"""Behavior tests split from deploy.py: test_gdc_cluster.py.

Tests verify the complete contract for each function:
1. Inputs - minimum required data and validation
2. Outputs - return values and data structures
3. Side effects - subprocess calls, file writes, system changes
4. Errors - error handling and propagation
5. Logging - debug and error logging

All external dependencies are mocked. No actual AWS calls, file operations,
or subprocess executions occur during tests.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import deploy

PINNED_IMAGE_TAG = "abc1234"

# =============================================================================
# Test Fixtures
# =============================================================================


def _sample_gcp_control_plane_outputs(project_id: str = "prod-rwctxzl6shxk") -> dict[str, dict[str, object]]:
    """Return representative Terraform outputs for the GCP control-plane path."""
    return {
        "gke_cluster_name": {"value": "shifter-gcp-dev-platform"},
        "gke_cluster_location": {"value": "us-central1"},
        "artifact_registry_image_roots": {
            "value": {
                "portal": f"us-central1-docker.pkg.dev/{project_id}/shifter-gcp-dev-portal/portal",
                "guacd": f"us-central1-docker.pkg.dev/{project_id}/shifter-gcp-dev-guacd/guacd",
                "guacamole-client": (
                    f"us-central1-docker.pkg.dev/{project_id}/shifter-gcp-dev-guacamole-client/guacamole-client"
                ),
                "pulumi-provisioner": (
                    f"us-central1-docker.pkg.dev/{project_id}/shifter-gcp-dev-pulumi-provisioner/pulumi-provisioner"
                ),
            }
        },
        "assets_bucket_name": {"value": f"{project_id}-gcp-dev-assets"},
        "terraform_state_bucket_name": {"value": f"{project_id}-terraform-state"},
        "platform_events_topic_id": {"value": f"projects/{project_id}/topics/shifter-gcp-dev-events"},
        "platform_event_subscriptions": {
            "value": {
                "cms": f"projects/{project_id}/subscriptions/shifter-gcp-dev-cms",
                "engine": f"projects/{project_id}/subscriptions/shifter-gcp-dev-engine",
                "mc": f"projects/{project_id}/subscriptions/shifter-gcp-dev-mc",
                "experiments": f"projects/{project_id}/subscriptions/shifter-gcp-dev-experiments",
            }
        },
        "runtime_secret_ids": {
            "value": {
                "app": f"projects/{project_id}/secrets/shifter-gcp-dev-app",
                "db": f"projects/{project_id}/secrets/shifter-gcp-dev-db",
                "guacamole-db": f"projects/{project_id}/secrets/shifter-gcp-dev-guacamole-db",
                "guacamole-json-auth": f"projects/{project_id}/secrets/shifter-gcp-dev-guacamole-json-auth",
                # ADR-008-R6 (#963): the GCP runtime renderer fails closed
                # without the Memorystore Secret Manager bundle ID.
                "redis": f"projects/{project_id}/secrets/shifter-gcp-dev-redis",
            }
        },
        "identity_platform_api_key": {"value": "identity-platform-api-key"},
        "identity_platform_project_id": {"value": project_id},
        "identity_allowed_email_domain": {"value": "paloaltonetworks.com"},
        "identity_allowed_emails": {"value": []},
        "control_plane_database": {
            "value": {
                "private_ip": "10.40.0.10",
                "port": 5432,
                "database_name": "shifter",
                "user_name": "shifter",
            }
        },
        # ADR-008-R6 (#963): Memorystore runs with TLS on the GCP runtime,
        # so the cache payload must carry tls_enabled or the renderer fails
        # closed.
        "control_plane_cache": {"value": {"host": "10.40.0.20", "port": 6378, "tls_enabled": True}},
        "guacamole_database": {
            "value": {
                "host": "10.40.0.10",
                "port": 5432,
                "database_name": "guacamole",
                "user_name": "guacamole",
            }
        },
        "public_ingress_ip_name": {"value": "shifter-gcp-dev-platform-ip"},
        "public_ingress_ip_address": {"value": "34.123.45.67"},
        "public_hostname": {"value": "portal.example.test"},
        "managed_tls_enabled": {"value": True},
        "cloud_armor_security_policy_name": {"value": "shifter-gcp-dev-edge"},
        "range_network_id": {"value": f"projects/{project_id}/global/networks/shifter-gcp-dev-range"},
        "range_network_cidr": {"value": "10.50.0.0/16"},
        "range_network_region": {"value": "us-central1"},
        "portal_network_cidrs": {"value": ["10.40.0.0/20", "10.44.0.0/16"]},
        "gke_services_cidr": {"value": "10.48.0.0/20"},
        "workload_service_accounts": {
            "value": {
                "portal": f"shiftergcpdev-portal@{project_id}.iam.gserviceaccount.com",
                "workers": f"shiftergcpdev-workers@{project_id}.iam.gserviceaccount.com",
                "ctf-scheduler": f"shiftergcpdev-ctf-scheduler@{project_id}.iam.gserviceaccount.com",
                "provisioner": f"shiftergcpdev-provisioner@{project_id}.iam.gserviceaccount.com",
            }
        },
    }


@pytest.fixture
def mock_stdin_tty():
    """Mock sys.stdin.isatty() to return True (interactive terminal)."""
    with patch("sys.stdin.isatty", return_value=True):
        yield


@pytest.fixture
def mock_stdin_non_tty():
    """Mock sys.stdin.isatty() to return False (non-interactive)."""
    with patch("sys.stdin.isatty", return_value=False):
        yield


@pytest.fixture(autouse=True)
def prevent_hanging_on_input():
    """Automatically mock input() to prevent tests from hanging.

    Individual tests should override this with their specific input values.
    """
    with patch("builtins.input", return_value=""):
        yield


@pytest.fixture(autouse=True)
def prevent_real_subprocess_calls():
    """Prevent any real subprocess calls from executing.

    This is a safety measure to ensure tests NEVER call real AWS, gh, git,
    terraform, or any other system commands. Individual tests must explicitly
    patch subprocess.run/call/check_output with their expected behavior.

    If a test tries to call subprocess without mocking, it will fail with
    a clear error message.
    """

    def safe_run(*args, **kwargs):
        # Allow only if explicitly mocked in test
        raise RuntimeError(
            f"Test attempted to call subprocess.run({args[0] if args else 'unknown'}) "
            f"without mocking! This could execute real commands. "
            f"Mock subprocess.run in your test."
        )

    with patch("subprocess.run", side_effect=safe_run):
        yield


@pytest.fixture
def bootstrap_config():
    """Return a valid BootstrapConfig for testing."""
    return deploy.BootstrapConfig(env="dev")


@pytest.fixture
def mock_repo_root(tmp_path):
    """Mock repository structure for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "platform").mkdir()
    (repo / "platform" / "terraform").mkdir()
    (repo / "platform" / "terraform" / "environments").mkdir()
    (repo / "platform" / "terraform" / "environments" / "dev").mkdir()
    (repo / "platform" / "terraform" / "environments" / "dev" / "portal").mkdir(parents=True)
    (repo / "platform" / "terraform" / "environments" / "dev" / "range").mkdir(parents=True)
    (repo / "platform" / "terraform" / "environments" / "prod").mkdir()
    (repo / "platform" / "terraform" / "environments" / "prod" / "portal").mkdir(parents=True)
    (repo / "platform" / "terraform" / "environments" / "prod" / "range").mkdir(parents=True)
    # global/iam for bootstrap_account tests
    (repo / "platform" / "terraform" / "global" / "iam").mkdir(parents=True)
    return repo


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run to return successful CompletedProcess.

    This overrides the autouse safety fixture for tests that need
    subprocess calls. Returns the mock for assertion purposes.
    """

    def smart_subprocess(cmd, **kwargs):
        # Return appropriate responses based on command
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

        # which gh - check if gh CLI is available
        if "which" in cmd_str and "gh" in cmd_str:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n", stderr="")
        # AWS OIDC provider list
        elif "list-open-id-connect-providers" in cmd_str:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com\n",
                stderr="",
            )
        # Terraform output -json
        elif "terraform" in cmd_str and "output" in cmd_str and "-json" in cmd_str:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"test_output": {"value": "test"}}', stderr=""
            )
        # Terraform show (for displaying plan)
        elif "terraform" in cmd_str and "show" in cmd_str:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="terraform plan output...", stderr="")
        # Git commands (add, commit, push) or gh secret set
        elif ("git" in cmd_str and any(x in cmd_str for x in ["add", "commit", "push"])) or (
            "gh" in cmd_str and "secret" in cmd_str and "set" in cmd_str
        ):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        # Default success
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=smart_subprocess) as mock:
        yield mock


# =============================================================================
# Test: check_dependencies()
# =============================================================================


# =============================================================================
# Split behavior tests
# =============================================================================


class TestGdcProjectResolution:
    """Tests for repo-root .env and env-var based GDC project discovery."""

    def test_prefers_runtime_environment_over_repo_env(self, tmp_path):
        """Process env vars should win over the repo-root .env file."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".env").write_text("PANW_GCP_DEV=from-dotenv\n")

        # clear=True so an ambient GCP_PROJECT_ID / GOOGLE_CLOUD_PROJECT /
        # GCLOUD_PROJECT (e.g. an authenticated gcloud config on a dev machine),
        # which get_default_gdc_project_id() checks ahead of PANW_GCP_DEV, does
        # not leak in and make this test non-hermetic.
        with (
            patch("deploy.get_repo_root", return_value=repo_root),
            patch.dict("os.environ", {"PANW_GCP_DEV": "from-env"}, clear=True),
        ):
            assert deploy.get_default_gdc_project_id() == "from-env"

    def test_reads_project_id_from_repo_env_when_runtime_env_missing(self, tmp_path):
        """The repo-root .env should be used when no explicit env var is set."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".env").write_text("PANW_GCP_DEV=prod-rwctxzl6shxk\n")

        with (
            patch("deploy.get_repo_root", return_value=repo_root),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert deploy.get_default_gdc_project_id() == "prod-rwctxzl6shxk"


class TestGdcBootstrapConfig:
    """Tests for deploy.GDCBootstrapConfig."""

    def test_derives_network_and_service_account_names(self):
        """Config should derive the default network, subnet, and service account names."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        assert config.resolved_network_name == "cluster1-gdc"
        assert config.resolved_subnetwork_name == "cluster1-gdc-us-central1"
        assert config.service_account_email == "baremetal-gcr@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        assert config.gdc_access_secret_id == "shifter-gcp-dev-gdc-access"
        assert config.gdc_vm_image_gcs_secret_id == "shifter-gcp-dev-gdc-vm-image-gcs"

    def test_exposes_expected_cluster_hosts(self):
        """Config should expose the expected workstation, control-plane, and worker hosts."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        assert config.workstation.name == "cluster1-abm-ws0-001"
        assert [host.vxlan_ip for host in config.control_plane_hosts] == ["10.200.0.3", "10.200.0.4", "10.200.0.5"]
        assert [host.vxlan_ip for host in config.worker_hosts] == ["10.200.0.6", "10.200.0.7"]


class TestGdcRenderers:
    """Tests for the generated GDC bootstrap assets."""

    def test_cluster_config_includes_multi_network_and_vmruntime_prereqs(self):
        """The generated cluster config should include the validated networking settings."""
        config = deploy.GDCBootstrapConfig(
            project_id="prod-rwctxzl6shxk",
            cluster_id="cluster1",
            google_account_email="admin@example.com",
        )

        rendered = deploy.render_gdc_cluster_config(config)

        assert "multipleNetworkInterfaces: true" in rendered
        assert "controlPlaneVIP: 10.200.0.49" in rendered
        assert "ingressVIP: 10.200.0.50" in rendered
        assert "clusterAdmin:" in rendered
        assert "admin@example.com" in rendered

    def test_prepare_hosts_script_bakes_in_vxlan_and_inotify_fix(self):
        """The host prep script should contain both the vxlan setup and the inotify hardening."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.render_gdc_prepare_hosts_script(config)

        assert "ip link add vxlan0 type vxlan id 42" in rendered
        assert "fs.inotify.max_user_instances = 1024" in rendered
        assert 'configure_remote_host "10.240.0.3" "10.200.0.3"' in rendered
        # accept-new pins the host key on first contact for freshly created VMs
        # without the silent-MITM exposure of `no`.
        assert "StrictHostKeyChecking=accept-new" in rendered
        assert "StrictHostKeyChecking=no" not in rendered
        assert "UserKnownHostsFile=/dev/null" not in rendered

    def test_prepare_workstation_script_installs_staged_bmctl(self):
        """The workstation prep must install the pinned staged bmctl binary, not curl it remotely."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.render_gdc_prepare_workstation_script(config)

        assert f"install -m 755 {config.staging_bundle_dir}/bmctl /usr/local/sbin/bmctl" in rendered
        assert "anthos-baremetal-release" not in rendered
        assert "StrictHostKeyChecking accept-new" in rendered
        assert "StrictHostKeyChecking no" not in rendered
        assert "UserKnownHostsFile /dev/null" not in rendered

    def test_rendered_gdc_shell_scripts_parse_with_bash(self, tmp_path):
        """Rendered bootstrap shell scripts must be syntactically valid bash."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        rendered_scripts = {
            "prepare-workstation.sh": deploy.render_gdc_prepare_workstation_script(config),
            "prepare-hosts.sh": deploy.render_gdc_prepare_hosts_script(config),
            "create-cluster.sh": deploy.render_gdc_create_cluster_script(config),
            "install-helper.sh": deploy.render_gdc_install_helper_script(config),
        }

        for name, rendered in rendered_scripts.items():
            script_path = tmp_path / name
            script_path.write_text(rendered)
            process = subprocess.Popen(
                ["bash", "-n", str(script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate()
            assert process.returncode == 0, f"{name} failed bash -n: {stdout}{stderr}"

    def test_create_cluster_script_is_safe_to_rerun(self):
        """The cluster create script should skip cluster creation if the kubeconfig already exists."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.render_gdc_create_cluster_script(config)

        assert f"if [ ! -f {config.kubeconfig_path} ]" in rendered
        assert "bmctl check vmruntimepfc" in rendered
        assert "patch vmruntime vmruntime" in rendered

    def test_build_gdc_access_secret_payload_contains_cluster_and_vxlan_details(self):
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.build_gdc_access_secret_payload(config, "apiVersion: v1\nclusters: []\n")

        assert '"cluster_id": "cluster1"' in rendered
        assert '"vxlan_cidr": "10.200.0.0/24"' in rendered
        assert '"network_interface": "vxlan0"' in rendered


class TestRewriteGdcKubeconfig:
    """Tests for repointing the provisioner kubeconfig at the platform LB."""

    _BMCTL_KUBECONFIG = (
        "apiVersion: v1\n"
        "clusters:\n"
        "- cluster:\n"
        "    certificate-authority-data: QUFB\n"
        "    server: https://10.200.0.49:443\n"
        "  name: cluster1\n"
        "contexts:\n"
        "- context:\n"
        "    cluster: cluster1\n"
        "    user: cluster1-admin\n"
        "  name: cluster1-admin@cluster1\n"
        "current-context: cluster1-admin@cluster1\n"
        "users:\n"
        "- name: cluster1-admin\n"
        "  user:\n"
        "    client-certificate-data: Q0ND\n"
        "    client-key-data: S0tL\n"
    )

    def test_repoints_server_and_drops_ca_for_lb_endpoint(self):
        rewritten = deploy.rewrite_gdc_kubeconfig_for_platform_access(self._BMCTL_KUBECONFIG, "10.240.0.8")

        assert "    server: https://10.240.0.8:6444" in rewritten
        assert "    insecure-skip-tls-verify: true" in rewritten
        assert "certificate-authority-data" not in rewritten
        assert "10.200.0.49" not in rewritten
        assert "client-certificate-data: Q0ND" in rewritten
        assert "client-key-data: S0tL" in rewritten
        assert "current-context: cluster1-admin@cluster1" in rewritten

    def test_honors_explicit_port_in_endpoint(self):
        rewritten = deploy.rewrite_gdc_kubeconfig_for_platform_access(self._BMCTL_KUBECONFIG, "10.240.0.8:8443")

        assert "    server: https://10.240.0.8:8443" in rewritten

    def test_sync_rewrites_when_endpoint_configured(self):
        config = deploy.GDCBootstrapConfig(
            project_id="prod-rwctxzl6shxk",
            cluster_id="cluster1",
            control_plane_platform_endpoint="10.240.0.8",
        )
        captured: dict[str, str] = {}

        def fake_subprocess_run(cmd, *args, **kwargs):
            if cmd[:3] == ["gcloud", "secrets", "describe"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd[:3] == ["gcloud", "compute", "ssh"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=self._BMCTL_KUBECONFIG, stderr="")
            if cmd[:4] == ["gcloud", "secrets", "versions", "access"]:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="NOT_FOUND: version not found")
            if cmd[:4] == ["gcloud", "secrets", "versions", "add"] and "--data-file" in cmd:
                captured["payload"] = Path(cmd[cmd.index("--data-file") + 1]).read_text()
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("deploy.subprocess.run", side_effect=fake_subprocess_run):
            deploy.sync_gdc_access_secret(config)

        assert "10.240.0.8:6444" in captured["payload"]
        assert "insecure-skip-tls-verify" in captured["payload"]
        assert "10.200.0.49" not in captured["payload"]


class TestGdcBootstrapCluster:
    """Tests for deploy.gdc_bootstrap_cluster."""

    def test_executes_bootstrap_steps_in_order(self, tmp_path):
        """The GDC bootstrap path should execute the expected sequence of helper steps."""
        # range_backend="gdc" is what builds the ABM/GDC substrate (#1716); the gce
        # default skips it and is covered by TestGdcBootstrapRangeBackend.
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1", range_backend="gdc")
        staged_assets = {
            "assets_dir": tmp_path / "cluster1",
            "ssh_metadata": tmp_path / "cluster1" / "ssh-metadata",
            "service_account_key": tmp_path / "cluster1" / "bm-gcr.json",
        }

        with (
            patch("deploy.confirm", return_value=True),
            patch("deploy.ensure_gdc_apis") as mock_apis,
            patch("deploy.ensure_gdc_service_account") as mock_sa,
            patch("deploy.stage_gdc_bootstrap_assets", return_value=staged_assets) as mock_stage,
            patch("deploy.ensure_gdc_network") as mock_network,
            patch("deploy.ensure_gdc_instances") as mock_instances,
            patch("deploy.sync_gdc_instance_ssh_metadata") as mock_sync,
            patch("deploy.wait_for_gdc_ssh") as mock_wait,
            patch("deploy.upload_gdc_assets") as mock_upload,
            patch("deploy.run_gdc_workstation_script") as mock_remote,
            patch("deploy.sync_gdc_access_secret") as mock_access_secret,
            patch("deploy.sync_gdc_vm_image_secret") as mock_vm_image_secret,
            patch(
                "deploy.bootstrap_gcp_control_plane",
                return_value=_sample_gcp_control_plane_outputs(),
            ) as mock_platform,
        ):
            result = deploy.gdc_bootstrap_cluster(config)

            assert result["cluster_id"] == "cluster1"
            mock_apis.assert_called_once_with(config, dry_run=False)
            mock_sa.assert_called_once_with(config, dry_run=False)
            mock_stage.assert_called_once()
            mock_network.assert_called_once_with(config, dry_run=False)
            mock_instances.assert_called_once_with(config, staged_assets["ssh_metadata"], dry_run=False)
            mock_sync.assert_called_once_with(config, staged_assets["ssh_metadata"], dry_run=False)
            assert mock_wait.call_count == len(config.all_hosts)
            mock_upload.assert_called_once_with(config, staged_assets["assets_dir"], dry_run=False)
            assert [call.args[1] for call in mock_remote.call_args_list] == [
                "prepare-workstation.sh",
                "prepare-hosts.sh",
                "create-cluster.sh",
                "install-helper.sh",
            ]
            mock_access_secret.assert_called_once_with(config, dry_run=False)
            mock_vm_image_secret.assert_called_once_with(config, staged_assets["service_account_key"], dry_run=False)
            mock_platform.assert_called_once_with(config, dry_run=False)
            assert result["gdc_access_secret_id"] == "shifter-gcp-dev-gdc-access"
            assert result["gdc_vm_image_gcs_secret_id"] == "shifter-gcp-dev-gdc-vm-image-gcs"
            assert result["gke_cluster_name"] == "shifter-gcp-dev-platform"


class TestGdcClusterAccessHardening:
    """Tests for the private GDC admin path."""

    def test_instance_create_uses_private_network_only(self, tmp_path):
        """GDC hosts must not receive public IP addresses."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        cmd = deploy.gdc_instance_create_command(config, config.workstation, tmp_path / "ssh-metadata")

        assert "--no-address" in cmd

    def test_wait_for_gdc_ssh_uses_iap_tunnel(self):
        """Bootstrap SSH probes must go through IAP instead of direct public SSH."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        ready = subprocess.CompletedProcess(["gcloud"], 0, stdout="ready", stderr="")

        with patch("deploy.subprocess.run", return_value=ready) as mock_run:
            deploy.wait_for_gdc_ssh(config, config.workstation)

        cmd = mock_run.call_args.args[0]
        assert cmd[:3] == ["gcloud", "compute", "ssh"]
        assert "--tunnel-through-iap" in cmd

    def test_run_gdc_workstation_script_uses_iap_tunnel(self):
        """Remote workstation scripts must go through IAP."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch("deploy.run_cmd") as mock_run_cmd:
            deploy.run_gdc_workstation_script(config, "prepare-workstation.sh")

        assert mock_run_cmd.call_args.args[0] == [
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
            f"bash {config.staging_dir}/{config.cluster_id}/prepare-workstation.sh",
        ]

    def test_fetch_gdc_kubeconfig_uses_iap_tunnel(self):
        """Kubeconfig fetches must go through IAP."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch(
            "deploy.run_cmd",
            return_value=subprocess.CompletedProcess(["gcloud"], 0, stdout="apiVersion: v1\n", stderr=""),
        ) as mock_run_cmd:
            deploy.fetch_gdc_kubeconfig(config)

        assert mock_run_cmd.call_args.args[0] == [
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
        ]

    def test_ensure_gdc_network_locks_ssh_to_iap_and_lb_to_internal_subnet(self):
        """The GDC network must not expose SSH or LB/admin ports to the internet."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with (
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gdc_network(config)

        firewall_creates = [
            call.args[0]
            for call in mock_run_cmd.call_args_list
            if call.args[0][:4] == ["gcloud", "compute", "firewall-rules", "create"]
        ]
        assert any(cmd[4] == config.ssh_firewall_rule_name and "35.235.240.0/20" in cmd for cmd in firewall_creates)
        assert any(cmd[4] == config.lb_firewall_rule_name and config.subnet_cidr in cmd for cmd in firewall_creates)

    def test_ensure_gdc_network_provisions_cloud_nat_for_private_host_egress(self):
        """Private GDC hosts must get outbound internet access through Cloud NAT."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with (
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gdc_network(config)

        router_create = next(
            call.args[0]
            for call in mock_run_cmd.call_args_list
            if call.args[0][:4] == ["gcloud", "compute", "routers", "create"]
        )
        nat_create = next(
            call.args[0]
            for call in mock_run_cmd.call_args_list
            if call.args[0][:5] == ["gcloud", "compute", "routers", "nats", "create"]
        )

        assert router_create == [
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
        ]
        assert nat_create == [
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
        ]


class TestGdcControlPlaneRollout:
    """Tests for deploying Shifter onto GKE through Helm."""

    def test_rollout_sequence_fetches_credentials_and_runs_atomic_helm_release(self, tmp_path):
        """The rollout path must fetch cluster credentials and perform one atomic Helm release."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values_path = tmp_path / "values.json"
        values_path.write_text("{}")
        chart_dir = Path(__file__).resolve().parents[3] / "platform" / "charts" / "shifter"
        environment_values_path = chart_dir / "values-gcp-dev.yaml"

        def subprocess_run(cmd, **kwargs):
            if cmd[:4] == ["gcloud", "secrets", "versions", "access"]:
                secret_name = cmd[cmd.index("--secret") + 1]
                if secret_name == "shifter-gcp-dev-guacamole-db":
                    return subprocess.CompletedProcess(cmd, 0, stdout='{"username":"guac","password":"supersecret"}')
                if secret_name == "shifter-gcp-dev-guacamole-json-auth":
                    return subprocess.CompletedProcess(cmd, 0, stdout="json-auth-key\n")
            if cmd == ["kubectl", "apply", "-f", "-"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="secret/guacamole-runtime configured\n", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=f"unexpected command: {cmd}")

        with (
            patch("deploy.run_cmd") as mock_run_cmd,
            patch("deploy.subprocess.run", side_effect=subprocess_run),
            patch("deploy.ensure_gke_gcloud_auth_plugin") as mock_ensure_plugin,
            patch("deploy.prepare_gcp_helm_cutover") as mock_prepare_cutover,
            patch("deploy.ensure_gcp_control_plane_namespaces") as mock_ensure_namespaces,
            patch("deploy.get_repo_root", return_value=Path(__file__).resolve().parents[3]),
        ):
            deploy.deploy_gcp_control_plane_with_helm(config, outputs, values_path)

        mock_ensure_plugin.assert_called_once_with(dry_run=False)
        mock_prepare_cutover.assert_called_once_with(dry_run=False)
        mock_ensure_namespaces.assert_called_once_with(dry_run=False)
        commands = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert commands[0] == [
            "gcloud",
            "container",
            "fleet",
            "memberships",
            "get-credentials",
            "shifter-gcp-dev-platform",
            "--location",
            "us-central1",
            "--project",
            "prod-rwctxzl6shxk",
        ]
        assert commands[1] == [
            "helm",
            "upgrade",
            "--install",
            "shifter",
            str(chart_dir),
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
        ]
        assert commands[2] == [
            "kubectl",
            "-n",
            "shifter-platform",
            "rollout",
            "restart",
            "deployment/guacamole-client",
        ]
        assert commands[3] == [
            "kubectl",
            "-n",
            "shifter-platform",
            "rollout",
            "status",
            "deployment/guacamole-client",
            "--timeout=5m",
        ]

    def test_bootstrap_control_plane_creates_operator_before_helm_and_waits_for_dns_tls_after_release(self):
        """Bootstrap must seed Identity Platform before Helm and only finish after DNS/TLS verification."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        calls: list[str] = []

        def record(name: str):
            def _inner(*args, **kwargs):
                calls.append(name)
                if name == "apply":
                    return outputs
                if name == "stage":
                    return Path("shifter.values.generated.json")
                return None

            return _inner

        with (
            patch("deploy.apply_gcp_control_plane_terraform", side_effect=record("apply")),
            patch("deploy.ensure_gcp_identity_platform_operator", side_effect=record("seed_operator")),
            patch("deploy.push_gcp_control_plane_images", side_effect=record("push_images")),
            patch("deploy.stage_gcp_control_plane_values", side_effect=record("stage")),
            patch("deploy.deploy_gcp_control_plane_with_helm", side_effect=record("deploy")),
            patch("deploy.walkthrough_gcp_dns_setup_and_wait_for_tls", side_effect=record("dns_tls")),
            patch.dict(os.environ, {"SHIFTER_IMAGE_TAG": PINNED_IMAGE_TAG}),
        ):
            result = deploy.bootstrap_gcp_control_plane(config)

        assert result == outputs
        assert calls == ["apply", "seed_operator", "push_images", "stage", "deploy", "dns_tls"]


class TestGdcBootstrapPrerequisites:
    """Tests for GDC bootstrap IAM and API prerequisites."""

    def test_gdc_api_enablement_includes_cloud_storage(self):
        """Bootstrap must enable the Cloud Storage API used by GDC workflows."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch("deploy.run_cmd") as mock_run_cmd:
            deploy.ensure_gdc_apis(config)

        enable_call = mock_run_cmd.call_args_list[1]
        assert enable_call.args[0][:3] == ["gcloud", "services", "enable"]
        enabled_services = set(enable_call.args[0])
        assert {"storage.googleapis.com", "iap.googleapis.com"}.issubset(enabled_services)

    def test_gdc_service_account_grants_compute_viewer_for_bmctl(self):
        """The bootstrap service account must be able to read Compute zone metadata for bmctl."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with (
            patch("deploy.gcloud_resource_exists", return_value=True),
            patch("deploy.run_cmd"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(["gcloud"], 0, stdout="", stderr=""),
            ) as mock_subprocess,
        ):
            deploy.ensure_gdc_service_account(config)

        granted_roles = [call.args[0][7] for call in mock_subprocess.call_args_list]
        assert "roles/compute.viewer" in granted_roles

    def test_gdc_service_account_waits_for_visibility_after_create(self):
        """First-run bootstrap must wait for service-account propagation before IAM bindings."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with (
            patch("deploy.gcloud_resource_exists", side_effect=[False, False, False, True]),
            patch("deploy.run_cmd") as mock_run_cmd,
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(["gcloud"], 0, stdout="", stderr=""),
            ) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.ensure_gdc_service_account(config)

        assert mock_run_cmd.call_args_list[0].args[0][:4] == [
            "gcloud",
            "iam",
            "service-accounts",
            "create",
        ]
        assert any(
            call.args[0][0:3] == ["gcloud", "projects", "add-iam-policy-binding"]
            for call in mock_subprocess.call_args_list
        )
        assert mock_sleep.call_count == 2


class TestGdcBootstrapAssetUpload:
    """Tests for staging the GDC bootstrap bundle on the workstation."""

    def test_creates_remote_staging_directory_before_recursive_scp(self, tmp_path):
        """The uploader must replace the staged bundle and transfer it through IAP."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        assets_dir = tmp_path / "cluster1"
        assets_dir.mkdir()

        with patch("deploy.run_cmd") as mock_run_cmd:
            deploy.upload_gdc_assets(config, assets_dir)

        mkdir_call = mock_run_cmd.call_args_list[0]
        assert mkdir_call.args[0] == [
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
        ]
        assert mkdir_call.kwargs == {"dry_run": False}

        scp_call = mock_run_cmd.call_args_list[1]
        assert scp_call.args[0] == [
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
        ]
        assert scp_call.kwargs == {"dry_run": False}


class TestGdcStagedAssets:
    """Tests for the local GDC bootstrap bundle assembly."""

    def test_reuses_existing_workstation_credentials_when_present(self, tmp_path):
        """Reruns must reuse the workstation bootstrap credentials instead of minting fresh ones."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        existing_material = {
            "private_key": "PRIVATE KEY\n",
            "public_key": "ssh-rsa AAAAexisting bootstrap@ws\n",
            "service_account_key": '{"private_key_id":"d6edc4b1cc096f95b105b810d838e786b040a3e9"}\n',
        }

        def fake_run_cmd(cmd, *args, **kwargs):
            if cmd[:3] == ["gcloud", "storage", "cp"]:
                Path(cmd[4]).write_text("bmctl-binary")
            return None

        with (
            patch("deploy._fetch_existing_gdc_bootstrap_material", return_value=existing_material),
            patch("deploy.run_cmd", side_effect=fake_run_cmd) as mock_run_cmd,
        ):
            staged_assets = deploy.stage_gdc_bootstrap_assets(config, tmp_path)

        assert staged_assets["private_key"].read_text() == "PRIVATE KEY\n"
        assert staged_assets["public_key"].read_text() == "ssh-rsa AAAAexisting bootstrap@ws\n"
        assert (
            staged_assets["service_account_key"].read_text()
            == '{"private_key_id":"d6edc4b1cc096f95b105b810d838e786b040a3e9"}\n'
        )
        executed = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert ["ssh-keygen", "-t", "rsa", "-N", "", "-f", str(staged_assets["private_key"])] not in executed
        assert not any(cmd[:5] == ["gcloud", "iam", "service-accounts", "keys", "create"] for cmd in executed)

    def test_stages_bmctl_binary_from_gcs_into_bundle(self, tmp_path):
        """Asset staging must fetch the pinned bmctl binary into the uploaded bundle."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        def fake_run_cmd(cmd, *args, **kwargs):
            if cmd[:4] == ["ssh-keygen", "-t", "rsa", "-N"]:
                private_key = Path(cmd[-1])
                private_key.write_text("PRIVATE KEY\n")
                private_key.with_suffix(".pub").write_text("ssh-rsa AAAATESTKEY\n")
            elif cmd[:5] == ["gcloud", "iam", "service-accounts", "keys", "create"]:
                Path(cmd[5]).write_text('{"type": "service_account"}\n')
            elif cmd[:3] == ["gcloud", "storage", "cp"]:
                Path(cmd[4]).write_text("bmctl-binary")
            return None

        with (
            patch("deploy._fetch_existing_gdc_bootstrap_material", return_value=None),
            patch("deploy.run_cmd", side_effect=fake_run_cmd) as mock_run_cmd,
        ):
            staged_assets = deploy.stage_gdc_bootstrap_assets(config, tmp_path)

        assert staged_assets["bmctl_binary"].read_text() == "bmctl-binary"
        assert mock_run_cmd.call_args_list[2].args[0] == [
            "gcloud",
            "storage",
            "cp",
            config.bmctl_gcs_source,
            str(staged_assets["bmctl_binary"]),
        ]


class TestGdcRerunSafety:
    """Tests for rerun-safe secret and metadata synchronization."""

    def test_sync_instance_ssh_metadata_skips_hosts_already_in_sync(self, tmp_path):
        """Instance metadata writes should be skipped when the expected key is already present."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        metadata_path = tmp_path / "ssh-metadata"
        metadata_path.write_text("root:ssh-rsa AAAAexisting atomik@Phoenix\n")

        with (
            patch("deploy.get_gdc_instance_ssh_metadata") as mock_get_metadata,
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            mock_get_metadata.side_effect = [
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
                "root:ssh-rsa AAAAdifferent atomik@Phoenix",
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
            ]

            deploy.sync_gdc_instance_ssh_metadata(config, metadata_path)

        assert mock_run_cmd.call_count == 1
        assert "cluster1-abm-cp1-001" in mock_run_cmd.call_args.args[0]

    def test_sync_gdc_access_secret_skips_unchanged_payload(self):
        """Bootstrap should not add a new secret version when the access payload is unchanged."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        payload = deploy.build_gdc_access_secret_payload(config, "apiVersion: v1\nclusters: []\n")

        with (
            patch("deploy.ensure_gdc_access_secret"),
            patch("deploy.fetch_gdc_kubeconfig", return_value="apiVersion: v1\nclusters: []\n"),
            patch("deploy.get_latest_gcp_secret_payload", return_value=payload),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.sync_gdc_access_secret(config)

        mock_run_cmd.assert_not_called()

    def test_sync_gdc_vm_image_secret_skips_unchanged_payload(self, tmp_path):
        """Bootstrap should not add a new VM image secret version when the key payload is unchanged."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        key_path = tmp_path / "bm-gcr.json"
        key_path.write_text('{"private_key_id":"d6edc4b1cc096f95b105b810d838e786b040a3e9"}\n')

        with (
            patch("deploy.ensure_gdc_vm_image_secret"),
            patch(
                "deploy.get_latest_gcp_secret_payload",
                return_value='{"private_key_id":"d6edc4b1cc096f95b105b810d838e786b040a3e9"}\n',
            ),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.sync_gdc_vm_image_secret(config, key_path)

        mock_run_cmd.assert_not_called()
