"""Behavior tests split from deploy.py: test_aws_bootstrap.py.

Tests verify the complete contract for each function:
1. Inputs - minimum required data and validation
2. Outputs - return values and data structures
3. Side effects - subprocess calls, file writes, system changes
4. Errors - error handling and propagation
5. Logging - debug and error logging

All external dependencies are mocked. No actual AWS calls, file operations,
or subprocess executions occur during tests.
"""

import json
import subprocess
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


class TestBootstrapAccount:
    """Tests for deploy.bootstrap_account."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_creates_s3_bucket_for_terraform_state(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function creates S3 bucket for state storage."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call aws s3 mb
            s3_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "s3" in " ".join(c[0][0])
            ]
            assert len(s3_calls) > 0

    def test_does_not_create_dynamodb_table(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """State locking uses S3 native (use_lockfile = true), so no DynamoDB calls."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            dynamo_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "dynamodb" in " ".join(c[0][0])
            ]
            assert dynamo_calls == []

    def test_runs_terraform_to_create_oidc_and_role(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function runs Terraform to create OIDC provider and production IAM role."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
            patch("os.chdir"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call terraform init and apply
            terraform_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "terraform"
            ]
            assert len(terraform_calls) > 0

    def test_creates_iam_role_for_github_actions(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function creates IAM role for GitHub Actions."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call aws iam create-role
            role_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "create-role" in " ".join(c[0][0])
            ]
            assert len(role_calls) > 0

    def test_adds_admin_policy_to_bootstrap_role(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function adds AdministratorAccess-equivalent permissions to bootstrap role."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
            patch("os.chdir"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call put-role-policy with AdministratorAccess-equivalent policy
            policy_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and c[0][0][0] == "aws"
                and "put-role-policy" in " ".join(c[0][0])
                and "bootstrap-administrator-access" in " ".join(c[0][0])
            ]
            assert len(policy_calls) > 0

    def test_returns_dict_with_bootstrap_results(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function returns dictionary with resource ARNs and names."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            result = deploy.bootstrap_account(bootstrap_config, "my-profile")

            assert isinstance(result, dict)
            assert "role_arn" in result
            assert "bucket_name" in result
            assert result["state_bucket_secret_name"] == "TF_INFRA_STATE_BUCKET_DEV"

    def test_uses_correct_github_org_and_repo_in_trust_policy(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function includes correct GitHub org/repo in IAM trust policy."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            bootstrap_config.github_org = "test-org"
            bootstrap_config.github_repo = "test-repo"
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Find the create-role call
            role_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 1 and "create-role" in " ".join(c[0][0])
            ]
            assert len(role_calls) > 0

            # The trust policy should be in the command args
            cmd_args = role_calls[0][0][0]
            policy_json = None
            for i, arg in enumerate(cmd_args):
                if arg == "--assume-role-policy-document":
                    policy_json = cmd_args[i + 1]
                    break

            assert policy_json is not None
            policy = json.loads(policy_json)
            # Policy should reference the GitHub repo
            policy_str = json.dumps(policy)
            assert "test-org" in policy_str
            assert "test-repo" in policy_str

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_create_resources_in_dry_run(self, bootstrap_config, mock_repo_root):
        """Function does not execute AWS commands in dry-run mode."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile", dry_run=True)

            # In dry-run, every AWS/IAM command is routed through run_cmd(dry_run=True),
            # which short-circuits before subprocess.run, so nothing reaches the boundary.
            mock_run.assert_not_called()

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_s3_bucket_creation_fails(self, bootstrap_config, mock_repo_root):
        """Function exits when S3 bucket creation fails."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["aws", "s3", "mb"])

            with pytest.raises(SystemExit):
                deploy.bootstrap_account(bootstrap_config, "my-profile")

    def test_exits_when_iam_role_creation_fails(self, bootstrap_config, mock_repo_root):
        """Function exits when IAM role creation fails."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            # Succeed for S3 and DynamoDB, fail for IAM
            def side_effect(cmd, **kwargs):
                if "create-role" in cmd:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = side_effect

            with pytest.raises(SystemExit):
                deploy.bootstrap_account(bootstrap_config, "my-profile")

    # ---------------------------------------------------------------------
    # Profile injection
    # ---------------------------------------------------------------------

    def test_passes_profile_to_all_aws_commands(self, bootstrap_config, mock_repo_root):
        """Function passes profile parameter to all AWS CLI calls."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                # Return OIDC ARN for list-open-id-connect-providers
                if "list-open-id-connect-providers" in cmd_str:
                    return subprocess.CompletedProcess(
                        args=cmd,
                        returncode=0,
                        stdout=("arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com\n"),
                    )
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="")

            mock_run.side_effect = run_side_effect

            deploy.bootstrap_account(bootstrap_config, "test-profile")

            # All AWS commands should have --profile in their args
            aws_calls = [
                c for c in mock_run.call_args_list if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws"
            ]
            for call_args in aws_calls:
                cmd = call_args[0][0]
                assert "--profile" in cmd
                assert "test-profile" in cmd
