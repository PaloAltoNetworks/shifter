"""Behavior tests for the shared deploy/bootstrap preflight (preflight.py)."""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

import deploy
import preflight
from preflight import Cloud, Mode, Status

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SECRETS_DOC = REPO_ROOT / "docs" / "dev" / "deploy-secrets.md"

# Full set of GCP secrets present in a healthy CI environment.
GCP_CI_ENV = {
    "GCP_PROJECT_ID": "prod-ksqdkj",
    "GCP_PUBLIC_HOSTNAME": "gcp.example.test",
    "GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN": "example.test",
    "GCP_SERVICE_ACCOUNT": "deploy@prod-ksqdkj.iam.gserviceaccount.com",
    "GCP_WORKLOAD_IDENTITY_PROVIDER": "projects/1/locations/global/workloadIdentityPools/p/providers/gh",
    "GCP_BOOTSTRAP_ADMIN_EMAIL": "operator@example.test",
    "GCP_BOOTSTRAP_ADMIN_PASSWORD": "Galvatron7!!!",
}


@pytest.fixture
def mock_stdin_tty():
    with patch("sys.stdin.isatty", return_value=True):
        yield


@pytest.fixture
def mock_stdin_non_tty():
    with patch("sys.stdin.isatty", return_value=False):
        yield


@pytest.fixture(autouse=True)
def prevent_hanging_on_input():
    """Guard: no test may block on real stdin."""
    with patch("builtins.input", return_value=""):
        yield


# --- Secret-name resolution ---------------------------------------------------


class TestAwsSecretNames:
    def test_role_secret_is_unsuffixed_for_prod(self):
        assert preflight._aws_role_secret("prod") == "AWS_ROLE_ARN"
        assert preflight._aws_role_secret("dev") == "AWS_ROLE_ARN_DEV"
        assert preflight._aws_role_secret("proof") == "AWS_ROLE_ARN_PROOF"

    def test_state_bucket_secret_is_unsuffixed_for_prod(self):
        assert preflight._aws_state_bucket_secret("prod") == "TF_INFRA_STATE_BUCKET"
        assert preflight._aws_state_bucket_secret("dev") == "TF_INFRA_STATE_BUCKET_DEV"

    def test_tf_vars_secret_is_env_suffixed_for_every_env(self):
        assert preflight._tf_vars_secret("prod", "PORTAL") == "TF_VARS_PROD_PORTAL"
        assert preflight._tf_vars_secret("dev", "core") == "TF_VARS_DEV_CORE"

    def test_shifter_config_secret(self):
        assert preflight._shifter_config_secret("proof") == "SHIFTER_CONFIG_PROOF_RANGE"


# --- run_preflight: CI (secret) mode ------------------------------------------


class TestRunPreflightGcpCi:
    def test_all_secrets_present_passes(self):
        report = preflight.run_preflight(Cloud.GCP, Mode.CI, "gcp-dev", env=dict(GCP_CI_ENV))
        assert report.ok
        assert report.failures == []

    def test_missing_required_secret_fails(self):
        env = dict(GCP_CI_ENV)
        del env["GCP_PROJECT_ID"]
        report = preflight.run_preflight(Cloud.GCP, Mode.CI, "gcp-dev", env=env)
        assert not report.ok
        assert any("GCP_PROJECT_ID" in r.message and r.status is Status.FAIL for r in report.results)

    def test_missing_operator_creds_fail_without_optout(self):
        env = dict(GCP_CI_ENV)
        del env["GCP_BOOTSTRAP_ADMIN_PASSWORD"]
        report = preflight.run_preflight(Cloud.GCP, Mode.CI, "gcp-dev", env=env)
        assert not report.ok
        assert any("GCP_BOOTSTRAP_ADMIN_PASSWORD" in r.message and r.status is Status.FAIL for r in report.results)

    def test_operator_optout_downgrades_to_warn(self):
        env = dict(GCP_CI_ENV)
        del env["GCP_BOOTSTRAP_ADMIN_EMAIL"]
        del env["GCP_BOOTSTRAP_ADMIN_PASSWORD"]
        env[preflight.SKIP_OPERATOR_ENV] = "true"
        report = preflight.run_preflight(Cloud.GCP, Mode.CI, "gcp-dev", env=env)
        assert report.ok
        warns = [r for r in report.results if r.status is Status.WARN]
        assert any("opt-out" in r.message for r in warns)

    def test_optional_secret_missing_is_warn_not_fail(self):
        report = preflight.run_preflight(Cloud.GCP, Mode.CI, "gcp-dev", env=dict(GCP_CI_ENV))
        cidr = next(r for r in report.results if "authorized" in r.name.lower())
        assert cidr.status is Status.WARN


class TestRunPreflightAwsCi:
    def _aws_env(self, environment):
        return {
            preflight._aws_role_secret(environment): "arn:aws:iam::1:role/x",
            preflight._aws_state_bucket_secret(environment): "shifter-state",
            preflight._tf_vars_secret(environment, "CORE"): "x=1",
            preflight._tf_vars_secret(environment, "RANGE"): "x=1",
            preflight._tf_vars_secret(environment, "PORTAL"): "x=1",
            preflight._shifter_config_secret(environment): "settings: {}",
        }

    def test_all_components_present_passes(self):
        report = preflight.run_preflight(Cloud.AWS, Mode.CI, "dev", env=self._aws_env("dev"))
        assert report.ok

    def test_component_scoped_only_checks_that_component(self):
        env = {
            preflight._aws_role_secret("dev"): "arn",
            preflight._aws_state_bucket_secret("dev"): "bucket",
            preflight._tf_vars_secret("dev", "CORE"): "x=1",
        }
        report = preflight.run_preflight(Cloud.AWS, Mode.CI, "dev", component="core", env=env)
        assert report.ok

    def test_prod_uses_unsuffixed_role_and_bucket(self):
        report = preflight.run_preflight(Cloud.AWS, Mode.CI, "prod", component="core", env=self._aws_env("prod"))
        assert report.ok


# --- run_preflight: local mode ------------------------------------------------


class TestRunPreflightLocal:
    def test_missing_tool_fails(self):
        report = preflight.run_preflight(
            Cloud.AWS, Mode.LOCAL, "dev", env={}, repo_root=Path("/nonexistent"), tool_exists=lambda name: None
        )
        assert any(r.name == "tool: terraform" and r.status is Status.FAIL for r in report.results)

    def test_tools_present_pass(self, tmp_path):
        report = preflight.run_preflight(
            Cloud.AWS,
            Mode.LOCAL,
            "dev",
            env={},
            repo_root=tmp_path,
            tool_exists=lambda name: f"/usr/bin/{name}",
        )
        assert all(r.status is Status.OK for r in report.results if r.name.startswith("tool:"))

    def test_aws_overlay_missing_fails_when_component_selected(self, tmp_path):
        report = preflight.run_preflight(
            Cloud.AWS, Mode.LOCAL, "dev", component="portal", env={}, repo_root=tmp_path, tool_exists=lambda n: "/bin/x"
        )
        assert any(r.name == "portal overlay" and r.status is Status.FAIL for r in report.results)

    def test_aws_overlay_present_passes(self, tmp_path):
        overlay = tmp_path / "platform" / "terraform" / "environments" / "dev" / "portal" / "local.auto.tfvars"
        overlay.parent.mkdir(parents=True)
        overlay.write_text('domain_name = "x"\n')
        report = preflight.run_preflight(
            Cloud.AWS, Mode.LOCAL, "dev", component="portal", env={}, repo_root=tmp_path, tool_exists=lambda n: "/bin/x"
        )
        assert any(r.name == "portal overlay" and r.status is Status.OK for r in report.results)

    def test_gcp_local_reads_security_inputs(self, tmp_path):
        tf_dir = tmp_path / "platform" / "terraform" / "gcp" / "environments" / "gcp-dev"
        tf_dir.mkdir(parents=True)
        (tf_dir / "terraform.tfvars").write_text(
            'public_hostname = "gcp.example.test"\n'
            "enable_managed_tls = true\n"
            'gke_master_authorized_cidrs = ["203.0.113.10/32"]\n'
        )
        report = preflight.run_preflight(
            Cloud.GCP, Mode.LOCAL, "gcp-dev", env={}, repo_root=tmp_path, tool_exists=lambda n: "/bin/x"
        )
        assert any(r.name == "GCP control-plane inputs" and r.status is Status.OK for r in report.results)

    def test_gcp_local_flags_insecure_inputs(self, tmp_path):
        tf_dir = tmp_path / "platform" / "terraform" / "gcp" / "environments" / "gcp-dev"
        tf_dir.mkdir(parents=True)
        (tf_dir / "terraform.tfvars").write_text("enable_managed_tls = false\n")
        report = preflight.run_preflight(
            Cloud.GCP, Mode.LOCAL, "gcp-dev", env={}, repo_root=tmp_path, tool_exists=lambda n: "/bin/x"
        )
        assert not report.ok


# --- Report rendering ---------------------------------------------------------


class TestReport:
    def test_render_reports_pass_and_fail(self):
        env = dict(GCP_CI_ENV)
        del env["GCP_PROJECT_ID"]
        report = preflight.run_preflight(Cloud.GCP, Mode.CI, "gcp-dev", env=env)
        rendered = report.render()
        assert "[FAIL]" in rendered
        assert "Result: FAIL" in rendered

    def test_render_reports_clean_pass(self):
        report = preflight.run_preflight(Cloud.GCP, Mode.CI, "gcp-dev", env=dict(GCP_CI_ENV))
        assert "Result: PASS" in report.render()


# --- Gate (interactive / headless) --------------------------------------------


class TestPreflightGate:
    def _set_gcp_env(self, monkeypatch, omit=()):
        """Put a healthy GCP secret set on the real process env (the gate reads os.environ)."""
        monkeypatch.delenv(preflight.SKIP_OPERATOR_ENV, raising=False)
        for key, value in GCP_CI_ENV.items():
            if key in omit:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)

    def test_headless_pass_returns_report(self, mock_stdin_non_tty, monkeypatch):
        self._set_gcp_env(monkeypatch)
        report = preflight.preflight_gate(Cloud.GCP, Mode.CI, "gcp-dev")
        assert report.ok

    def test_headless_failure_exits(self, mock_stdin_non_tty, monkeypatch):
        self._set_gcp_env(monkeypatch, omit=("GCP_PROJECT_ID",))
        with pytest.raises(SystemExit) as exc:
            preflight.preflight_gate(Cloud.GCP, Mode.CI, "gcp-dev", headless=True)
        assert exc.value.code == 1

    def test_interactive_confirms_manual_prereqs(self, mock_stdin_tty):
        # AWS local + component=None runs only the tool checks; a present PATH plus a
        # "yes" to the manual-prerequisite prompt passes the gate.
        with (
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("builtins.input", return_value="y"),
        ):
            report = preflight.preflight_gate(Cloud.AWS, Mode.LOCAL, "dev", headless=False)
        assert report.ok

    def test_interactive_abort_when_manual_prereqs_declined(self, mock_stdin_tty):
        with (
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("builtins.input", return_value="n"),
            pytest.raises(SystemExit),
        ):
            preflight.preflight_gate(Cloud.AWS, Mode.LOCAL, "dev", headless=False)


# --- Facade wiring ------------------------------------------------------------


class TestFacade:
    def test_deploy_reexports_run_preflight(self):
        assert callable(deploy.run_preflight)
        assert callable(deploy.preflight_gate)


# --- Parity with docs/dev/deploy-secrets.md -----------------------------------


def _required_secrets_in_section(text: str, heading: str) -> set[str]:
    """Extract secret names marked required=yes in a markdown table under a heading."""
    section = _slice_section(text, heading)
    names: set[str] = set()
    name_idx = required_idx = None
    for row in section.splitlines():
        if not row.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        header_cells = [c.lower() for c in cells]
        if "required" in header_cells and ("name" in header_cells or "secret" in header_cells):
            required_idx = header_cells.index("required")
            name_idx = header_cells.index("name") if "name" in header_cells else header_cells.index("secret")
            continue
        if name_idx is None or set("".join(cells)) <= set("-: "):
            continue
        if required_idx < len(cells) and cells[required_idx].lower() in {"yes", "required", "y"}:
            names.add(cells[name_idx].strip("`").strip())
    return names


def _slice_section(text: str, heading: str) -> str:
    """Return the text from a heading line to the next same-or-higher heading."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if heading in line and line.startswith("#"))
    level = len(re.match(r"#+", lines[start]).group())
    end = len(lines)
    for i in range(start + 1, len(lines)):
        match = re.match(r"#+", lines[i])
        if match and len(match.group()) <= level:
            end = i
            break
    return "\n".join(lines[start:end])


def _spec_required(cloud: Cloud, environment: str) -> set[str]:
    return {c.env_var for c in preflight.secret_checks(cloud, environment) if c.required}


class TestDocParity:
    def test_gcp_spec_matches_deploy_secrets_doc(self):
        text = DEPLOY_SECRETS_DOC.read_text()
        doc_required = _required_secrets_in_section(text, "GCP (gcp-dev)")
        assert _spec_required(Cloud.GCP, "gcp-dev") == doc_required

    def test_aws_spec_matches_deploy_secrets_doc(self):
        text = DEPLOY_SECRETS_DOC.read_text()
        doc_required = _required_secrets_in_section(text, "stand up an AWS environment")
        assert _spec_required(Cloud.AWS, "dev") == doc_required
