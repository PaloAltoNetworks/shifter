"""Behavior tests split from deploy.py: test_cli.py.

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


class TestMainCLI:
    """Tests for deploy.main() CLI argument parsing."""

    # ---------------------------------------------------------------------
    # Command parsing
    # ---------------------------------------------------------------------

    def test_requires_command(self):
        """CLI requires a subcommand (bootstrap, terraform, or full)."""
        with (
            patch("sys.argv", ["deploy.py"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_bootstrap_command_requires_env(self):
        """Bootstrap command requires --env argument."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--profile", "test"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_bootstrap_command_requires_profile(self):
        """Bootstrap command requires --profile argument."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--env", "dev"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_terraform_command_requires_env(self):
        """Terraform command requires --env argument."""
        with (
            patch("sys.argv", ["deploy.py", "terraform", "--profile", "test"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_terraform_command_requires_profile(self):
        """Terraform command requires --profile argument."""
        with (
            patch("sys.argv", ["deploy.py", "terraform", "--env", "dev"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_full_command_requires_env_and_profile(self):
        """Full command requires both --env and --profile arguments."""
        with (
            patch("sys.argv", ["deploy.py", "full"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    # ---------------------------------------------------------------------
    # Dependency checking
    # ---------------------------------------------------------------------

    def test_checks_gdc_dependencies_before_running_command(self, capsys):
        """A missing GDC dependency stops the command before any work starts."""
        with (
            patch(
                "sys.argv",
                ["deploy.py", "gdc-bootstrap", "--project-id", "prod-rwctxzl6shxk", "--cluster-id", "cluster1"],
            ),
            patch("shutil.which", side_effect=lambda tool: None if tool == "gcloud" else f"/usr/bin/{tool}"),
            pytest.raises(SystemExit) as exc,
        ):
            deploy.main()

        assert exc.value.code == 1
        output = capsys.readouterr().out
        assert "Missing required dependencies" in output
        assert "gcloud" in output
        assert "Bootstrapping cluster1 GDC Cluster" not in output

    # ---------------------------------------------------------------------
    # Command execution
    # ---------------------------------------------------------------------

    def test_executes_bootstrap_command(self):
        """CLI executes bootstrap_account when bootstrap command given."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--env", "dev", "--profile", "test"]),
            patch("deploy.check_dependencies"),
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("deploy.bootstrap_account") as mock_bootstrap,
            patch("deploy.walkthrough_github_secrets"),
            patch("deploy.walkthrough_backend_config"),
        ):
            mock_bootstrap.return_value = {"role_arn": "test"}

            deploy.main()

            mock_bootstrap.assert_called_once_with(deploy.BootstrapConfig(env="dev"), "test", dry_run=False)

    def test_executes_terraform_command(self):
        """CLI executes terraform_deploy when terraform command given."""
        with (
            patch("sys.argv", ["deploy.py", "terraform", "--env", "dev", "--profile", "test"]),
            patch("deploy.check_dependencies"),
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("deploy.terraform_deploy") as mock_terraform,
            patch("deploy.walkthrough_acm_validation"),
            patch("deploy.walkthrough_dns_setup"),
            patch("deploy.walkthrough_cognito_user"),
            patch("deploy.walkthrough_final_steps"),
        ):
            mock_terraform.return_value = {}

            deploy.main()

            mock_terraform.assert_called_once_with("dev", "test", dry_run=False)

    def test_executes_full_command(self):
        """CLI executes full_deployment when full command given."""
        with (
            patch("sys.argv", ["deploy.py", "full", "--env", "dev", "--profile", "test"]),
            patch("deploy.check_dependencies"),
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("deploy.full_deployment") as mock_full,
        ):
            deploy.main()

            mock_full.assert_called_once_with("dev", "test", dry_run=False)

    def test_executes_gdc_bootstrap_dry_run(self, capsys, mock_subprocess, mock_repo_root):
        """gdc-bootstrap parses its configuration and completes a safe dry run."""
        tf_dir = mock_repo_root / "platform" / "terraform" / "gcp" / "environments" / "gcp-dev"
        tf_dir.mkdir(parents=True)
        (tf_dir / "terraform.tfvars").write_text(
            'project_id = "shifter-gcp-dev"\n'
            'public_hostname = "portal.example.test"\n'
            "enable_managed_tls = true\n"
            "gke_master_authorized_cidrs = []\n"
        )
        security_override = tf_dir / "security.auto.tfvars"
        security_override.write_text('gke_master_authorized_cidrs = ["203.0.113.10/32"]\n')
        shifter_config = mock_repo_root / "shifter.yaml"
        shifter_config.write_text("version: 1\nbackend: gcp\n")
        with (
            patch(
                "sys.argv",
                [
                    "deploy.py",
                    "gdc-bootstrap",
                    "--project-id",
                    "prod-rwctxzl6shxk",
                    "--cluster-id",
                    "cluster1",
                    "--range-backend",
                    "gdc",
                    "--shifter-config",
                    str(shifter_config),
                    "--dry-run",
                ],
            ),
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
        ):
            deploy.main()

        output = capsys.readouterr().out
        assert "Bootstrapping cluster1 GDC Cluster" in output
        assert "GCP Project: prod-rwctxzl6shxk" in output
        assert "GDC bootstrap complete" in output

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_passes_dry_run_flag_to_bootstrap(self):
        """CLI passes --dry-run flag to bootstrap_account."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--env", "dev", "--profile", "test", "--dry-run"]),
            patch("deploy.check_dependencies"),
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("deploy.bootstrap_account") as mock_bootstrap,
            patch("deploy.walkthrough_github_secrets"),
            patch("deploy.walkthrough_backend_config"),
        ):
            mock_bootstrap.return_value = {"role_arn": "test"}

            deploy.main()

            # Should be called with dry_run=True
            assert mock_bootstrap.call_args[1]["dry_run"] is True

    def test_passes_dry_run_flag_to_terraform(self):
        """CLI passes --dry-run flag to terraform_deploy."""
        with (
            patch("sys.argv", ["deploy.py", "terraform", "--env", "dev", "--profile", "test", "--dry-run"]),
            patch("deploy.check_dependencies"),
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("deploy.terraform_deploy") as mock_terraform,
        ):
            mock_terraform.return_value = None

            deploy.main()

            assert mock_terraform.call_args[1]["dry_run"] is True

    def test_passes_dry_run_flag_to_gdc_bootstrap(self):
        """CLI passes --dry-run flag to gdc_bootstrap_cluster."""
        with (
            patch(
                "sys.argv",
                [
                    "deploy.py",
                    "gdc-bootstrap",
                    "--project-id",
                    "prod-rwctxzl6shxk",
                    "--cluster-id",
                    "cluster1",
                    "--dry-run",
                ],
            ),
            patch("deploy.check_dependencies"),
            patch("deploy.gdc_bootstrap_cluster") as mock_gdc_bootstrap,
        ):
            deploy.main()

            assert mock_gdc_bootstrap.call_args[1]["dry_run"] is True

    def test_gdc_bootstrap_defaults_to_gce_range_backend(self):
        """gdc-bootstrap defaults to the gce range backend so no ABM substrate / SA key is built (#1716)."""
        with (
            patch.dict("os.environ", {"GCP_RANGE_BACKEND": ""}, clear=False),
            patch(
                "sys.argv",
                ["deploy.py", "gdc-bootstrap", "--project-id", "prod-rwctxzl6shxk", "--cluster-id", "cluster1"],
            ),
            patch("deploy.check_dependencies"),
            patch("deploy.gdc_bootstrap_cluster") as mock_gdc_bootstrap,
        ):
            deploy.main()

            config = mock_gdc_bootstrap.call_args[0][0]
            assert config.range_backend == "gce"
            assert config.builds_gdc_substrate is False

    def test_gdc_bootstrap_range_backend_gdc_selects_substrate(self):
        """--range-backend gdc selects the ABM/GDC substrate-building path (#1716)."""
        with (
            patch(
                "sys.argv",
                [
                    "deploy.py",
                    "gdc-bootstrap",
                    "--project-id",
                    "prod-rwctxzl6shxk",
                    "--cluster-id",
                    "cluster1",
                    "--range-backend",
                    "gdc",
                ],
            ),
            patch("deploy.check_dependencies"),
            patch("deploy.gdc_bootstrap_cluster") as mock_gdc_bootstrap,
        ):
            deploy.main()

            config = mock_gdc_bootstrap.call_args[0][0]
            assert config.range_backend == "gdc"
            assert config.builds_gdc_substrate is True

    def test_gdc_bootstrap_terraform_identity_operator_adc(self):
        """--terraform-identity operator-adc threads through to the config (#1718)."""
        with (
            patch(
                "sys.argv",
                [
                    "deploy.py",
                    "gdc-bootstrap",
                    "--project-id",
                    "prod-rwctxzl6shxk",
                    "--cluster-id",
                    "cluster1",
                    "--terraform-identity",
                    "operator-adc",
                ],
            ),
            patch("deploy.check_dependencies"),
            patch("deploy.gdc_bootstrap_cluster") as mock_gdc_bootstrap,
        ):
            deploy.main()

            config = mock_gdc_bootstrap.call_args[0][0]
            assert config.terraform_identity == "operator-adc"
            assert config.terraform_uses_operator_adc is True

    def test_gdc_bootstrap_defaults_to_operator_adc_terraform_identity(self):
        """gdc-bootstrap defaults to operator-adc (keyless, no owner-on-SA) terraform identity (#1738).

        Asserts the config built directly from parsed CLI args/env, rather than routing
        through deploy.main() + gdc_bootstrap_cluster, so this stays a focused unit test
        of the config-building seam (ADR-019 boundary-mock policy).
        """
        with patch.dict("os.environ", {"SHIFTER_GCP_TERRAFORM_IDENTITY": ""}, clear=False):
            parser = deploy._build_parser()
            args = parser.parse_args(["gdc-bootstrap", "--project-id", "prod-rwctxzl6shxk", "--cluster-id", "cluster1"])
            config = deploy._build_gdc_bootstrap_config(args)

        assert config.terraform_identity == "operator-adc"
        assert config.terraform_uses_operator_adc is True

    def test_gdc_bootstrap_terraform_identity_bootstrap_sa_optout(self):
        """--terraform-identity bootstrap-sa opts back into the tf-bootstrap SA path (#1738).

        Asserts the config built directly from parsed CLI args, rather than routing through
        deploy.main() + gdc_bootstrap_cluster, so this stays a focused unit test of the
        config-building seam (ADR-019 boundary-mock policy).
        """
        parser = deploy._build_parser()
        args = parser.parse_args(
            [
                "gdc-bootstrap",
                "--project-id",
                "prod-rwctxzl6shxk",
                "--cluster-id",
                "cluster1",
                "--terraform-identity",
                "bootstrap-sa",
            ]
        )
        config = deploy._build_gdc_bootstrap_config(args)

        assert config.terraform_identity == "bootstrap-sa"
        assert config.terraform_uses_operator_adc is False

    def test_passes_yes_flag_to_gdc_bootstrap(self):
        """--yes makes later non-interactive confirmation prompts proceed."""
        deploy.set_assume_yes(False)
        try:
            with (
                patch(
                    "sys.argv",
                    [
                        "deploy.py",
                        "gdc-bootstrap",
                        "--project-id",
                        "prod-rwctxzl6shxk",
                        "--cluster-id",
                        "cluster1",
                        "--yes",
                    ],
                ),
                patch("shutil.which", return_value=None),
                pytest.raises(SystemExit) as exc,
            ):
                deploy.main()

            assert exc.value.code == 1
            with patch("sys.stdin.isatty", return_value=False):
                assert deploy.confirm("Proceed?") is True
        finally:
            deploy.set_assume_yes(False)

    # ---------------------------------------------------------------------
    # preflight subcommand (shared deploy prerequisite gate)
    #
    # Observable behavior only: the real gate runs against a patched shutil.which
    # boundary (ADR-019), so a present toolchain passes and a missing one exits 1.
    # ---------------------------------------------------------------------

    def test_preflight_command_passes_when_tools_present(self, mock_stdin_non_tty):
        """preflight --cloud aws exits cleanly when the required tools are on PATH."""
        with (
            patch("sys.argv", ["deploy.py", "preflight", "--cloud", "aws", "--env", "dev"]),
            patch("shutil.which", return_value="/usr/bin/tool"),
        ):
            deploy.main()

    def test_preflight_command_fails_on_missing_tool(self, mock_stdin_non_tty):
        """preflight fails fast (exit 1) when a required deploy tool is missing.

        git is present so check_dependencies passes; terraform/aws are absent so the
        preflight gate itself is what fails.
        """
        with (
            patch("sys.argv", ["deploy.py", "preflight", "--cloud", "aws", "--env", "dev"]),
            patch("shutil.which", side_effect=lambda name: "/usr/bin/git" if name == "git" else None),
            pytest.raises(SystemExit) as exc,
        ):
            deploy.main()
        assert exc.value.code == 1

    # ---------------------------------------------------------------------
    # runners subcommand (issue #1433)
    #
    # These assert observable behavior (argparse wiring + the dry-run command
    # plan printed by the real handler) rather than patching first-party seams,
    # per the ADR-019 boundary-mock policy.
    # ---------------------------------------------------------------------

    def test_runners_command_requires_env_and_profile(self):
        """runners subcommand requires both --env and --profile."""
        with (
            patch("sys.argv", ["deploy.py", "runners"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_runners_subcommand_exposes_its_flags(self, capsys):
        """The runners subparser is wired with its automation flags."""
        with (
            patch("sys.argv", ["deploy.py", "runners", "--help"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

        help_text = capsys.readouterr().out
        assert "--use-existing-network" in help_text
        assert "--runner-count" in help_text
        # GCP runner path (issue #1546) is wired on the same subcommand.
        assert "--cloud" in help_text
        assert "--project-id" in help_text

    def test_runners_cloud_gcp_dispatches_to_gcp_path(self, capsys):
        """--cloud gcp dry-run plans the GCP runner root, never the AWS SSM path.

        Asserts observable behavior (ADR-019) rather than patching first-party
        dispatch seams: the GCP path is the only one that threads project_id into
        the Terraform plan and it never emits an SSM send-command.
        """
        with (
            patch(
                "sys.argv",
                ["deploy.py", "runners", "--cloud", "gcp", "--env", "gcp-dev", "--project-id", "my-proj", "--dry-run"],
            ),
            patch("shutil.which", return_value="/usr/bin/tool"),
        ):
            deploy.main()

        out = capsys.readouterr().out
        assert "project_id=my-proj" in out
        assert "send-command" not in out  # never the AWS SSM registration path

    def test_runners_cloud_aws_requires_profile(self):
        """--cloud aws (default) without --profile fails closed before any work."""
        with (
            patch("sys.argv", ["deploy.py", "runners", "--env", "dev"]),
            patch("shutil.which", return_value="/usr/bin/tool"),
            pytest.raises(SystemExit),
        ):
            deploy.main()


class TestRunnersDeployment:
    """Observable behavior of the runners_deployment handler in dry-run."""

    def test_provisions_dedicated_network_by_default(self, capsys):
        """Dry-run plans the runner apply with create_runner_network=true and no token."""
        deploy.runners_deployment("dev", "test", dry_run=True)

        out = capsys.readouterr().out
        assert "terraform" in out
        assert "create_runner_network=true" in out
        # Dry-run must not mint a token or send an SSM command.
        assert "registration-token" not in out
        assert "send-command" not in out

    def test_use_existing_network_disables_created_vpc(self, capsys):
        """--use-existing-network plans with create_runner_network=false."""
        deploy.runners_deployment("dev", "test", dry_run=True, use_existing_network=True)

        out = capsys.readouterr().out
        assert "create_runner_network=false" in out

    def test_runner_count_override_reaches_terraform(self, capsys):
        """--runner-count is threaded into the terraform plan vars."""
        deploy.runners_deployment("dev", "test", dry_run=True, runner_count=5)

        out = capsys.readouterr().out
        assert "runner_count=5" in out
