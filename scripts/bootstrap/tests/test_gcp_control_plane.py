"""Behavior tests split from deploy.py: test_gcp_control_plane.py.

Tests verify the complete contract for each function:
1. Inputs - minimum required data and validation
2. Outputs - return values and data structures
3. Side effects - subprocess calls, file writes, system changes
4. Errors - error handling and propagation
5. Logging - debug and error logging

All external dependencies are mocked. No actual AWS calls, file operations,
or subprocess executions occur during tests.
"""

import io
import json
import os
import shutil
import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

import deploy
import gcp_control_plane

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
                # account_id is bounded to <=30 chars, so provisioner-launcher's SA
                # localpart is shortened to prov-launcher (#1719).
                "provisioner-launcher": (f"shiftergcpdev-prov-launcher@{project_id}.iam.gserviceaccount.com"),
                "provisioner": f"shiftergcpdev-provisioner@{project_id}.iam.gserviceaccount.com",
            }
        },
    }


def _completed(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Return a typed CompletedProcess test double."""
    return subprocess.CompletedProcess(["cmd"], returncode, stdout=stdout, stderr=stderr)


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


class TestGdcControlPlaneTerraform:
    """Tests for the GCP control-plane Terraform bootstrap path."""

    def test_uses_requested_project_for_backend_and_apply(self, mock_repo_root):
        """Terraform bootstrap must target the live project instead of the committed gcp-dev placeholder."""
        # Pin the bootstrap-sa path explicitly: the default is now operator-adc (#1738),
        # but this test exercises the tf-bootstrap-SA credential + access-wait flow.
        config = deploy.GDCBootstrapConfig(
            project_id="prod-rwctxzl6shxk", cluster_id="cluster1", terraform_identity="bootstrap-sa"
        )
        tf_dir = mock_repo_root / "platform" / "terraform" / "gcp" / "environments" / "gcp-dev"
        tf_dir.mkdir(parents=True)
        (tf_dir / "terraform.tfvars").write_text(
            """
project_id = "shifter-gcp-dev"
region = "us-central1"
public_hostname = "portal.example.test"
enable_managed_tls = true
gke_master_authorized_cidrs = ["198.51.100.10/32"]
	"""
        )
        # The control-plane apply renders the range egress bridge from the root
        # config (#1015); a deployment shifter.yaml must be resolvable.
        (mock_repo_root / "shifter.yaml").write_text("version: 1\nbackend: gcp\n")

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"name":"operations/artifactregistry-service-identity"}'

        terraform_output = json.dumps(_sample_gcp_control_plane_outputs(config.project_id))

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.gcp_terraform_bootstrap_credentials", return_value=nullcontext(Path("bootstrap.json"))),
            patch("deploy.run_gcp_terraform_init_with_retry") as mock_init,
            patch("deploy.wait_for_gcp_terraform_bootstrap_access") as mock_wait,
            patch("deploy.run_gcp_terraform_apply_with_retry") as mock_apply,
            patch("deploy.run_cmd") as mock_run_cmd,
            patch("deploy._gcp_identity_access_token", return_value="test-access-token"),
            patch("deploy.urllib_request.urlopen", return_value=_FakeResponse()),
            patch("os.chdir"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(["terraform"], 0, stdout=terraform_output),
            ),
        ):
            outputs = deploy.apply_gcp_control_plane_terraform(config)

        # The apply flow renders the range egress bridge tfvars from shifter.yaml (#1015).
        assert any("shifter-config" in (call.args[0] if call.args else []) for call in mock_run_cmd.call_args_list), (
            "apply must render the range egress allowlist via shifter-config"
        )
        mock_init.assert_called_once_with(config, config.terraform_state_bucket_name, Path("bootstrap.json"))
        mock_wait.assert_called_once_with(config, Path("bootstrap.json"))
        assert mock_init.call_args.args[1] == "prod-rwctxzl6shxk-terraform-state"
        assert mock_init.call_args.args[0] is config
        mock_apply.assert_called_once_with(config)
        assert mock_apply.call_args.args[0] is config
        assert outputs["gke_cluster_name"]["value"] == "shifter-gcp-dev-platform"

    def test_operator_adc_identity_skips_tf_bootstrap_service_account(self, mock_repo_root):
        """operator-adc runs terraform under ADC and never provisions the privileged tf-bootstrap SA (#1718)."""
        config = deploy.GDCBootstrapConfig(
            project_id="prod-rwctxzl6shxk", cluster_id="cluster1", terraform_identity="operator-adc"
        )
        tf_dir = mock_repo_root / "platform" / "terraform" / "gcp" / "environments" / "gcp-dev"
        tf_dir.mkdir(parents=True)
        (tf_dir / "terraform.tfvars").write_text(
            'project_id = "shifter-gcp-dev"\n'
            'region = "us-central1"\n'
            'public_hostname = "portal.example.test"\n'
            "enable_managed_tls = true\n"
            'gke_master_authorized_cidrs = ["198.51.100.10/32"]\n'
        )
        (mock_repo_root / "shifter.yaml").write_text("version: 1\nbackend: gcp\n")

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"name":"operations/artifactregistry-service-identity"}'

        terraform_output = json.dumps(_sample_gcp_control_plane_outputs(config.project_id))

        with (
            patch.dict("os.environ", {}, clear=False),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.gcp_terraform_bootstrap_credentials") as mock_creds,
            patch("deploy.run_gcp_terraform_init_with_retry") as mock_init,
            patch("deploy.wait_for_gcp_terraform_bootstrap_access") as mock_wait,
            patch("deploy.run_gcp_terraform_apply_with_retry") as mock_apply,
            patch("deploy.run_cmd"),
            patch("deploy._gcp_identity_access_token", return_value="test-access-token"),
            patch("deploy.urllib_request.urlopen", return_value=_FakeResponse()),
            patch("os.chdir"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(["terraform"], 0, stdout=terraform_output),
            ),
        ):
            outputs = deploy.apply_gcp_control_plane_terraform(config)

            # Under the caller's user ADC, identitytoolkit / Identity Platform need
            # a quota project or they 403; the operator-adc path sets it (#1738).
            assert os.environ["USER_PROJECT_OVERRIDE"] == "true"
            assert os.environ["GOOGLE_BILLING_PROJECT"] == config.project_id

        mock_creds.assert_not_called()
        mock_wait.assert_not_called()
        mock_init.assert_called_once_with(config, config.terraform_state_bucket_name, None)
        mock_apply.assert_called_once_with(config)
        assert outputs["gke_cluster_name"]["value"] == "shifter-gcp-dev-platform"


class TestRenderRangeEgressTfvars:
    """render_range_egress_tfvars shells out to `shifter-config render` at the process boundary (#1015)."""

    def test_invokes_shifter_config_render_with_paths(self, tmp_path):
        """The render argv passes the config and output paths to the installation CLI."""
        repo_root = tmp_path / "repo"
        (repo_root / "shifter" / "installation").mkdir(parents=True)
        config_path = tmp_path / "shifter.yaml"
        config_path.write_text("version: 1\nbackend: gcp\n")
        output_path = tmp_path / "range_egress.auto.tfvars"

        with patch("subprocess.run", return_value=subprocess.CompletedProcess(["uv"], 0)) as mock_run:
            deploy.render_range_egress_tfvars(repo_root, config_path, output_path)

        mock_run.assert_called_once()
        argv = mock_run.call_args.args[0]
        assert argv[:6] == [
            "uv",
            "run",
            "--project",
            str(repo_root / "shifter" / "installation"),
            "shifter-config",
            "render",
        ]
        assert argv[6] == str(config_path)
        assert argv[-2:] == ["--output", str(output_path)]

    def test_dry_run_does_not_execute(self, tmp_path, capsys):
        """Dry-run prints the render command without touching the process boundary."""
        with patch("subprocess.run") as mock_run:
            deploy.render_range_egress_tfvars(
                tmp_path / "repo", tmp_path / "shifter.yaml", tmp_path / "out.tfvars", dry_run=True
            )

        mock_run.assert_not_called()
        assert "shifter-config" in capsys.readouterr().out


class TestResolveShifterConfigPath:
    """resolve_shifter_config_path is single-source; a missing root config fails the deploy loud (#1015)."""

    def test_prefers_explicit_path(self, tmp_path, monkeypatch):
        """An explicit --shifter-config path wins over the SHIFTER_CONFIG env and the repo-root default."""
        monkeypatch.setenv("SHIFTER_CONFIG", str(tmp_path / "env-not-used.yaml"))
        explicit = tmp_path / "explicit.yaml"
        explicit.write_text("version: 1\nbackend: gcp\n")
        (tmp_path / "shifter.yaml").write_text("version: 1\nbackend: gcp\n")
        config = deploy.GDCBootstrapConfig(project_id="p", shifter_config_path=str(explicit))

        assert deploy.resolve_shifter_config_path(config, tmp_path) == explicit

    def test_falls_back_to_env(self, tmp_path, monkeypatch):
        """With no explicit path, SHIFTER_CONFIG is used before the repo-root default."""
        env_cfg = tmp_path / "env.yaml"
        env_cfg.write_text("version: 1\nbackend: gcp\n")
        monkeypatch.setenv("SHIFTER_CONFIG", str(env_cfg))
        config = deploy.GDCBootstrapConfig(project_id="p")

        assert deploy.resolve_shifter_config_path(config, tmp_path) == env_cfg

    def test_falls_back_to_repo_root(self, tmp_path, monkeypatch):
        """With no explicit path and no env, the repo-root shifter.yaml is the default."""
        monkeypatch.delenv("SHIFTER_CONFIG", raising=False)
        repo_cfg = tmp_path / "shifter.yaml"
        repo_cfg.write_text("version: 1\nbackend: gcp\n")
        config = deploy.GDCBootstrapConfig(project_id="p")

        assert deploy.resolve_shifter_config_path(config, tmp_path) == repo_cfg

    def test_missing_config_fails_loud(self, tmp_path, monkeypatch, capsys):
        """No resolvable root config is a hard SystemExit, never a silent status-quo."""
        monkeypatch.delenv("SHIFTER_CONFIG", raising=False)
        config = deploy.GDCBootstrapConfig(project_id="p")

        with pytest.raises(SystemExit):
            deploy.resolve_shifter_config_path(config, tmp_path)

        assert "shifter.yaml" in capsys.readouterr().out


class TestGcpControlPlaneSecurityInputs:
    """Tests for the bootstrap security preflight that runs before Terraform apply."""

    def test_reads_security_inputs_from_tfvars(self, tmp_path):
        """Bootstrap should read the hostname, TLS, and admin CIDR inputs from terraform.tfvars."""
        tf_dir = tmp_path / "gcp-dev"
        tf_dir.mkdir()
        (tf_dir / "terraform.tfvars").write_text(
            """
public_hostname = "portal.example.test"
enable_managed_tls = true
gke_master_authorized_cidrs = [
  "198.51.100.10/32",
  "203.0.113.0/24",
]
"""
        )

        settings = deploy.read_gcp_control_plane_security_inputs(tf_dir)

        assert settings == {
            "public_hostname": "portal.example.test",
            "enable_managed_tls": True,
            "gke_master_authorized_cidrs": ["198.51.100.10/32", "203.0.113.0/24"],
        }

    def test_reads_security_inputs_from_auto_tfvars_with_last_assignment_wins(self, tmp_path):
        """Bootstrap should include sorted auto.tfvars so generated security inputs are honored."""
        tf_dir = tmp_path / "gcp-dev"
        tf_dir.mkdir()
        (tf_dir / "terraform.tfvars").write_text(
            """
public_hostname = "portal.example.test"
enable_managed_tls = false
gke_master_authorized_cidrs = ["198.51.100.10/32"]
"""
        )
        (tf_dir / "99-security.auto.tfvars").write_text(
            """
enable_managed_tls = true
gke_master_authorized_cidrs = ["203.0.113.0/24"]
"""
        )

        assert deploy.read_gcp_control_plane_security_inputs(tf_dir) == {
            "public_hostname": "portal.example.test",
            "enable_managed_tls": True,
            "gke_master_authorized_cidrs": ["203.0.113.0/24"],
        }

    def test_validate_security_inputs_rejects_insecure_defaults(self, tmp_path):
        """Bootstrap must fail before Terraform apply when ingress and control-plane access are insecure."""
        tf_dir = tmp_path / "gcp-dev"
        tf_dir.mkdir()
        (tf_dir / "terraform.tfvars").write_text(
            """
public_hostname = ""
enable_managed_tls = false
gke_master_authorized_cidrs = []
"""
        )

        with pytest.raises(ValueError, match="public hostname"):
            deploy.validate_gcp_control_plane_security_inputs(tf_dir)

    @staticmethod
    def _write_secure_tfvars(tf_dir, cidrs):
        """Write a terraform.tfvars whose hostname/TLS pass, so a test isolates the CIDR allowlist check."""
        tf_dir.mkdir()
        cidr_lines = "".join(f'  "{cidr}",\n' for cidr in cidrs)
        (tf_dir / "terraform.tfvars").write_text(
            'public_hostname = "portal.example.test"\n'
            "enable_managed_tls = true\n"
            f"gke_master_authorized_cidrs = [\n{cidr_lines}]\n"
        )

    @pytest.mark.parametrize(
        ("cidrs", "expected_match"),
        [
            # The same contract the Terraform `validation` block on
            # `gke_master_authorized_cidrs` enforces — keep these in lockstep.
            (["0.0.0.0/0"], r"/0 range"),
            (["::/0"], r"/0 range"),
            (["198.51.100.0/24", "0.0.0.0/0"], r"/0 range"),
            (["203.0.113.10"], r"explicit /N prefix"),
            (["not-a-cidr"], r"explicit /N prefix"),
            (["not/a/cidr"], r"not a valid CIDR"),
            (["198.51.100.999/32"], r"not a valid CIDR"),
            (["198.51.100.0/33"], r"not a valid CIDR"),
        ],
        ids=[
            "ipv4_world_open",
            "ipv6_world_open",
            "mixed_with_world_open",
            "bare_ip_no_prefix",
            "no_prefix_garbage",
            "garbage_with_slashes",
            "bad_octet",
            "bad_prefix",
        ],
    )
    def test_validate_security_inputs_rejects_unsafe_authorized_cidrs(self, tmp_path, cidrs, expected_match):
        """Bootstrap must reject malformed CIDR entries and world-open /0 ranges in the admin allowlist."""
        tf_dir = tmp_path / "gcp-dev"
        self._write_secure_tfvars(tf_dir, cidrs)

        with pytest.raises(ValueError, match=expected_match):
            deploy.validate_gcp_control_plane_security_inputs(tf_dir)

    def test_validate_security_inputs_accepts_specific_admin_cidrs(self, tmp_path):
        """A non-empty allowlist of specific, well-formed v4/v6 CIDRs passes the preflight.

        The validator is a side-effect-only contract (raise on bad input, return
        None on good input), so the assertions cover both halves: the documented
        None return and a round-trip parse that proves the test fixture's input
        was actually consumed (so a future refactor that silently skipped the
        CIDR loop would still be caught here, not just by the negative cases).
        """
        tf_dir = tmp_path / "gcp-dev"
        cidrs = ["198.51.100.10/32", "203.0.113.0/24", "2001:db8::/48"]
        self._write_secure_tfvars(tf_dir, cidrs)

        assert deploy.validate_gcp_control_plane_security_inputs(tf_dir) is None
        assert deploy.read_gcp_control_plane_security_inputs(tf_dir)["gke_master_authorized_cidrs"] == cidrs


class TestGdcTerraformBootstrapCredentials:
    """Tests for the ephemeral Terraform credential path used by GCP bootstrap."""

    def test_bootstrap_credentials_set_google_env_vars_and_cleanup(self, monkeypatch):
        """Terraform bootstrap must provision temporary credentials and clean them up afterwards."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        def fake_run_cmd(cmd, *args, **kwargs):
            if cmd[:5] == ["gcloud", "iam", "service-accounts", "keys", "create"]:
                Path(cmd[5]).write_text('{"private_key_id":"bootstrap-key-id"}\n')
            return None

        for key in ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_BACKEND_CREDENTIALS", "GOOGLE_CREDENTIALS"):
            monkeypatch.delenv(key, raising=False)

        with (
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.prune_stale_gcp_terraform_bootstrap_keys") as mock_prune,
            patch("deploy.run_cmd", side_effect=fake_run_cmd) as mock_run_cmd,
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(["gcloud"], 0, stdout="", stderr=""),
            ) as mock_subprocess,
            deploy.gcp_terraform_bootstrap_credentials(config) as credentials_path,
        ):
            assert Path(credentials_path).read_text() == '{"private_key_id":"bootstrap-key-id"}\n'
            assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(credentials_path)
            assert "GOOGLE_BACKEND_CREDENTIALS" not in os.environ
            assert "GOOGLE_CREDENTIALS" not in os.environ

        mock_prune.assert_called_once_with(config)
        executed = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert any(
            cmd[:4] == ["gcloud", "iam", "service-accounts", "create"]
            and cmd[4] == config.terraform_bootstrap_service_account_name
            for cmd in executed
        )
        bound = [call.args[0] for call in mock_subprocess.call_args_list]
        assert any(
            cmd[:4] == ["gcloud", "projects", "add-iam-policy-binding", config.project_id] and cmd[7] == "roles/owner"
            for cmd in bound
        )
        assert any(
            cmd[:5]
            == ["gcloud", "storage", "buckets", "add-iam-policy-binding", f"gs://{config.terraform_state_bucket_name}"]
            and "roles/storage.objectAdmin" in cmd
            for cmd in executed
        )
        assert any(
            cmd[:5] == ["gcloud", "iam", "service-accounts", "keys", "delete"] and "bootstrap-key-id" in cmd
            for cmd in executed
        )
        assert any(
            cmd[:4] == ["gcloud", "projects", "remove-iam-policy-binding", config.project_id] and "roles/owner" in cmd
            for cmd in executed
        )
        assert any(
            cmd[:5]
            == [
                "gcloud",
                "storage",
                "buckets",
                "remove-iam-policy-binding",
                f"gs://{config.terraform_state_bucket_name}",
            ]
            and "roles/storage.objectAdmin" in cmd
            for cmd in executed
        )
        for key in ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_BACKEND_CREDENTIALS", "GOOGLE_CREDENTIALS"):
            assert key not in os.environ

    def test_prunes_stale_user_managed_bootstrap_keys_before_creating_a_new_one(self):
        """Interrupted reruns must not accumulate leftover bootstrap keys."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        listed_keys = subprocess.CompletedProcess(
            ["gcloud"],
            0,
            stdout="stale-key-1\nstale-key-2\n",
            stderr="",
        )

        with (
            patch("deploy.subprocess.run", return_value=listed_keys),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.prune_stale_gcp_terraform_bootstrap_keys(config)

        executed = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert executed == [
            [
                "gcloud",
                "iam",
                "service-accounts",
                "keys",
                "delete",
                "stale-key-1",
                "--iam-account",
                config.terraform_bootstrap_service_account_email,
                "--project",
                config.project_id,
                "--quiet",
            ],
            [
                "gcloud",
                "iam",
                "service-accounts",
                "keys",
                "delete",
                "stale-key-2",
                "--iam-account",
                config.terraform_bootstrap_service_account_email,
                "--project",
                config.project_id,
                "--quiet",
            ],
        ]


class TestGdcTerraformInitRetries:
    """Tests for retrying Terraform init on GCS backend IAM propagation."""

    def test_retries_init_on_eventual_bucket_iam_consistency(self):
        """Documented GCS backend 403s must be retried until init succeeds."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        denied = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout="Initializing the backend...\n",
            stderr=(
                "Error: Failed to get existing workspaces: querying Cloud Storage failed: "
                "googleapi: Error 403: shifter-gcp-dev-tf-bootstrap@prod-rwctxzl6shxk.iam.gserviceaccount.com "
                "does not have storage.objects.list access to the Google Cloud Storage bucket."
            ),
        )
        allowed = subprocess.CompletedProcess(["terraform"], 0, stdout="Initializing the backend...\n", stderr="")

        with (
            patch("subprocess.run", side_effect=[denied, allowed]) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.run_gcp_terraform_init_with_retry(
                config,
                config.terraform_state_bucket_name,
                Path("bootstrap.json"),
                max_attempts=2,
                sleep_seconds=0,
            )

        commands = [call.args[0] for call in mock_subprocess.call_args_list]
        assert commands == [
            [
                "terraform",
                "init",
                "-reconfigure",
                f"-backend-config=bucket={config.terraform_state_bucket_name}",
                f"-backend-config=prefix=shifter/{config.environment}/platform-core",
                "-backend-config=credentials=bootstrap.json",
            ],
            [
                "terraform",
                "init",
                "-reconfigure",
                f"-backend-config=bucket={config.terraform_state_bucket_name}",
                f"-backend-config=prefix=shifter/{config.environment}/platform-core",
                "-backend-config=credentials=bootstrap.json",
            ],
        ]
        mock_sleep.assert_called_once_with(0)

    def test_retries_invalid_jwt_signature_until_key_propagates(self):
        """Fresh service-account keys must be retried until Terraform can exchange them."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        invalid_auth = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout="Initializing the backend...\n",
            stderr='Response: {"error":"invalid_grant","error_description":"Invalid JWT Signature."}',
        )
        allowed = subprocess.CompletedProcess(["terraform"], 0, stdout="Initializing the backend...\n", stderr="")

        with (
            patch("subprocess.run", side_effect=[invalid_auth, allowed]) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.run_gcp_terraform_init_with_retry(
                config,
                config.terraform_state_bucket_name,
                Path("bootstrap.json"),
                max_attempts=2,
                sleep_seconds=0,
            )

        assert mock_subprocess.call_count == 2
        mock_sleep.assert_called_once_with(0)

    def test_fails_fast_on_non_retryable_init_error(self):
        """Non-propagation Terraform failures must abort immediately."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        invalid_backend = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout="Initializing the backend...\n",
            stderr="Error: unsupported backend configuration",
        )

        bootstrap_path = Path("bootstrap.json")
        with (
            patch("subprocess.run", return_value=invalid_backend) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
            pytest.raises(SystemExit),
        ):
            deploy.run_gcp_terraform_init_with_retry(
                config,
                config.terraform_state_bucket_name,
                bootstrap_path,
                max_attempts=3,
                sleep_seconds=0,
            )

        assert mock_subprocess.call_count == 1
        mock_sleep.assert_not_called()


class TestGdcTerraformApplyRetries:
    """Tests for retrying Terraform apply on temporary bootstrap-auth failures."""

    def test_retries_apply_on_iam_permission_propagation(self):
        """403 permission errors from freshly granted project roles must be retried."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        denied = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout='module.platform_core.google_artifact_registry_repository.docker["portal"]: Creating...\n',
            stderr=(
                "Error: Error creating Repository: googleapi: Error 403: Permission "
                "'artifactregistry.repositories.create' denied on resource "
                "'//artifactregistry.googleapis.com/projects/prod-rwctxzl6shxk/locations/us-central1'."
            ),
        )
        allowed = subprocess.CompletedProcess(["terraform"], 0, stdout="Apply complete!\n", stderr="")

        with (
            patch("subprocess.run", side_effect=[denied, allowed]) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.run_gcp_terraform_apply_with_retry(config, max_attempts=2, sleep_seconds=0)

        commands = [call.args[0] for call in mock_subprocess.call_args_list]
        assert commands == [
            ["terraform", "apply", "-auto-approve", f"-var=project_id={config.project_id}"],
            ["terraform", "apply", "-auto-approve", f"-var=project_id={config.project_id}"],
        ]
        mock_sleep.assert_called_once_with(0)

    def test_fails_fast_on_non_retryable_apply_error(self):
        """Non-permission Terraform apply failures must abort immediately."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        invalid_apply = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout="Planning failed.\n",
            stderr="Error: Invalid function argument",
        )

        with (
            patch("subprocess.run", return_value=invalid_apply) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
            pytest.raises(SystemExit),
        ):
            deploy.run_gcp_terraform_apply_with_retry(config, max_attempts=3, sleep_seconds=0)

        assert mock_subprocess.call_count == 1
        mock_sleep.assert_not_called()


class TestGdcTerraformBootstrapAccess:
    """Tests for waiting until bootstrap credentials can really read GCP resources."""

    def test_waits_until_storage_and_artifact_registry_access_are_usable(self):
        """Bootstrap must not start apply until the temporary credentials can list required resources."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        denied = subprocess.CompletedProcess(
            ["gcloud"],
            1,
            stdout="",
            stderr=(
                "ERROR: (gcloud.artifacts.repositories.list) googleapi: Error 403: "
                "Permission 'artifactregistry.repositories.list' denied on resource "
                "'//artifactregistry.googleapis.com/projects/prod-rwctxzl6shxk/locations/us-central1'."
            ),
        )
        allowed = subprocess.CompletedProcess(["gcloud"], 0, stdout="ok\n", stderr="")
        probe_attempts = {"artifact_list": 0}

        def fake_probe(cmd, credentials_path):
            if cmd[:4] == ["gcloud", "artifacts", "repositories", "list"]:
                probe_attempts["artifact_list"] += 1
                return denied if probe_attempts["artifact_list"] == 1 else allowed
            return allowed

        with (
            patch("deploy._run_gcp_bootstrap_probe", side_effect=fake_probe) as mock_probe,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.wait_for_gcp_terraform_bootstrap_access(
                config,
                Path("bootstrap.json"),
                max_attempts=2,
                sleep_seconds=0,
            )

        assert mock_probe.call_count == 6
        mock_sleep.assert_called_once_with(0)

    def test_probe_uses_credential_file_override(self, tmp_path):
        """The readiness probes must use the same temporary credential file Terraform uses."""
        completed = subprocess.CompletedProcess(["gcloud"], 0, stdout="", stderr="")
        credentials_path = tmp_path / "bootstrap.json"

        with patch("deploy.subprocess.run", return_value=completed) as mock_subprocess:
            deploy._run_gcp_bootstrap_probe(["gcloud", "storage", "buckets", "list"], credentials_path)

        env = mock_subprocess.call_args.kwargs["env"]
        assert env["CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"] == str(credentials_path)
        assert env["GOOGLE_APPLICATION_CREDENTIALS"] == str(credentials_path)

    def test_fails_fast_when_probe_error_is_not_retryable(self):
        """Permanent probe failures must abort instead of looping blindly."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        invalid = subprocess.CompletedProcess(
            ["gcloud"],
            1,
            stdout="",
            stderr="ERROR: (gcloud.artifacts.repositories.list) INVALID_ARGUMENT: bad request",
        )

        bootstrap_path = Path("bootstrap.json")
        with (
            patch("deploy._run_gcp_bootstrap_probe", return_value=invalid) as mock_probe,
            patch("deploy.time.sleep") as mock_sleep,
            pytest.raises(SystemExit),
        ):
            deploy.wait_for_gcp_terraform_bootstrap_access(
                config,
                bootstrap_path,
                max_attempts=2,
                sleep_seconds=0,
            )

        assert mock_probe.call_count == 3
        mock_sleep.assert_not_called()


class TestGdcControlPlaneHelmValues:
    """Tests for rendering Helm values for the GCP Shifter release."""

    def test_renders_values_with_live_project_specific_inputs(self):
        """The generated values must carry project-specific images, env contracts, and identity bindings."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values = deploy.render_gcp_helm_values(
            config,
            outputs,
            image_tag=PINNED_IMAGE_TAG,
        )

        assert values["releaseNamespace"] == "shifter-system"
        # CLOUD_PROVIDER reaches the merged runtime env solely via the GCP backend
        # runtime-env renderer (scripts/gcp/render_runtime_env.py); PLAT-2005.
        assert values["runtimeEnv"]["CLOUD_PROVIDER"] == "gcp"
        assert values["runtimeEnv"]["GCP_PROJECT_ID"] == "prod-rwctxzl6shxk"
        assert values["runtimeEnv"]["GOOGLE_CLOUD_PROJECT"] == "prod-rwctxzl6shxk"
        assert values["runtimeEnv"]["DJANGO_DEBUG"] == "false"
        assert values["runtimeEnv"]["SESSION_COOKIE_SECURE"] == "true"
        assert values["runtimeEnv"]["SITE_URL"] == "https://portal.example.test"
        assert (
            values["runtimeEnv"]["GDC_VM_IMAGE_GCS_SECRET_ID"]
            == "projects/prod-rwctxzl6shxk/secrets/shifter-gcp-dev-gdc-vm-image-gcs"
        )
        assert (
            values["serviceAccounts"]["portal"]["annotations"]["iam.gke.io/gcp-service-account"]
            == "shiftergcpdev-portal@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        )
        assert (
            values["serviceAccounts"]["workers"]["annotations"]["iam.gke.io/gcp-service-account"]
            == "shiftergcpdev-workers@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        )
        assert (
            values["serviceAccounts"]["provisioner"]["annotations"]["iam.gke.io/gcp-service-account"]
            == "shiftergcpdev-provisioner@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        )
        assert (
            values["serviceAccounts"]["ctfScheduler"]["annotations"]["iam.gke.io/gcp-service-account"]
            == "shiftergcpdev-ctf-scheduler@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        )
        assert values["images"]["portal"]["repository"] == (
            "us-central1-docker.pkg.dev/prod-rwctxzl6shxk/shifter-gcp-dev-portal/portal"
        )
        assert values["images"]["guacd"]["repository"] == (
            "us-central1-docker.pkg.dev/prod-rwctxzl6shxk/shifter-gcp-dev-guacd/guacd"
        )
        assert values["images"]["guacamoleClient"]["repository"] == (
            "us-central1-docker.pkg.dev/prod-rwctxzl6shxk/shifter-gcp-dev-guacamole-client/guacamole-client"
        )
        assert values["images"]["portal"]["tag"] == PINNED_IMAGE_TAG
        assert values["images"]["guacd"]["tag"] == PINNED_IMAGE_TAG
        assert values["images"]["guacamoleClient"]["tag"] == PINNED_IMAGE_TAG
        assert (
            values["runtimeEnv"]["ENGINE_TASK_IMAGE"] == "us-central1-docker.pkg.dev/prod-rwctxzl6shxk/"
            "shifter-gcp-dev-pulumi-provisioner/pulumi-provisioner:abc1234"
        )
        assert values["guacamoleRuntimeSecret"] == {"name": "guacamole-runtime"}
        assert values["services"]["portal"]["backendConfig"]["securityPolicyName"] == "shifter-gcp-dev-edge"
        assert values["services"]["guacamoleClient"]["backendConfig"]["enabled"] is True
        assert values["services"]["guacamoleClient"]["backendConfig"]["name"] == "guacamole-client"
        assert values["services"]["guacamoleClient"]["backendConfig"]["securityPolicyName"] == "shifter-gcp-dev-edge"
        assert values["networkPolicy"] == {
            "enabled": True,
            "gclbSourceRanges": [
                "35.191.0.0/16",  # NOSONAR - Google Cloud Load Balancer range.
                "130.211.0.0/22",  # NOSONAR - Google Cloud Load Balancer range.
            ],
            "googleApiCidrs": [
                "199.36.153.4/30",  # NOSONAR - restricted.googleapis.com VIP.
                "199.36.153.8/30",  # NOSONAR - private.googleapis.com VIP.
            ],
            "privateServiceCidrs": ["10.40.0.10/32", "10.40.0.20/32"],
            "kubernetesApiCidrs": ["10.48.0.0/20"],
            "rangeClusterApiCidrs": [],
            "rangeClusterApiPort": 6444,
            "rangeAccessCidrs": ["10.50.0.0/16"],
        }

    def test_range_cluster_api_cidrs_from_control_plane_endpoint(self):
        """The range-cluster egress allowlist mirrors the configured control-plane endpoint."""
        config = deploy.GDCBootstrapConfig(
            project_id="prod-rwctxzl6shxk",
            cluster_id="cluster1",
            control_plane_platform_endpoint="10.240.0.5:6444",
        )
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values = deploy.render_gcp_helm_values(
            config,
            outputs,
            image_tag=PINNED_IMAGE_TAG,
        )

        assert values["networkPolicy"]["rangeClusterApiCidrs"] == ["10.240.0.5/32"]
        assert values["networkPolicy"]["rangeClusterApiPort"] == 6444

    def test_range_access_cidrs_from_range_network_cidr(self):
        """Participant range access (issue #1349): the portal/guacd egress allowlist
        is the range network CIDR so those workloads can dial range guests."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values = deploy.render_gcp_helm_values(config, outputs, image_tag=PINNED_IMAGE_TAG)

        assert values["networkPolicy"]["rangeAccessCidrs"] == ["10.50.0.0/16"]

    def test_range_access_cidrs_empty_when_range_network_cidr_absent(self):
        """No range network CIDR -> empty allowlist so the egress policy stays unrendered."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        outputs["range_network_cidr"] = {"value": ""}
        values = deploy.render_gcp_helm_values(config, outputs, image_tag=PINNED_IMAGE_TAG)

        assert values["networkPolicy"]["rangeAccessCidrs"] == []

    def test_rejects_insecure_public_bootstrap_values(self):
        """The Helm values renderer must refuse public bare-IP debug deployments on GCP."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        outputs["public_hostname"] = {"value": ""}
        outputs["managed_tls_enabled"] = {"value": False}

        with pytest.raises(ValueError, match="public_hostname"):
            deploy.render_gcp_helm_values(
                config,
                outputs,
                image_tag=PINNED_IMAGE_TAG,
            )

    def test_rejects_latest_image_tag(self):
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with pytest.raises(ValueError, match="latest"):
            deploy.render_gcp_helm_values(
                config,
                outputs,
                image_tag="latest",
            )

    def test_generated_values_carry_no_guacamole_secret_payload(self):
        """Generated Helm values reference the runtime Secret by name only (issue #1180).

        Guacamole DB and JSON-auth secrets live in Secret Manager and the
        out-of-band Kubernetes Secret; they must never be serialized into Helm
        values (and thus Helm release history).
        """
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        values = deploy.render_gcp_helm_values(config, outputs, image_tag=PINNED_IMAGE_TAG)

        assert values["guacamoleRuntimeSecret"] == {"name": "guacamole-runtime"}
        serialized = json.dumps(values)
        assert "POSTGRESQL_PASSWORD" not in serialized
        assert "JSON_SECRET_KEY" not in serialized
        assert "stringData" not in serialized


class TestGdcControlPlaneImages:
    def test_push_gcp_control_plane_images_uses_only_pinned_tags(self, capsys):
        outputs = _sample_gcp_control_plane_outputs("prod-rwctxzl6shxk")

        deploy.push_gcp_control_plane_images(outputs, image_tag=PINNED_IMAGE_TAG, dry_run=True)

        output = capsys.readouterr().out
        assert ":latest" not in output
        for image in ("portal", "pulumi-provisioner", "guacd", "guacamole-client"):
            assert f"{image}:{PINNED_IMAGE_TAG}" in output

    def test_resolve_gcp_control_plane_image_tag_prefers_env_override(self, monkeypatch):
        monkeypatch.setenv("SHIFTER_IMAGE_TAG", PINNED_IMAGE_TAG)

        assert deploy.resolve_gcp_control_plane_image_tag() == PINNED_IMAGE_TAG

    def test_resolve_gcp_control_plane_image_tag_uses_github_sha(self, monkeypatch):
        monkeypatch.delenv("SHIFTER_IMAGE_TAG", raising=False)
        monkeypatch.setenv("GITHUB_SHA", "abcdef1234567890")

        assert deploy.resolve_gcp_control_plane_image_tag() == "abcdef1"

    def test_resolve_gcp_control_plane_image_tag_falls_back_to_git_head(self, monkeypatch):
        monkeypatch.delenv("SHIFTER_IMAGE_TAG", raising=False)
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        expected = "def5678"

        with patch("deploy.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                ["git"],
                0,
                stdout=f"{expected}\n",
                stderr="",
            )

            assert deploy.resolve_gcp_control_plane_image_tag() == expected

        assert mock_run.call_args.args[0] == [
            "git",
            "-C",
            str(deploy.get_repo_root()),
            "rev-parse",
            "--short=7",
            "HEAD",
        ]


class TestGdcControlPlaneHelmChart:
    """Tests for the Helm chart that packages the GCP Shifter deployment."""

    def test_chart_renders_restricted_security_contexts_and_numeric_runtime_ids(self, tmp_path):
        """The chart must render restricted-compatible workloads with pinned runtime IDs."""
        helm = shutil.which("helm")
        if helm is None:
            pytest.skip("helm is required for chart render validation")

        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values_path = tmp_path / "values.json"
        values_path.write_text(
            json.dumps(
                deploy.render_gcp_helm_values(
                    config,
                    outputs,
                    image_tag=PINNED_IMAGE_TAG,
                )
            )
        )
        chart_dir = Path(__file__).resolve().parents[3] / "platform" / "charts" / "shifter"

        rendered = subprocess.Popen(  # nosec B603 B607
            [
                helm,
                "template",
                "shifter",
                str(chart_dir),
                "--namespace",
                "shifter-system",
                "--values",
                str(values_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = rendered.communicate()

        assert rendered.returncode == 0, stderr
        output = stdout
        assert "kind: Deployment" in output
        assert "name: portal-web" in output
        assert "name: worker-cms" in output
        assert "name: guacd" in output
        assert "name: guacamole-client" in output
        assert "type: RuntimeDefault" in output
        assert "allowPrivilegeEscalation: false" in output
        assert "runAsNonRoot: true" in output
        assert "runAsUser: 1000" in output
        assert "runAsGroup: 1000" in output
        assert "runAsUser: 1001" in output
        assert "runAsGroup: 1001" in output
        assert "kind: Namespace" not in output
        assert "kind: BackendConfig" in output
        assert "kind: NetworkPolicy" in output
        assert "name: default-deny-platform" in output
        assert "name: default-deny-jobs" in output
        assert "199.36.153.4/30" in output
        assert "10.40.0.10/32" in output
        # Participant/operator range access egress (issue #1349): the Helm path
        # must render the policy from networkPolicy.rangeAccessCidrs (fed by the
        # range_network_cidr Terraform output), scoped to the participant channel
        # ports -- asserted at the rendered-manifest level so values->template
        # wiring drift is caught, mirroring the Kustomize renderer's own test.
        assert "name: allow-platform-range-access-egress" in output
        assert "10.50.0.0/16" in output  # range_network_cidr from the sample outputs
        assert "port: 22" in output
        assert "port: 3389" in output
        assert 'requestPath: "/health/"' in output
        assert "securityPolicy:" in output
        assert "name: shifter-gcp-dev-edge" in output
        assert 'cloud.google.com/backend-config: "{\\"default\\":\\"portal-web\\"}"' in output
        assert 'cloud.google.com/backend-config: "{\\"default\\":\\"guacamole-client\\"}"' in output
        # The chart references the guacamole-runtime Secret; it must never create one (#1180).
        assert "kind: Secret" not in output

    def test_chart_never_renders_a_secret_even_when_values_carry_a_payload(self, tmp_path):
        """Defense in depth (#1180): the chart owns no Secret payload.

        Even if a caller injects secret material under guacamoleRuntimeSecret,
        the chart must not render a Kubernetes Secret or leak the values into
        rendered output / Helm release history. The runtime Secret is created
        out of band by the deploy bootstrap and consumed by reference only.
        """
        helm = shutil.which("helm")
        if helm is None:
            pytest.skip("helm is required for chart render validation")

        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values = deploy.render_gcp_helm_values(config, outputs, image_tag=PINNED_IMAGE_TAG)
        # Adversarial override: a caller tries to smuggle secrets through values.
        values["guacamoleRuntimeSecret"] = {
            "enabled": True,
            "name": "guacamole-runtime",
            "stringData": {
                "POSTGRESQL_PASSWORD": "should-not-render",
                "JSON_SECRET_KEY": "should-not-render",
            },
        }
        values_path = tmp_path / "values.json"
        values_path.write_text(json.dumps(values))
        chart_dir = Path(__file__).resolve().parents[3] / "platform" / "charts" / "shifter"

        rendered = subprocess.Popen(  # nosec B603 B607
            [
                helm,
                "template",
                "shifter",
                str(chart_dir),
                "--namespace",
                "shifter-system",
                "--values",
                str(values_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = rendered.communicate()

        assert rendered.returncode == 0, stderr
        assert "kind: Secret" not in stdout
        assert "should-not-render" not in stdout
        assert "POSTGRESQL_PASSWORD" not in stdout
        assert "JSON_SECRET_KEY" not in stdout


class TestGdcControlPlaneGuacamoleRuntimeSecret:
    """Tests for syncing guacamole-client runtime credentials outside Helm values."""

    def test_renders_guacamole_runtime_secret_manifest(self):
        manifest = deploy.render_gcp_guacamole_runtime_secret_manifest(
            {"username": "guac", "password": "supersecret"},
            "json-auth-key",
        )

        assert manifest == {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "guacamole-runtime",
                "namespace": "shifter-platform",
                "labels": {"app.kubernetes.io/part-of": "shifter"},
            },
            "type": "Opaque",
            "stringData": {
                "POSTGRESQL_USER": "guac",
                "POSTGRESQL_PASSWORD": "supersecret",
                "JSON_SECRET_KEY": "json-auth-key",
            },
        }

    def test_syncs_guacamole_runtime_secret_through_kubectl_stdin(self):
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

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

        with patch("deploy.subprocess.run", side_effect=subprocess_run) as mock_run:
            changed = deploy.sync_gcp_guacamole_runtime_secret(config, outputs)

        assert changed is True
        calls = [call.args[0] for call in mock_run.call_args_list]
        assert calls[0][:4] == ["gcloud", "secrets", "versions", "access"]
        assert calls[0][calls[0].index("--secret") + 1] == "shifter-gcp-dev-guacamole-db"
        assert calls[1][:4] == ["gcloud", "secrets", "versions", "access"]
        assert calls[1][calls[1].index("--secret") + 1] == "shifter-gcp-dev-guacamole-json-auth"
        assert calls[2] == ["kubectl", "apply", "-f", "-"]
        assert "supersecret" not in " ".join(calls[2])
        applied = json.loads(mock_run.call_args_list[2].kwargs["input"])
        assert applied["metadata"]["name"] == "guacamole-runtime"
        assert applied["stringData"]["POSTGRESQL_PASSWORD"] == "supersecret"

    def test_dry_run_does_not_fetch_or_apply_guacamole_runtime_secret(self):
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with patch("deploy.subprocess.run") as mock_run:
            changed = deploy.sync_gcp_guacamole_runtime_secret(config, outputs, dry_run=True)

        assert changed is False
        mock_run.assert_not_called()


class TestGdcControlPlaneNamespaces:
    """Tests for namespace lifecycle outside the Helm release."""

    def test_creates_required_namespaces_with_restricted_labels(self):
        """Bootstrap must create Helm target namespaces before the release installs."""
        missing_platform = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            stdout="",
            stderr='Error from server (NotFound): namespaces "shifter-platform" not found',
        )
        active_platform = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps({"status": {"phase": "Active"}}),
            stderr="",
        )
        missing_jobs = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            stdout="",
            stderr='Error from server (NotFound): namespaces "shifter-jobs" not found',
        )
        active_jobs = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps({"status": {"phase": "Active"}}),
            stderr="",
        )

        with patch(
            "deploy.subprocess.run",
            side_effect=[
                missing_platform,
                subprocess.CompletedProcess(["kubectl"], 0, stdout="namespace/shifter-platform created\n", stderr=""),
                active_platform,
                missing_jobs,
                subprocess.CompletedProcess(["kubectl"], 0, stdout="namespace/shifter-jobs created\n", stderr=""),
                active_jobs,
            ],
        ) as mock_subprocess:
            deploy.ensure_gcp_control_plane_namespaces()

        apply_calls = [
            call for call in mock_subprocess.call_args_list if call.args[0][:3] == ["kubectl", "apply", "-f"]
        ]
        assert len(apply_calls) == 2
        platform_manifest = json.loads(apply_calls[0].kwargs["input"])
        jobs_manifest = json.loads(apply_calls[1].kwargs["input"])
        assert platform_manifest["metadata"]["name"] == "shifter-platform"
        assert platform_manifest["metadata"]["labels"]["app.kubernetes.io/part-of"] == "shifter"
        assert platform_manifest["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
        assert jobs_manifest["metadata"]["name"] == "shifter-jobs"
        assert jobs_manifest["metadata"]["labels"]["shifter.dev/plane"] == "jobs"

    def test_waits_for_terminating_namespace_then_recreates_it(self):
        """A terminating namespace from a failed install must be allowed to clear first."""
        terminating_platform = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps(
                {
                    "metadata": {"deletionTimestamp": "2026-04-10T00:00:00Z"},
                    "status": {"phase": "Terminating"},
                }
            ),
            stderr="",
        )
        missing_platform = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            stdout="",
            stderr='Error from server (NotFound): namespaces "shifter-platform" not found',
        )
        active_platform = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps({"status": {"phase": "Active"}}),
            stderr="",
        )
        active_jobs = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps({"status": {"phase": "Active"}}),
            stderr="",
        )

        with (
            patch(
                "deploy.subprocess.run",
                side_effect=[
                    terminating_platform,
                    missing_platform,
                    subprocess.CompletedProcess(
                        ["kubectl"],
                        0,
                        stdout="namespace/shifter-platform created\n",
                        stderr="",
                    ),
                    active_platform,
                    active_jobs,
                    subprocess.CompletedProcess(
                        ["kubectl"],
                        0,
                        stdout="namespace/shifter-jobs configured\n",
                        stderr="",
                    ),
                    active_jobs,
                ],
            ) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.ensure_gcp_control_plane_namespaces()

        mock_sleep.assert_not_called()
        apply_calls = [
            call for call in mock_subprocess.call_args_list if call.args[0][:3] == ["kubectl", "apply", "-f"]
        ]
        assert len(apply_calls) == 2


class TestGdcHelmCutover:
    """Tests for the breaking cutover from legacy raw manifests to Helm."""

    def test_first_install_deletes_legacy_resources_before_helm_takes_over(self):
        """A non-Helm legacy deployment must be removed before the first Helm install."""
        with (
            patch("deploy.helm_release_exists", return_value=False),
            patch(
                "deploy.list_gcp_helm_cutover_resources",
                side_effect=lambda namespace: {
                    "shifter-system": [],
                    "shifter-platform": [
                        "configmap/platform-runtime",
                        "deployment.apps/portal-web",
                        "secret/guacamole-runtime",
                        "serviceaccount/portal",
                    ],
                    "shifter-jobs": ["serviceaccount/provisioner"],
                }[namespace],
            ),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.prepare_gcp_helm_cutover()

        commands = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert commands == [
            [
                "kubectl",
                "-n",
                "shifter-platform",
                "delete",
                "configmap/platform-runtime",
                "deployment.apps/portal-web",
                "secret/guacamole-runtime",
                "serviceaccount/portal",
                "--ignore-not-found=true",
                "--wait=true",
                "--timeout=10m",
            ],
            [
                "kubectl",
                "-n",
                "shifter-jobs",
                "delete",
                "serviceaccount/provisioner",
                "--ignore-not-found=true",
                "--wait=true",
                "--timeout=10m",
            ],
        ]

    def test_existing_helm_release_skips_namespace_cleanup(self):
        """Reruns must not delete namespaces once Helm already owns the environment."""
        with (
            patch("deploy.helm_release_exists", return_value=True),
            patch("deploy.list_gcp_helm_cutover_resources") as mock_list,
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.prepare_gcp_helm_cutover()

        mock_list.assert_not_called()
        mock_run_cmd.assert_not_called()

    def test_missing_namespace_is_treated_as_no_legacy_resources(self):
        """Cutover inspection must tolerate namespaces that do not exist yet."""
        not_found = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            stdout="",
            stderr='Error from server (NotFound): namespaces "shifter-jobs" not found',
        )

        with patch("deploy.subprocess.run", return_value=not_found):
            assert deploy.list_gcp_helm_cutover_resources("shifter-jobs") == []

    def test_explicit_runtime_objects_are_included_even_without_labels(self):
        """Legacy runtime config objects from the raw path must still be purged."""
        labeled = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout="serviceaccount/portal\n",
            stderr="",
        )
        explicit = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout="configmap/platform-runtime\nsecret/guacamole-runtime\n",
            stderr="",
        )

        with patch("deploy.subprocess.run", side_effect=[labeled, explicit]):
            assert deploy.list_gcp_helm_cutover_resources("shifter-platform") == [
                "configmap/platform-runtime",
                "secret/guacamole-runtime",
                "serviceaccount/portal",
            ]


class TestGkeGcloudAuthPlugin:
    """Tests for ensuring the local GKE kubectl auth plugin."""

    def test_skips_install_when_plugin_already_present(self):
        """No package-manager calls should run when the plugin is already on PATH."""
        with (
            patch("deploy.shutil.which", return_value="/usr/bin/gke-gcloud-auth-plugin"),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gke_gcloud_auth_plugin()

        mock_run_cmd.assert_not_called()

    def test_installs_plugin_with_apt_when_running_as_root(self):
        """On apt-based systems, bootstrap should install the plugin automatically."""

        def fake_which(cmd: str) -> str | None:
            if cmd == "gke-gcloud-auth-plugin":
                return None if fake_which.calls == 0 else "/usr/bin/gke-gcloud-auth-plugin"
            if cmd == "apt-get":
                return "/usr/bin/apt-get"
            return None

        fake_which.calls = 0

        def which_side_effect(cmd: str) -> str | None:
            result = fake_which(cmd)
            if cmd == "gke-gcloud-auth-plugin":
                fake_which.calls += 1
            return result

        with (
            patch("deploy.shutil.which", side_effect=which_side_effect),
            patch("deploy.os.geteuid", return_value=0),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gke_gcloud_auth_plugin()

        commands = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert commands == [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", "google-cloud-cli-gke-gcloud-auth-plugin"],
        ]

    def test_uses_sudo_when_not_running_as_root(self):
        """Non-root bootstrap runs should elevate for the plugin install."""

        def fake_which(cmd: str) -> str | None:
            if cmd == "gke-gcloud-auth-plugin":
                return None if fake_which.calls == 0 else "/usr/bin/gke-gcloud-auth-plugin"
            if cmd == "apt-get":
                return "/usr/bin/apt-get"
            if cmd == "sudo":
                return "/usr/bin/sudo"
            return None

        fake_which.calls = 0

        def which_side_effect(cmd: str) -> str | None:
            result = fake_which(cmd)
            if cmd == "gke-gcloud-auth-plugin":
                fake_which.calls += 1
            return result

        with (
            patch("deploy.shutil.which", side_effect=which_side_effect),
            patch("deploy.os.geteuid", return_value=1000),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gke_gcloud_auth_plugin()

        commands = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert commands == [
            ["sudo", "apt-get", "update"],
            ["sudo", "apt-get", "install", "-y", "google-cloud-cli-gke-gcloud-auth-plugin"],
        ]

    def test_uses_user_space_install_when_not_root_and_sudo_unavailable(self):
        """Bootstrap should fall back to a user-space plugin install when sudo is unavailable."""
        with (
            patch(
                "deploy.shutil.which",
                side_effect=lambda cmd: (
                    None
                    if cmd in {"gke-gcloud-auth-plugin", "sudo"}
                    else "/usr/bin/apt-get"
                    if cmd == "apt-get"
                    else None
                ),
            ),
            patch("deploy.os.geteuid", return_value=1000),
            patch("deploy.install_gke_gcloud_auth_plugin_user_space") as mock_user_space_install,
        ):
            deploy.ensure_gke_gcloud_auth_plugin(dry_run=True)

        mock_user_space_install.assert_called_once_with(dry_run=True)

    def test_fails_when_plugin_missing_and_host_is_not_apt_based(self):
        """Bootstrap must fail clearly when it cannot satisfy the plugin prerequisite."""
        with (
            patch("deploy.shutil.which", return_value=None),
            patch("deploy.error") as mock_error,
            pytest.raises(SystemExit),
        ):
            deploy.ensure_gke_gcloud_auth_plugin()

        mock_error.assert_called_once()
        assert (
            "Automatic installation requires the gcloud component manager or apt-based package tooling"
            in mock_error.call_args.args[0]
        )


class TestGcloudComponentsInstallGkePlugin:
    """Tests for deploy._gcloud_components_install_gke_plugin."""

    def test_returns_false_when_gcloud_absent(self):
        with patch("deploy.shutil.which", return_value=None):
            assert deploy._gcloud_components_install_gke_plugin() is False

    def test_dry_run_reports_success_without_running(self):
        with patch("deploy.shutil.which", return_value="/usr/bin/gcloud"), patch("subprocess.run") as mock_run:
            assert deploy._gcloud_components_install_gke_plugin(dry_run=True) is True

        mock_run.assert_not_called()

    def test_returns_true_on_successful_install(self):
        with (
            patch("deploy.shutil.which", return_value="/usr/bin/gcloud"),
            patch("subprocess.run", return_value=_completed(returncode=0)),
        ):
            assert deploy._gcloud_components_install_gke_plugin() is True

    def test_returns_false_and_surfaces_stderr_on_failure(self, capsys):
        with (
            patch("deploy.shutil.which", return_value="/usr/bin/gcloud"),
            patch("subprocess.run", return_value=_completed(returncode=1, stderr="component manager disabled")),
        ):
            assert deploy._gcloud_components_install_gke_plugin() is False

        assert "component manager disabled" in capsys.readouterr().err


class TestGkeGcloudAuthPluginUserSpaceInstall:
    """Tests for the user-space GKE auth plugin install path."""

    def test_extracts_package_and_copies_binary_into_local_bin(self, tmp_path):
        """The user-space installer must stage the binary into ~/.local/bin."""

        def fake_subprocess(cmd, cwd=None, **kwargs):
            if cmd[:2] == ["apt", "download"]:
                package = Path(cwd) / "google-cloud-cli-gke-gcloud-auth-plugin_564.0.0-0_amd64.deb"
                package.write_text("fake-deb")
            elif cmd[:2] == ["dpkg-deb", "-x"]:
                extract_root = Path(cmd[3])
                binary = extract_root / "usr" / "lib" / "google-cloud-sdk" / "bin" / "gke-gcloud-auth-plugin"
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("plugin")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch(
                "deploy.shutil.which",
                side_effect=lambda cmd: "/usr/bin/" + cmd if cmd in {"apt", "dpkg-deb"} else None,
            ),
            patch("deploy.tempfile.TemporaryDirectory", return_value=nullcontext(str(tmp_path))),
            patch("deploy.Path.home", return_value=tmp_path),
            patch("deploy.subprocess.run", side_effect=fake_subprocess),
        ):
            deploy.install_gke_gcloud_auth_plugin_user_space()

        destination = tmp_path / ".local" / "bin" / "gke-gcloud-auth-plugin"
        assert destination.exists()
        assert destination.read_text() == "plugin"


class TestGcpPlatformCoreContracts:
    """Tests for the Terraform platform-core contract that bootstrap depends on."""

    def test_workload_identity_bindings_exist_for_platform_service_accounts(self):
        """Portal, workers, and provisioner KSAs must be able to impersonate their GSAs."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "portal"
            / "iam"
            / "main.tf"
        )
        module_main = module_path.read_text()

        assert 'resource "google_service_account_iam_member" "workload_identity"' in module_main
        assert 'role               = "roles/iam.workloadIdentityUser"' in module_main
        assert '"serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/portal]"' in module_main
        assert '"serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/workers]"' in module_main
        assert '"serviceAccount:${var.project_id}.svc.id.goog[shifter-jobs/provisioner]"' in module_main

    def test_workers_have_pubsub_publish_and_subscribe_permissions(self):
        """The shared workers service account must publish as well as consume Pub/Sub events."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "portal"
            / "iam"
            / "main.tf"
        )
        module_main = module_path.read_text()

        workers_section = module_main.split("workers = toset([", 1)[1].split("])", 1)[0]
        assert '"roles/pubsub.publisher"' in workers_section
        assert '"roles/pubsub.subscriber"' in workers_section

    def test_portal_has_identity_platform_viewer_permissions(self):
        """Portal auth needs read access to Identity Platform user records for token verification."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "portal"
            / "iam"
            / "main.tf"
        )
        module_main = module_path.read_text()

        portal_section = module_main.split("portal = toset([", 1)[1].split("])", 1)[0]
        assert '"roles/firebaseauth.viewer"' in portal_section

    def test_identity_platform_self_signup_is_allowed_and_guarded_by_before_create_trigger(self):
        """GCP corporate registration must stay open to eligible users and be gated by a blocking function."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "portal"
            / "identity-platform"
            / "main.tf"
        )
        module_main = module_path.read_text()

        identity_platform_section = module_main.split('resource "google_identity_platform_config" "platform" {', 1)[1]
        assert "disabled_user_signup   = false" in identity_platform_section
        assert 'event_type   = "beforeCreate"' in identity_platform_section
        # The blocking function is optional because Domain Restricted Sharing can
        # block its allUsers invoker, so the trigger is count-gated.
        assert (
            "google_cloudfunctions_function.identity_platform_before_create[0].https_trigger_url"
            in identity_platform_section
        )

    def test_cloud_armor_sqli_rule_uses_baseline_sensitivity(self):
        """The edge WAF should run SQLi detection at the PL1 baseline to avoid login false positives."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "portal"
            / "ingress"
            / "main.tf"
        )
        module_main = module_path.read_text()

        assert "evaluatePreconfiguredWaf('sqli-v33-stable'" in module_main
        assert "'sensitivity': 1" in module_main
        assert "opt_out_rule_ids" not in module_main


class TestGcpBootstrapIdentityPlatform:
    """Tests for Identity Platform bootstrap user sourcing and seeding."""

    def test_parse_simple_env_file_handles_quoted_values(self, tmp_path):
        """Simple env parsing should strip matching quotes and ignore comments."""
        env_path = tmp_path / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "# Comment",
                    'OIDC_RP_CLIENT_ID="client-id"',
                    "OIDC_RP_CLIENT_SECRET='client-secret'",
                    "OIDC_ISSUER_URL=https://issuer.example.test/",
                    'OIDC_AUTH_DOMAIN="https://auth.example.test"',
                    "",
                ]
            )
        )

        assert deploy.parse_simple_env_file(env_path) == {
            "OIDC_RP_CLIENT_ID": "client-id",
            "OIDC_RP_CLIENT_SECRET": "client-secret",
            "OIDC_ISSUER_URL": "https://issuer.example.test/",
            "OIDC_AUTH_DOMAIN": "https://auth.example.test",
        }

    def _write_gcp_dev_overlay(self, repo_root: Path, body: str) -> Path:
        overlay = repo_root / gcp_control_plane._GCP_DEV_TFVARS_OVERLAY
        overlay.parent.mkdir(parents=True, exist_ok=True)
        overlay.write_text(body)
        return overlay

    def test_gcp_bootstrap_creds_from_tfvars_maps_overlay_keys(self, tmp_path):
        """The gcp-dev overlay's HCL creds map to the GCP_BOOTSTRAP_ADMIN_* env keys."""
        self._write_gcp_dev_overlay(
            tmp_path,
            "\n".join(
                [
                    'project_id                   = "prod-ksqdkj"',
                    'gcp_bootstrap_admin_email    = "operator@paloaltonetworks.com"',
                    'gcp_bootstrap_admin_password = "Galvatron7!!!"',
                    "",
                ]
            ),
        )

        assert gcp_control_plane._gcp_bootstrap_creds_from_tfvars(tmp_path) == {
            "GCP_BOOTSTRAP_ADMIN_EMAIL": "operator@paloaltonetworks.com",
            "GCP_BOOTSTRAP_ADMIN_PASSWORD": "Galvatron7!!!",
        }

    def test_gcp_bootstrap_creds_from_tfvars_absent_overlay_returns_empty(self, tmp_path):
        """A missing (gitignored) overlay yields no creds so the bootstrap falls back."""
        assert gcp_control_plane._gcp_bootstrap_creds_from_tfvars(tmp_path) == {}

    def test_load_bootstrap_env_values_overlay_overrides_process_env(self, tmp_path, monkeypatch):
        """The tfvars overlay is authoritative: it overrides a stale process-env password."""
        self._write_gcp_dev_overlay(
            tmp_path,
            'gcp_bootstrap_admin_password = "from-overlay"\n',
        )
        monkeypatch.setenv("GCP_BOOTSTRAP_ADMIN_PASSWORD", "from-process-env")

        values = gcp_control_plane.load_bootstrap_env_values(repo_root=tmp_path)

        assert values["GCP_BOOTSTRAP_ADMIN_PASSWORD"] == "from-overlay"

    def test_resolve_gcp_bootstrap_operator_credentials_returns_none_when_missing(self):
        """Bootstrap should report no operator credentials when the env files do not provide them."""
        assert deploy.resolve_gcp_bootstrap_operator_credentials(env_values={}) is None

    def test_resolve_gcp_bootstrap_operator_credentials_uses_env_values(self):
        """Bootstrap should source the first operator credentials from env-backed values when present."""
        credentials = deploy.resolve_gcp_bootstrap_operator_credentials(
            env_values={
                "GCP_BOOTSTRAP_ADMIN_EMAIL": "analyst@paloaltonetworks.com",
                "GCP_BOOTSTRAP_ADMIN_PASSWORD": "correct-horse-battery-staple",
            },
        )

        assert credentials == ("analyst@paloaltonetworks.com", "correct-horse-battery-staple")

    def test_ensure_gcp_identity_platform_operator_creates_user(self):
        """Bootstrap must create the first operator via the Identity Platform admin API."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("analyst@paloaltonetworks.com", "correct-horse-battery-staple"),
            ),
            patch("deploy._gcp_identity_admin_request", return_value={"localId": "user-123"}) as mock_request,
        ):
            deploy.ensure_gcp_identity_platform_operator(config, outputs)

        mock_request.assert_called_once_with(
            config=config,
            outputs=outputs,
            path=f"/projects/{config.project_id}/accounts",
            payload={
                "email": "analyst@paloaltonetworks.com",
                "password": "correct-horse-battery-staple",
                "displayName": "Shifter Operator",
                "emailVerified": True,
            },
        )

    def test_ensure_gcp_identity_platform_operator_returns_operator_email(self):
        """Bootstrap should return the first operator email so the runtime can elevate that user."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("analyst@paloaltonetworks.com", "correct-horse-battery-staple"),
            ),
            patch("deploy._gcp_identity_admin_request", return_value={"localId": "user-123"}),
        ):
            email = deploy.ensure_gcp_identity_platform_operator(config, outputs)

        assert email == "analyst@paloaltonetworks.com"

    def test_ensure_gcp_identity_platform_operator_skips_existing_user(self):
        """Bootstrap should treat an existing operator account as success."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("analyst@paloaltonetworks.com", "correct-horse-battery-staple"),
            ),
            patch("deploy._gcp_identity_admin_request", side_effect=RuntimeError("EMAIL_EXISTS")) as mock_request,
        ):
            result = deploy.ensure_gcp_identity_platform_operator(config, outputs)

        mock_request.assert_called_once()
        assert result == "analyst@paloaltonetworks.com"

    def test_ensure_gcp_identity_platform_operator_prompts_when_env_missing(self):
        """Interactive bootstrap should prompt for the first operator when env values are absent."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch("deploy.resolve_gcp_bootstrap_operator_credentials", return_value=None),
            patch(
                "deploy.prompt_for_gcp_bootstrap_operator_credentials",
                return_value=("analyst@paloaltonetworks.com", "correct-horse-battery-staple"),
            ) as mock_prompt,
            patch("deploy._gcp_identity_admin_request", return_value={"localId": "user-123"}) as mock_request,
        ):
            email = deploy.ensure_gcp_identity_platform_operator(config, outputs)

        mock_prompt.assert_called_once_with()
        assert email == "analyst@paloaltonetworks.com"
        mock_request.assert_called_once_with(
            config=config,
            outputs=outputs,
            path=f"/projects/{config.project_id}/accounts",
            payload={
                "email": "analyst@paloaltonetworks.com",
                "password": "correct-horse-battery-staple",
                "displayName": "Shifter Operator",
                "emailVerified": True,
            },
        )

    def test_ensure_gcp_identity_platform_operator_rejects_non_corporate_email(self):
        """Bootstrap must reject an operator email outside the
        identity_allowed_email_domain Terraform output before touching
        Identity Platform — that domain is the same allow-list the
        Identity Platform beforeCreate hook enforces."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        # _sample_gcp_control_plane_outputs sets identity_allowed_email_domain
        # to "paloaltonetworks.com"; an email outside that domain must fail.

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("intruder@example.com", "correct-horse-battery-staple"),
            ),
            pytest.raises(ValueError, match=r"paloaltonetworks\.com"),
        ):
            deploy.ensure_gcp_identity_platform_operator(config, outputs)

    def test_ensure_gcp_identity_platform_operator_env_fallback(self, monkeypatch):
        """When no identity_allowed_email_domain output is supplied (e.g., a dry
        run before terraform apply), SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN is the
        fallback enforcement seam."""
        monkeypatch.setenv("SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN", "example.org")
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        outputs.pop("identity_allowed_email_domain")  # simulate no terraform output

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("intruder@example.com", "correct-horse-battery-staple"),
            ),
            pytest.raises(ValueError, match=r"example\.org"),
        ):
            deploy.ensure_gcp_identity_platform_operator(config, outputs)

    def test_ensure_gcp_identity_platform_operator_rejects_malformed_email(self):
        """Bootstrap must fail before touching Identity Platform when the operator email is malformed."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("not-an-email", "correct-horse-battery-staple"),
            ),
            pytest.raises(ValueError, match=r"@"),
        ):
            deploy.ensure_gcp_identity_platform_operator(config, outputs)

    def test_render_gcp_platform_runtime_env_elevates_bootstrap_operator(self):
        """The generated runtime env should elevate the first operator without hardcoding an email in the repo."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.render_gcp_platform_runtime_env(
            config,
            bootstrap_operator_email="admin@example.com",
            bootstrap_env_values={},
        )

        assert "PLATFORM_BOOTSTRAP_STAFF_EMAILS=admin@example.com\n" in rendered
        assert "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=admin@example.com\n" in rendered
        assert "GCP_RANGE_BACKEND=gce\n" in rendered
        assert "ENGINE_TASK_SERVICE_ACCOUNT_NAME=provisioner\n" in rendered
        # CLOUD_PROVIDER must come from the GCP backend runtime-env renderer only
        # (PLAT-2005): _render_gcp_runtime_env merges this bootstrap-owned contract
        # with scripts/gcp/render_runtime_env.py's output, which is the
        # renderer-owned source of the backend identity. A second hardcoded literal
        # here would be redundant and could silently drift from that value.
        assert "CLOUD_PROVIDER" not in deploy.parse_env_contract(rendered)

    def test_render_gcp_platform_runtime_env_uses_blank_guest_password_samples(self):
        """The generated env contract must not embed sample guest passwords in source-controlled output."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.render_gcp_platform_runtime_env(
            config,
            bootstrap_operator_email="admin@example.com",
            bootstrap_env_values={},
        )

        # Issue #762: per-instance guest passwords replace shared env
        # entries. The bootstrap-rendered platform-runtime env file must
        # not advertise these legacy keys, and never the legacy literal.
        assert "GDC_WINDOWS_ADMIN_PASSWORD" not in rendered
        assert "GDC_KALI_PASSWORD" not in rendered
        assert "GDC_UBUNTU_PASSWORD" not in rendered
        assert "CortexSavesTheDay!" not in rendered
        assert "kali:kali" not in rendered
        assert "ubuntu:ubuntu" not in rendered

    def test_render_gcp_platform_runtime_env_wires_guest_image_urls_from_bucket(self):
        """Guest boot images resolve to the packer-gcp export bucket per environment."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1", environment="gcp-dev")

        rendered = deploy.render_gcp_platform_runtime_env(config, bootstrap_env_values={})

        bucket = "shifter-gcp-dev-gdc-vm-images"
        assert f"GDC_UBUNTU_IMAGE_URL=gs://{bucket}/ubuntu.qcow2\n" in rendered
        assert f"GDC_KALI_IMAGE_URL=gs://{bucket}/kali.qcow2\n" in rendered
        assert f"GDC_WINDOWS_IMAGE_URL=gs://{bucket}/windows.qcow2\n" in rendered
        assert f"GDC_DC_IMAGE_URL=gs://{bucket}/dc.qcow2\n" in rendered
        assert "GDC_KALI_DISK_SIZE_GIB=40\n" in rendered
        assert "GDC_UBUNTU_IMAGE_URL=\n" not in rendered

    def test_render_gcp_platform_runtime_env_emits_aws_region_for_provisioner_policy(self):
        """AWS_REGION rides the ConfigMap so the range-Job admission policy passes (#1742).

        Django settings alias AWS_REGION to CLOUD_REGION, so the provisioner-launcher
        always emits a non-empty AWS_REGION even on GCP; restrict-provisioner-jobs then
        requires it to exist in platform-runtime with a matching value.
        """
        config = deploy.GDCBootstrapConfig(
            project_id="prod-rwctxzl6shxk", cluster_id="cluster1", environment="gcp-dev", region="us-central1"
        )

        rendered = deploy.render_gcp_platform_runtime_env(config, bootstrap_env_values={})

        assert "AWS_REGION=us-central1\n" in rendered
        assert "CLOUD_REGION=us-central1\n" in rendered


class TestArtifactRegistryServiceIdentity:
    """Tests for pre-provisioning the Artifact Registry service identity."""

    def test_dry_run_skips_network_calls(self):
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch("subprocess.run") as mock_run, patch("deploy.urllib_request.urlopen") as mock_urlopen:
            deploy.ensure_gcp_artifact_registry_service_identity(config, dry_run=True)

        mock_run.assert_not_called()
        mock_urlopen.assert_not_called()


class TestProvisionerLauncherDeploymentParity:
    """Launcher identity must stay consistent across Terraform, bootstrap, Helm, and runtime config."""

    def test_bootstrap_renders_dedicated_launcher_without_provisioner_cloud_identity(self):
        service_accounts = _sample_gcp_control_plane_outputs()["workload_service_accounts"]["value"]

        values = gcp_control_plane._helm_service_account_values(service_accounts)

        assert values["provisionerLauncher"] == {
            "name": "provisioner-launcher",
            "annotations": {
                "iam.gke.io/gcp-service-account": service_accounts["provisioner-launcher"],
            },
        }
        assert values["provisioner"]["annotations"]["iam.gke.io/gcp-service-account"] == service_accounts["provisioner"]
        assert service_accounts["provisioner-launcher"] != service_accounts["provisioner"]

    def test_runtime_and_terraform_keep_launcher_and_privileged_runtime_distinct(self):
        terraform_iam = (
            gcp_control_plane.get_repo_root()
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "portal"
            / "iam"
            / "main.tf"
        ).read_text(encoding="utf-8")
        assert '"provisioner-launcher"' in terraform_iam
        assert "shifter-platform/provisioner-launcher" in terraform_iam
        assert "provisioner-launcher = toset([])" in terraform_iam
        assert (
            'secret_reader_workloads    = toset(["portal", "workers", "ctf-scheduler", "provisioner-launcher"])'
            in terraform_iam
        )


class TestGcpIdentityAdminApi:
    """Tests for the authenticated Identity Platform bootstrap admin requests."""

    def test_gcp_identity_admin_request_uses_authenticated_project_endpoint_without_api_key(self):
        """Bootstrap must use the authenticated project-scoped admin endpoint without appending a web API key."""

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"localId":"user-123"}'

        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch("deploy._gcp_identity_access_token", return_value="test-access-token"),
            patch("deploy.urllib_request.urlopen", return_value=_FakeResponse()) as mock_urlopen,
        ):
            result = deploy._gcp_identity_admin_request(
                config=config,
                outputs=outputs,
                path=f"/projects/{config.project_id}/accounts",
                payload={"email": "analyst@paloaltonetworks.com", "password": "correct-horse-battery-staple"},
            )

        assert result == {"localId": "user-123"}
        request = mock_urlopen.call_args.args[0]
        assert request.full_url == (f"https://identitytoolkit.googleapis.com/v1/projects/{config.project_id}/accounts")
        assert request.headers["Authorization"] == "Bearer test-access-token"
        assert request.headers["Content-type"] == "application/json"
        assert request.headers["X-goog-user-project"] == config.project_id

    def test_gcp_identity_admin_request_surfaces_identity_platform_error_messages(self):
        """Bootstrap must surface the actual Identity Platform admin error when the request fails."""

        class _FakeHttpError(deploy.urllib_error.HTTPError):
            def __init__(self) -> None:
                super().__init__(
                    url="https://identitytoolkit.googleapis.com/v1/projects/prod-rwctxzl6shxk/accounts",
                    code=400,
                    msg="Bad Request",
                    hdrs=None,
                    fp=io.BytesIO(b'{"error":{"message":"EMAIL_EXISTS"}}'),
                )

        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch("deploy._gcp_identity_access_token", return_value="test-access-token"),
            patch("deploy.urllib_request.urlopen", side_effect=_FakeHttpError()),
            pytest.raises(RuntimeError, match="EMAIL_EXISTS"),
        ):
            deploy._gcp_identity_admin_request(
                config=config,
                outputs=outputs,
                path=f"/projects/{config.project_id}/accounts",
                payload={"email": "analyst@paloaltonetworks.com", "password": "correct-horse-battery-staple"},
            )


class TestGcpBootstrapDnsTlsFlow:
    """Tests for the post-ingress DNS/TLS walkthrough."""

    def test_wait_for_gcp_managed_certificate_active_retries_until_active(self):
        """Bootstrap must wait for the managed certificate to become Active before declaring success."""
        with (
            patch(
                "deploy.get_gcp_managed_certificate_status",
                side_effect=["Provisioning", "Provisioning", "Active"],
            ) as mock_status,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.wait_for_gcp_managed_certificate_active(timeout_seconds=60, poll_seconds=0)

        assert mock_status.call_count == 3
        assert mock_sleep.call_count == 2

    def test_walkthrough_gcp_dns_setup_and_waits_for_tls(self):
        """Bootstrap should guide DNS setup after ingress exists, then verify TLS and the public portal."""
        outputs = _sample_gcp_control_plane_outputs()

        with (
            patch("deploy.wait_for_user") as mock_wait_for_user,
            patch("deploy.wait_for_gcp_managed_certificate_active") as mock_wait_for_tls,
            patch("deploy.verify_gcp_public_portal") as mock_verify_portal,
        ):
            deploy.walkthrough_gcp_dns_setup_and_wait_for_tls(outputs)

        mock_wait_for_user.assert_called_once()
        mock_wait_for_tls.assert_called_once_with()
        mock_verify_portal.assert_called_once_with("portal.example.test")


class TestGdcBootstrapRangeBackend:
    """gdc_bootstrap_cluster gates the ABM/GDC substrate on the range backend (#1716)."""

    def test_gce_backend_skips_substrate_and_deploys_control_plane(self):
        """The gce backend never touches the substrate (no SA-key creation) and deploys the control plane."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1", range_backend="gce")
        with (
            patch("gcp_control_plane.confirm", return_value=True),
            patch("gcp_control_plane.ensure_gdc_apis") as mock_apis,
            patch("gcp_control_plane.ensure_gdc_service_account") as mock_sa,
            patch("gcp_control_plane.stage_gdc_bootstrap_assets") as mock_stage,
            patch("gcp_control_plane.sync_gdc_vm_image_secret") as mock_vm_image,
            patch(
                "gcp_control_plane.bootstrap_gcp_control_plane",
                return_value={"gke_cluster_name": {"value": "shifter-gcp-dev-platform"}},
            ) as mock_platform,
        ):
            result = gcp_control_plane.gdc_bootstrap_cluster(config, dry_run=False)

        mock_apis.assert_not_called()
        mock_sa.assert_not_called()
        mock_stage.assert_not_called()
        mock_vm_image.assert_not_called()
        mock_platform.assert_called_once_with(config, dry_run=False)
        assert result["gke_cluster_name"] == "shifter-gcp-dev-platform"
        assert result["workstation"] == ""
        assert result["gdc_vm_image_gcs_secret_id"] == ""

    def test_gdc_backend_builds_substrate_before_control_plane(self, tmp_path):
        """The gdc backend still builds the substrate (including the vm-image secret) before the control plane."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1", range_backend="gdc")
        staged = {
            "ssh_metadata": tmp_path / "ssh-metadata",
            "assets_dir": tmp_path / "assets",
            "service_account_key": tmp_path / "bm-gcr.json",
        }
        with (
            patch("gcp_control_plane.confirm", return_value=True),
            patch("gcp_control_plane.ensure_gdc_apis") as mock_apis,
            patch("gcp_control_plane.ensure_gdc_service_account"),
            patch("gcp_control_plane.stage_gdc_bootstrap_assets", return_value=staged),
            patch("gcp_control_plane.ensure_gdc_network"),
            patch("gcp_control_plane.ensure_gdc_instances"),
            patch("gcp_control_plane.sync_gdc_instance_ssh_metadata"),
            patch("gcp_control_plane.wait_for_gdc_ssh"),
            patch("gcp_control_plane.upload_gdc_assets"),
            patch("gcp_control_plane.run_gdc_workstation_script"),
            patch("gcp_control_plane.sync_gdc_access_secret"),
            patch("gcp_control_plane.sync_gdc_vm_image_secret") as mock_vm_image,
            patch("gcp_control_plane.bootstrap_gcp_control_plane", return_value={}),
        ):
            result = gcp_control_plane.gdc_bootstrap_cluster(config, dry_run=False)

        mock_apis.assert_called_once()
        mock_vm_image.assert_called_once()
        assert result["workstation"] == config.workstation.name
