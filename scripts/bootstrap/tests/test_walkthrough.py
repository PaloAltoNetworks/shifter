"""Behavior tests split from deploy.py: test_walkthrough.py.

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


class TestWalkthroughGithubSecrets:
    """Tests for deploy.walkthrough_github_secrets."""

    @staticmethod
    def _bootstrap_result(**overrides):
        base = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "state_bucket_secret_name": "TF_INFRA_STATE_BUCKET_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
            "bucket_name": "shifter-dev-infra-test-bucket",
        }
        base.update(overrides)
        return base

    # ---------------------------------------------------------------------
    # Happy path - automated with gh CLI
    # ---------------------------------------------------------------------

    def test_sets_secret_via_gh_cli_when_user_confirms(self, bootstrap_config, mock_stdin_tty):
        """Function sets GitHub secret using gh CLI when automated."""
        bootstrap_result = self._bootstrap_result()

        with (
            patch("builtins.input", return_value="y"),
            patch("subprocess.run") as mock_run,
        ):

            def mock_subprocess_run(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "which" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n", stderr="")
                elif "gh" in cmd_str and "secret" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = mock_subprocess_run

            deploy.walkthrough_github_secrets(bootstrap_result)

            # Should call gh secret set
            gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
            assert len(gh_calls) > 0
            # Find the set call
            set_calls = [c for c in gh_calls if "set" in c[0][0]]
            assert len(set_calls) == 2

    def test_passes_role_arn_to_gh_secret_stdin(self, bootstrap_config, mock_stdin_tty):
        """Function passes the role ARN to gh over stdin, not argv."""
        bootstrap_result = self._bootstrap_result()

        with (
            patch("builtins.input", return_value="y"),
            patch("subprocess.run") as mock_run,
        ):

            def mock_subprocess_run(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "which" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n", stderr="")
                elif "gh" in cmd_str and "secret" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = mock_subprocess_run

            deploy.walkthrough_github_secrets(bootstrap_result)

            # Find the gh secret set call
            gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh" and "set" in c[0][0]]
            assert len(gh_calls) > 0

            cmd = gh_calls[0][0][0]
            assert "arn:aws:iam::123456789012:role/test-role" not in " ".join(cmd)
            assert gh_calls[0].kwargs["input"] == "arn:aws:iam::123456789012:role/test-role"

    # ---------------------------------------------------------------------
    # Manual fallback
    # ---------------------------------------------------------------------

    def test_provides_manual_instructions_when_gh_not_available(self, capsys, mock_stdin_tty):
        """Function shows manual instructions when gh CLI not found."""
        bootstrap_result = self._bootstrap_result()

        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.wait_for_user") as mock_wait,
        ):
            # Make "which gh" return non-zero (not found)
            mock_run.return_value = subprocess.CompletedProcess(
                args=["which", "gh"], returncode=1, stdout="", stderr=""
            )

            deploy.walkthrough_github_secrets(bootstrap_result)

            # Should call wait_for_user
            assert mock_wait.called

    def test_provides_manual_instructions_when_user_chooses_manual(self, capsys, mock_stdin_tty):
        """Function shows manual instructions when user selects manual."""
        bootstrap_result = self._bootstrap_result()

        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.confirm_or_manual", return_value="manual"),
            patch("deploy.wait_for_user"),
        ):
            # Make "which gh" return success (found)
            mock_run.return_value = subprocess.CompletedProcess(
                args=["which", "gh"], returncode=0, stdout="/usr/bin/gh\n", stderr=""
            )

            deploy.walkthrough_github_secrets(bootstrap_result)

            captured = capsys.readouterr()
            assert "manual steps" in captured.out.lower()

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_user_refuses_github_secrets(self, mock_stdin_tty):
        """Function exits when user enters 'no' for GitHub secrets."""
        bootstrap_result = self._bootstrap_result()

        with (
            patch("builtins.input", return_value="n"),
            patch("subprocess.run") as mock_run,
        ):

            def mock_subprocess_run(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "which" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n", stderr="")
                if "gh" in cmd_str and "list" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = mock_subprocess_run

            with pytest.raises(SystemExit) as exc_info:
                deploy.walkthrough_github_secrets(bootstrap_result)

            assert exc_info.value.code == 1

    def test_ensures_state_bucket_when_role_secret_kept(self, mock_stdin_tty):
        """Keeping an existing role secret still provisions the state-bucket secret."""
        bootstrap_result = self._bootstrap_result()

        with (
            patch("builtins.input", side_effect=["n", "y"]),
            patch("subprocess.run") as mock_run,
        ):

            def mock_subprocess_run(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "which" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n", stderr="")
                if "gh" in cmd_str and "list" in cmd_str:
                    return subprocess.CompletedProcess(
                        args=cmd,
                        returncode=0,
                        stdout="AWS_ROLE_ARN_DEV\tupdated\n",
                        stderr="",
                    )
                if "gh" in cmd_str and "secret" in cmd_str and "set" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = mock_subprocess_run

            deploy.walkthrough_github_secrets(bootstrap_result)

            bucket_calls = [
                c for c in mock_run.call_args_list if c[0][0][0] == "gh" and "TF_INFRA_STATE_BUCKET_DEV" in c[0][0]
            ]
            assert len(bucket_calls) == 1

    def test_exits_when_gh_command_fails(self, mock_stdin_tty):
        """Function exits when gh secret set fails."""
        bootstrap_result = self._bootstrap_result()

        with (
            patch("deploy.confirm_or_manual", return_value="yes"),
            patch("subprocess.run") as mock_run,
        ):
            # Make subprocess.run return failure for gh secret set
            def selective_failure(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "which" in cmd_str and "gh" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n")
                elif "gh" in cmd_str and "secret" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=1, stderr="auth error")
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = selective_failure

            with pytest.raises(SystemExit):
                deploy.walkthrough_github_secrets(bootstrap_result)

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_set_secret_in_dry_run_mode(self, mock_subprocess):
        """Function does not execute gh command in dry-run."""
        bootstrap_result = self._bootstrap_result()

        with patch("shutil.which", return_value="/usr/bin/gh"):
            deploy.walkthrough_github_secrets(bootstrap_result, dry_run=True)
            # In dry-run, no `gh` command (availability probe or `gh secret set`)
            # reaches the process boundary.
            mock_subprocess.assert_not_called()


class TestWalkthroughBackendConfig:
    """Tests for deploy.walkthrough_backend_config."""

    def test_writes_instance_backend_files_when_user_confirms(
        self, tmp_path, mock_stdin_tty, mock_subprocess, monkeypatch
    ):
        instance_dir = tmp_path / "instance"
        monkeypatch.setenv("SHIFTER_INSTANCE_DIR", str(instance_dir))
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "region": "us-east-2",
            "env": "dev",
        }

        with patch("deploy.confirm_or_manual", return_value="yes"):
            deploy.walkthrough_backend_config(bootstrap_result)

        backend_dir = instance_dir / "terraform-backend"
        assert (backend_dir / "environments/dev/dev.s3.tfbackend").exists()
        assert (backend_dir / "environments/dev/portal/dev.s3.tfbackend").exists()
        assert bootstrap_result["backend_config_dir"] == str(backend_dir)

    def test_creates_correct_backend_config_content(self, tmp_path, mock_stdin_tty, mock_subprocess, monkeypatch):
        instance_dir = tmp_path / "instance"
        monkeypatch.setenv("SHIFTER_INSTANCE_DIR", str(instance_dir))
        bootstrap_result = {
            "bucket_name": "my-bucket",
            "region": "us-west-2",
            "env": "prod",
        }

        with patch("deploy.confirm_or_manual", return_value="yes"):
            deploy.walkthrough_backend_config(bootstrap_result)

        core_backend = (instance_dir / "terraform-backend" / "environments/prod/prod.s3.tfbackend").read_text()
        assert "my-bucket" in core_backend
        assert "us-west-2" in core_backend
        assert "use_lockfile = true" in core_backend

    def test_exits_when_user_refuses_backend_config(self, tmp_path, mock_stdin_tty, mock_subprocess, monkeypatch):
        monkeypatch.setenv("SHIFTER_INSTANCE_DIR", str(tmp_path / "instance"))
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.confirm_or_manual", return_value="no"),
            pytest.raises(SystemExit) as exc_info,
        ):
            deploy.walkthrough_backend_config(bootstrap_result)

        assert exc_info.value.code == 1

    def test_exits_when_file_write_fails(self, tmp_path, mock_stdin_tty, mock_subprocess, monkeypatch):
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_dir.chmod(0o500)
        monkeypatch.setenv("SHIFTER_INSTANCE_DIR", str(instance_dir))
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.confirm_or_manual", return_value="yes"),
            pytest.raises(PermissionError),
        ):
            deploy.walkthrough_backend_config(bootstrap_result)

    def test_provides_manual_instructions_when_user_chooses_manual(
        self, tmp_path, capsys, mock_stdin_tty, mock_subprocess, monkeypatch
    ):
        monkeypatch.setenv("SHIFTER_INSTANCE_DIR", str(tmp_path / "instance"))
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.confirm_or_manual", return_value="manual"),
            patch("deploy.wait_for_user") as mock_wait,
        ):
            deploy.walkthrough_backend_config(bootstrap_result)

        assert mock_wait.called
        call_arg = mock_wait.call_args[0][0]
        assert "instance directory" in call_arg.lower()


class TestWalkthroughCognitoUser:
    """Tests for deploy.walkthrough_cognito_user."""

    # ---------------------------------------------------------------------
    # Happy path - user creation
    # ---------------------------------------------------------------------

    def test_creates_cognito_user_with_email(self, mock_stdin_tty, mock_subprocess):
        """Function creates Cognito user with provided email."""
        outputs = {"cognito_user_pool_id": {"value": "us-east-2_ABC123"}}

        with (
            patch("deploy.confirm", return_value=True),
            patch("builtins.input", return_value="test@example.com"),
        ):
            deploy.walkthrough_cognito_user(outputs, "dev", "my-profile")

            # Should call aws cognito-idp admin-create-user
            cognito_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "cognito-idp" in " ".join(c[0][0])
            ]
            assert len(cognito_calls) > 0

    def test_includes_user_pool_id_in_command(self, mock_stdin_tty, mock_subprocess):
        """Function passes correct user pool ID to Cognito."""
        outputs = {"cognito_user_pool_id": {"value": "us-east-2_TESTPOOL"}}

        with (
            patch("deploy.confirm", return_value=True),
            patch("builtins.input", return_value="test@example.com"),
        ):
            deploy.walkthrough_cognito_user(outputs, "dev", "my-profile")

            # Find the cognito command
            cognito_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and c[0][0][0] == "aws"
                and "admin-create-user" in " ".join(c[0][0])
            ]
            assert len(cognito_calls) > 0

            cmd = cognito_calls[0][0][0]
            assert "us-east-2_TESTPOOL" in " ".join(cmd)

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_cognito_user_creation_fails(self, mock_stdin_tty):
        """Function exits when Cognito user creation fails."""
        outputs = {"cognito_user_pool_id": {"value": "us-east-2_ABC123"}}

        with (
            patch("deploy.confirm", return_value=True),
            patch("builtins.input", return_value="test@example.com"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["aws"])

            with pytest.raises(SystemExit):
                deploy.walkthrough_cognito_user(outputs, "dev", "my-profile")

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_create_user_in_dry_run_mode(self, mock_subprocess):
        """Function does not execute Cognito commands in dry-run."""
        outputs = {"cognito_user_pool_id": {"value": "us-east-2_ABC123"}}

        with patch("deploy.run_cmd") as mock_run:
            deploy.walkthrough_cognito_user(outputs, "dev", "my-profile", dry_run=True)

            # In dry-run, the Cognito admin-create-user call is gated behind
            # `if not dry_run`, so run_cmd is never invoked at all.
            mock_run.assert_not_called()


class TestEnsureStateBucketSettingSecret:
    """Branch coverage for _ensure_tf_infra_state_bucket_secret.

    Mocks only the process boundary (subprocess.run for `gh`, plus stdin), not
    first-party seams, per ADR-019-R1.
    """

    NAME = "TF_INFRA_STATE_BUCKET_DEV"

    @staticmethod
    def _gh_list_run(stdout: str):
        """subprocess.run side effect: `gh secret list` returns stdout; others succeed."""

        def run(cmd, **kwargs):
            joined = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "secret" in joined and "list" in joined:
                return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        return run

    @staticmethod
    def _set_calls(mock_run):
        return [c for c in mock_run.call_args_list if "gh" in c[0][0] and "set" in c[0][0]]

    def test_returns_early_when_already_configured(self) -> None:
        """When `gh secret list` already shows the secret, do not set it."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._gh_list_run(f"{self.NAME}\tUpdated 2024\n")
            deploy._ensure_tf_infra_state_bucket_secret(self.NAME, "shifter-dev-infra-x", "org", "repo")
        assert self._set_calls(mock_run) == []

    def test_manual_choice_does_not_set(self, monkeypatch) -> None:
        """Non-interactive resolves to the manual path: instructions, no gh set.

        Non-interactive `confirm_or_manual` returns "manual" and `wait_for_user`
        returns immediately, so no first-party seam needs mocking.
        """
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._gh_list_run("")  # secret absent
            deploy._ensure_tf_infra_state_bucket_secret(self.NAME, "shifter-dev-infra-x", "org", "repo")
        assert self._set_calls(mock_run) == []

    def test_refusal_exits(self, mock_stdin_tty) -> None:
        """Choosing 'no' aborts, because the secret is required for deploys."""
        with patch("subprocess.run") as mock_run, patch("builtins.input", return_value="n"):
            mock_run.side_effect = self._gh_list_run("")  # secret absent
            with pytest.raises(SystemExit) as exc_info:
                deploy._ensure_tf_infra_state_bucket_secret(self.NAME, "shifter-dev-infra-x", "org", "repo")
        assert exc_info.value.code == 1
