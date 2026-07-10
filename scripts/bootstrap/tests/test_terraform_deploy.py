"""Behavior tests split from deploy.py: test_terraform_deploy.py.

Tests verify the complete contract for each function:
1. Inputs - minimum required data and validation
2. Outputs - return values and data structures
3. Side effects - subprocess calls, file writes, system changes
4. Errors - error handling and propagation
5. Logging - debug and error logging

All external dependencies are mocked. No actual AWS calls, file operations,
or subprocess executions occur during tests.
"""

import subprocess
from unittest.mock import patch

import pytest

import deploy
import terraform_backend as tb

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


class TestTerraformDeploy:
    """Tests for deploy.terraform_deploy."""

    @pytest.fixture(autouse=True)
    def _terraform_backend_setup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TF_INFRA_STATE_BUCKET", "test-bucket")
        instance_dir = tmp_path / "instance"
        monkeypatch.setenv("SHIFTER_INSTANCE_DIR", str(instance_dir))
        tb.write_instance_backend_configs(
            backend_dir=tb.resolve_instance_backend_dir(
                env="dev",
                bucket="test-bucket",
                instance_dir=instance_dir,
            ),
            env="dev",
            bucket="test-bucket",
            region="us-east-2",
        )
        tb.write_portal_remote_state_tfvars(
            instance_dir=instance_dir,
            env="dev",
            bucket="test-bucket",
            region="us-east-2",
        )
        yield

    # ---------------------------------------------------------------------
    # Happy path - successful deployment
    # ---------------------------------------------------------------------

    def test_runs_terraform_init_for_all_components(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function runs terraform init for core, portal, and range."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):
            deploy.terraform_deploy("dev", "my-profile")

            # Should call terraform init 3 times (core, portal, range)
            init_calls = [
                c
                for c in mock_subprocess.call_args_list
                if c.args and len(c.args[0]) >= 2 and c.args[0][0:2] == ["terraform", "init"]
            ]
            assert len(init_calls) == 3

    def test_runs_terraform_plan_for_all_components(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function runs terraform plan for core, portal, and range."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):
            deploy.terraform_deploy("dev", "my-profile")

            # Should call terraform plan 3 times (not show or apply)
            plan_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and c[0][0][0] == "terraform"
                and len(c[0][0]) > 1
                and c[0][0][1] == "plan"
            ]
            assert len(plan_calls) == 3

    def test_runs_terraform_apply_when_user_confirms(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function runs terraform apply when user confirms."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):
            mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}")

            deploy.terraform_deploy("dev", "my-profile")

            # Should call terraform apply 3 times
            apply_calls = [
                c
                for c in mock_subprocess.call_args_list
                if c.args and len(c.args[0]) >= 2 and c.args[0][0:2] == ["terraform", "apply"]
            ]
            assert len(apply_calls) == 3

    def test_captures_terraform_outputs(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function captures terraform output as JSON."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):
            result = deploy.terraform_deploy("dev", "my-profile")

            assert isinstance(result, dict)
            # Result should contain outputs from all components

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_terraform_init_fails(self, mock_repo_root, mock_stdin_tty):
        """Function exits when terraform init fails."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("os.chdir"),
            patch("subprocess.run") as mock_run,
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "init" in cmd_str:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = run_side_effect

            with pytest.raises(SystemExit):
                deploy.terraform_deploy("dev", "my-profile")

    def test_exits_when_terraform_plan_fails(self, mock_repo_root, mock_stdin_tty):
        """Function exits when terraform plan fails."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("os.chdir"),
            patch("subprocess.run") as mock_run,
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "plan" in cmd_str:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = run_side_effect

            with pytest.raises(SystemExit):
                deploy.terraform_deploy("dev", "my-profile")

    def test_exits_when_user_refuses_terraform_apply(self, mock_repo_root, mock_stdin_tty):
        """Function exits when user refuses to apply terraform."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("subprocess.run") as mock_run,
            patch("builtins.input", return_value="n"),  # user refuses
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

            with pytest.raises(SystemExit) as exc_info:
                deploy.terraform_deploy("dev", "my-profile")

            assert exc_info.value.code == 1

    def test_exits_when_terraform_apply_fails(self, mock_repo_root, mock_stdin_tty):
        """Function exits when terraform apply fails."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("subprocess.run") as mock_run,
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "apply" in cmd_str:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = run_side_effect

            with pytest.raises(SystemExit):
                deploy.terraform_deploy("dev", "my-profile")

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_execute_terraform_in_dry_run(self, mock_repo_root, mock_subprocess):
        """Function does not execute terraform commands in dry-run."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("os.chdir"),
        ):
            deploy.terraform_deploy("dev", "my-profile", dry_run=True)

            # In dry-run, terraform init/plan are routed through run_cmd(dry_run=True)
            # and apply is skipped, so no terraform command reaches the boundary.
            mock_subprocess.assert_not_called()

    # ---------------------------------------------------------------------
    # Component ordering
    # ---------------------------------------------------------------------

    def test_deploys_components_in_correct_order(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function deploys core before portal and range."""
        component_order = []

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir") as mock_chdir,
        ):
            mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}")

            def capture_chdir(path):
                path_str = str(path)
                if "environments/dev" in path_str and "portal" not in path_str and "range" not in path_str:
                    component_order.append("core")
                elif "portal" in path_str:
                    component_order.append("portal")
                elif "range" in path_str:
                    component_order.append("range")

            mock_chdir.side_effect = capture_chdir

            deploy.terraform_deploy("dev", "my-profile")

            # Core should be first
            assert component_order[0] == "core"
            # Portal and range can be in any order after core
            assert set(component_order[1:]) == {"portal", "range"}
