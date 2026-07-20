"""Tests for the backend-aware ``doctor`` validation UX (installation.doctor, #727)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from installation.contract import (
    BackendBundle,
    BackendMaturity,
    CommandSpec,
    GeneratedOutput,
    HealthCheck,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    OwnedFiles,
    RequiredSecret,
    RequiredTool,
    ValidationCheck,
)
from installation.doctor import (
    CheckScope,
    CheckStatus,
    CheckTier,
    CommandOutcome,
    DoctorCheckResult,
    DoctorProbes,
    DoctorReport,
    HealthOutcome,
    _default_command_runner,
    _default_health_probe,
    _default_tool_probe,
    _is_global_address,
    check_backend,
    run_doctor,
)

# --- Fakes for the injected execution seams (no real subprocess / network) -------------


def all_tools_present(_name: str) -> bool:
    return True


def no_tools_present(_name: str) -> bool:
    return False


def present_tools(*names: str):
    wanted = frozenset(names)
    return lambda name: name in wanted


class RecordingRunner:
    """A fake command runner that records the argv it was handed and returns a fixed outcome."""

    def __init__(self, outcome: CommandOutcome | None = None) -> None:
        self.outcome = outcome or CommandOutcome(returncode=0)
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, argv: Sequence[str], cwd: Path) -> CommandOutcome:
        self.calls.append((list(argv), cwd))
        return self.outcome


class RecordingProbe:
    def __init__(self, outcome: HealthOutcome | None = None) -> None:
        self.outcome = outcome or HealthOutcome(status_code=200, reachable=True)
        self.calls: list[tuple[str, int]] = []

    def __call__(self, target: str, timeout: int) -> HealthOutcome:
        self.calls.append((target, timeout))
        return self.outcome


def _bundle(
    *,
    required_tools: tuple[RequiredTool, ...] = (RequiredTool(name="uv", purpose="run tooling"),),
    required_secrets: tuple[RequiredSecret, ...] = (),
    validation_checks: tuple[ValidationCheck, ...] = (),
    health_checks: tuple[HealthCheck, ...] = (),
    generated_outputs: tuple[GeneratedOutput, ...] = (),
    owned_files: OwnedFiles | None = None,
) -> BackendBundle:
    return BackendBundle(
        contract_version=1,
        name="aws",
        title="Test backend",
        maturity=BackendMaturity.STABLE,
        description="A backend for testing the doctor executor.",
        supported_profiles=frozenset({"prod"}),
        required_tools=required_tools,
        required_secrets=required_secrets,
        validation_checks=validation_checks,
        health_checks=health_checks,
        generated_outputs=generated_outputs,
        owned_files=owned_files if owned_files is not None else OwnedFiles(),
    )


def _results_by_name(results):
    return {r.name: r for r in results}


def _probes(tool_probe=all_tools_present, command_runner=None, health_probe=None) -> DoctorProbes:
    return DoctorProbes(
        tool_probe=tool_probe,
        command_runner=command_runner or RecordingRunner(),
        health_probe=health_probe or RecordingProbe(),
    )


def _check(
    bundle: BackendBundle,
    *,
    scope: CheckScope = CheckScope.LOCAL,
    repo_root: Path,
    secrets=None,
    tool_probe=all_tools_present,
    command_runner=None,
    health_probe=None,
):
    return check_backend(
        bundle,
        domain="range.example.com",
        secrets=secrets or {},
        scope=scope,
        repo_root=repo_root,
        probes=_probes(tool_probe=tool_probe, command_runner=command_runner, health_probe=health_probe),
    )


# --- run_doctor config gate -----------------------------------------------------------


class TestConfigGate:
    def test_invalid_config_fails_and_reports_issues(self, write_config, tmp_path: Path) -> None:
        path = write_config({"backend": "aws", "deployment": {"name": "x", "domain": "not a domain"}})
        report = run_doctor(path, repo_root=tmp_path, probes=_probes())
        assert not report.ok
        assert report.exit_code() == 1
        assert any(r.status is CheckStatus.FAIL for r in report.results)

    def test_missing_config_fails_cleanly(self, tmp_path: Path) -> None:
        report = run_doctor(tmp_path / "nope.yaml", repo_root=tmp_path)
        assert not report.ok
        assert any(r.name == "root-config" and r.status is CheckStatus.FAIL for r in report.results)

    def test_valid_config_passes_the_config_gate(self, write_config, aws_config, tmp_path: Path) -> None:
        path = write_config(aws_config)
        report = run_doctor(path, repo_root=tmp_path, probes=_probes())
        root = _results_by_name(report.results)["root-config"]
        assert root.status is CheckStatus.PASS
        assert report.backend == "aws"
        assert report.profile == "prod"

    def test_report_never_echoes_config_values(self, write_config, tmp_path: Path) -> None:
        # A raw-looking secret must not be reflected back through the doctor report.
        secret = "AKIAIOSFODNN7EXAMPLE-super-secret-value"
        path = write_config(
            {
                "backend": "aws",
                "deployment": {"name": "x", "domain": "ex.example.com"},
                "secrets": {"django_secret_key": secret, "db_password": "prompt"},
                "settings": {"region": "BADREGION"},
            }
        )
        report = run_doctor(path, repo_root=tmp_path, probes=_probes())
        rendered = "\n".join(r.summary + (r.remediation or "") for r in report.results)
        assert secret not in rendered
        assert "BADREGION" not in rendered


# --- required tools -------------------------------------------------------------------


class TestRequiredTools:
    def test_present_tool_passes(self, tmp_path: Path) -> None:
        bundle = _bundle(required_tools=(RequiredTool(name="terraform", purpose="provision infra"),))
        results = _check(bundle, repo_root=tmp_path, tool_probe=present_tools("terraform"))
        tool = _results_by_name(results)["tool:terraform"]
        assert tool.status is CheckStatus.PASS
        assert tool.tier is CheckTier.LOCAL

    def test_missing_tool_is_a_blocking_failure_with_remediation(self, tmp_path: Path) -> None:
        bundle = _bundle(required_tools=(RequiredTool(name="terraform", purpose="provision infra"),))
        results = _check(bundle, repo_root=tmp_path, tool_probe=no_tools_present)
        tool = _results_by_name(results)["tool:terraform"]
        assert tool.status is CheckStatus.FAIL
        assert tool.blocking
        assert "terraform" in (tool.remediation or "")
        assert "provision infra" in (tool.remediation or "")


# --- secret references ----------------------------------------------------------------


class TestSecretReferences:
    def test_valid_references_pass(self, tmp_path: Path) -> None:
        bundle = _bundle(
            required_secrets=(
                RequiredSecret(logical_name="django_secret_key", purpose="app key", reference_grammar="a name"),
            )
        )
        results = _check(bundle, repo_root=tmp_path, secrets={"django_secret_key": "prompt"})
        assert _results_by_name(results)["secret-references"].status is CheckStatus.PASS

    def test_missing_reference_is_a_blocking_failure(self, tmp_path: Path) -> None:
        bundle = _bundle(
            required_secrets=(
                RequiredSecret(logical_name="django_secret_key", purpose="app key", reference_grammar="a name"),
            )
        )
        results = _check(bundle, repo_root=tmp_path, secrets={})
        secret = _results_by_name(results)["secret-references"]
        assert secret.status is CheckStatus.FAIL
        assert secret.blocking


# --- generated env classification -----------------------------------------------------


class TestGeneratedEnv:
    def test_reports_generated_outputs_as_info(self, tmp_path: Path) -> None:
        outputs = (
            GeneratedOutput(
                name="CLOUD_PROVIDER",
                kind=OutputKind.RUNTIME_ENV,
                owner="renderer",
                source="renderer",
                destination=OutputDestination.RUNTIME_ENV,
                sensitivity=OutputSensitivity.PUBLIC,
                description="public value",
            ),
            GeneratedOutput(
                name="APP_SECRET_ID",
                kind=OutputKind.RUNTIME_ENV,
                owner="renderer",
                source="renderer",
                destination=OutputDestination.RUNTIME_ENV,
                sensitivity=OutputSensitivity.SECRET_REFERENCE,
                description="secret reference",
            ),
        )
        results = _check(_bundle(generated_outputs=outputs), repo_root=tmp_path)
        gen = _results_by_name(results)["generated-env"]
        assert gen.status is CheckStatus.INFO
        assert gen.tier is CheckTier.LOCAL


# --- owned path existence -------------------------------------------------------------


class TestOwnedPaths:
    def test_missing_paths_warn_but_do_not_block(self, tmp_path: Path) -> None:
        bundle = _bundle(owned_files=OwnedFiles(infrastructure=("platform/absent",)))
        results = _check(bundle, repo_root=tmp_path)
        warns = [r for r in results if r.name.startswith("owned-path") and r.status is CheckStatus.WARN]
        assert warns
        assert all(not r.blocking for r in warns)

    def test_present_paths_pass(self, tmp_path: Path) -> None:
        (tmp_path / "platform").mkdir()
        (tmp_path / "platform" / "here").mkdir()
        bundle = _bundle(owned_files=OwnedFiles(infrastructure=("platform/here",)))
        results = _check(bundle, repo_root=tmp_path)
        owned = _results_by_name(results)["owned-paths"]
        assert owned.status is CheckStatus.PASS


# --- validation checks (executed, non-mutating) ---------------------------------------


class TestValidationChecks:
    def _bundle_with_check(self) -> BackendBundle:
        return _bundle(
            required_tools=(RequiredTool(name="terraform", purpose="provision"),),
            validation_checks=(
                ValidationCheck(
                    name="terraform-fmt",
                    command=CommandSpec(
                        argv=("terraform", "fmt", "-check", "platform/terraform"),
                        description="check fmt",
                    ),
                    description="fail on unformatted terraform",
                ),
            ),
        )

    def test_passing_check_runs_via_argv_and_passes(self, tmp_path: Path) -> None:
        runner = RecordingRunner(CommandOutcome(returncode=0))
        results = _check(
            self._bundle_with_check(),
            repo_root=tmp_path,
            tool_probe=present_tools("terraform"),
            command_runner=runner,
        )
        check = _results_by_name(results)["check:terraform-fmt"]
        assert check.status is CheckStatus.PASS
        # The runner is handed an argv array (never a shell string) and the repo root as cwd.
        assert runner.calls == [(["terraform", "fmt", "-check", "platform/terraform"], tmp_path)]

    def test_failing_blocking_check_fails_without_leaking_output(self, tmp_path: Path) -> None:
        runner = RecordingRunner(CommandOutcome(returncode=3))
        results = _check(
            self._bundle_with_check(),
            repo_root=tmp_path,
            tool_probe=present_tools("terraform"),
            command_runner=runner,
        )
        check = _results_by_name(results)["check:terraform-fmt"]
        assert check.status is CheckStatus.FAIL
        assert check.blocking

    def test_check_skipped_when_tool_absent(self, tmp_path: Path) -> None:
        runner = RecordingRunner(CommandOutcome(returncode=0))
        results = _check(
            self._bundle_with_check(),
            repo_root=tmp_path,
            tool_probe=no_tools_present,
            command_runner=runner,
        )
        check = _results_by_name(results)["check:terraform-fmt"]
        assert check.status is CheckStatus.SKIP
        assert runner.calls == []  # never executed a missing tool

    def test_timeout_is_a_failure(self, tmp_path: Path) -> None:
        runner = RecordingRunner(CommandOutcome(returncode=None, timed_out=True))
        results = _check(
            self._bundle_with_check(),
            repo_root=tmp_path,
            tool_probe=present_tools("terraform"),
            command_runner=runner,
        )
        assert _results_by_name(results)["check:terraform-fmt"].status is CheckStatus.FAIL

    def _bundle_with_nonblocking_check(self) -> BackendBundle:
        return _bundle(
            required_tools=(RequiredTool(name="terraform", purpose="provision"),),
            validation_checks=(
                ValidationCheck(
                    name="terraform-fmt",
                    command=CommandSpec(argv=("terraform", "fmt", "-check"), description="check fmt"),
                    description="advisory fmt check",
                    blocking=False,
                ),
            ),
        )

    @pytest.mark.parametrize(
        "outcome",
        [
            CommandOutcome(returncode=2),
            CommandOutcome(returncode=None, timed_out=True),
            CommandOutcome(returncode=None, error="boom"),
        ],
    )
    def test_nonblocking_failure_warns_not_fails(self, outcome: CommandOutcome, tmp_path: Path) -> None:
        # Finding #2: a non-blocking check that fails/times-out/errors is a WARN, never a FAIL.
        results = _check(
            self._bundle_with_nonblocking_check(),
            repo_root=tmp_path,
            tool_probe=present_tools("terraform"),
            command_runner=RecordingRunner(outcome),
        )
        check = _results_by_name(results)["check:terraform-fmt"]
        assert check.status is CheckStatus.WARN
        assert not check.blocking


# --- health checks (cloud-read tier, opt-in) ------------------------------------------


class TestHealthChecks:
    def _bundle_with_health(self) -> BackendBundle:
        return _bundle(
            health_checks=(
                HealthCheck(
                    name="portal-health",
                    target="https://<deployment.domain>/health/",
                    requires_credentials=False,
                    timeout_seconds=10,
                    description="portal health",
                ),
            )
        )

    def test_local_scope_does_not_probe_but_notes_the_tier(self, tmp_path: Path) -> None:
        probe = RecordingProbe()
        results = _check(self._bundle_with_health(), repo_root=tmp_path, scope=CheckScope.LOCAL, health_probe=probe)
        assert probe.calls == []
        health = _results_by_name(results)["health:portal-health"]
        assert health.tier is CheckTier.CLOUD_READ
        assert health.status is CheckStatus.SKIP

    def test_cloud_scope_probes_with_substituted_domain(self, tmp_path: Path) -> None:
        probe = RecordingProbe(HealthOutcome(status_code=200, reachable=True))
        results = _check(self._bundle_with_health(), repo_root=tmp_path, scope=CheckScope.CLOUD, health_probe=probe)
        assert probe.calls == [("https://range.example.com/health/", 10)]
        assert _results_by_name(results)["health:portal-health"].status is CheckStatus.PASS

    def test_unreachable_endpoint_warns_and_does_not_block(self, tmp_path: Path) -> None:
        probe = RecordingProbe(HealthOutcome(status_code=None, reachable=False, error="connection refused"))
        results = _check(self._bundle_with_health(), repo_root=tmp_path, scope=CheckScope.CLOUD, health_probe=probe)
        health = _results_by_name(results)["health:portal-health"]
        assert health.status is CheckStatus.WARN
        assert not health.blocking


# --- tier labelling + mutating note ---------------------------------------------------


class TestTierLabelling:
    def test_every_result_carries_a_tier(self, tmp_path: Path) -> None:
        results = _check(_bundle(), repo_root=tmp_path)
        assert all(isinstance(r.tier, CheckTier) for r in results)

    def test_deployment_mutating_category_is_reported(self, tmp_path: Path) -> None:
        results = _check(_bundle(), repo_root=tmp_path)
        mutating = _results_by_name(results)["deployment-mutating"]
        assert mutating.tier is CheckTier.MUTATING
        assert mutating.status is CheckStatus.INFO


# --- end-to-end against the real bundles ----------------------------------------------


# A complete, loader-valid GCP config (the shared gcp_config fixture omits the settings the
# GCP backend now requires, so it is fine for schema tests but not for load_root_config).
_LOADABLE_GCP_CONFIG = {
    "backend": "gcp",
    "deployment": {"name": "shifter", "domain": "shifter.example.com"},
    "secrets": {"django_secret_key": "prompt"},
    "settings": {"project_id": "acme-shifter", "region": "us-central1"},
}


class TestRealBundles:
    @pytest.mark.parametrize("config", [pytest.param("aws", id="aws"), pytest.param("gcp", id="gcp")])
    def test_run_doctor_produces_a_tiered_report(
        self, config: str, request: pytest.FixtureRequest, write_config, tmp_path: Path
    ) -> None:
        config = request.getfixturevalue("aws_config") if config == "aws" else _LOADABLE_GCP_CONFIG
        path = write_config(config)
        report = run_doctor(
            path,
            repo_root=tmp_path,
            scope=CheckScope.LOCAL,
            probes=_probes(command_runner=RecordingRunner(CommandOutcome(returncode=0))),
        )
        tiers = {r.tier for r in report.results}
        assert CheckTier.LOCAL in tiers
        assert CheckTier.MUTATING in tiers
        assert _results_by_name(report.results)["root-config"].status is CheckStatus.PASS

    def test_json_report_is_serializable(self, write_config, aws_config, tmp_path: Path) -> None:
        import json

        path = write_config(aws_config)
        report = run_doctor(path, repo_root=tmp_path, probes=_probes())
        payload = json.dumps(report.to_dict())
        assert '"backend": "aws"' in payload

    def test_unregistered_bundle_fails_the_config_gate(self, write_config, aws_config, tmp_path, monkeypatch) -> None:
        # Defensive branch: a validated backend whose bundle unexpectedly does not resolve.
        monkeypatch.setattr("installation.doctor.get_backend_bundle", lambda _name: None)
        path = write_config(aws_config)
        report = run_doctor(path, repo_root=tmp_path, probes=_probes())
        assert not report.ok
        assert any("no backend bundle" in r.summary for r in report.results)


class TestReportReadiness:
    """Finding #2: report.ok honors the blocking flag, not merely the FAIL status."""

    def _report(self, *results: DoctorCheckResult) -> DoctorReport:
        return DoctorReport(backend="aws", profile="prod", results=list(results))

    def test_blocking_failure_makes_report_not_ok(self) -> None:
        report = self._report(
            DoctorCheckResult("a", CheckTier.LOCAL, CheckStatus.PASS, "ok"),
            DoctorCheckResult("b", CheckTier.LOCAL, CheckStatus.FAIL, "bad", blocking=True),
        )
        assert report.ok is False
        assert report.exit_code() == 1

    def test_nonblocking_warn_keeps_report_ok(self) -> None:
        report = self._report(
            DoctorCheckResult("a", CheckTier.LOCAL, CheckStatus.PASS, "ok"),
            DoctorCheckResult("b", CheckTier.LOCAL, CheckStatus.WARN, "soft", blocking=False),
        )
        assert report.ok is True
        assert report.exit_code() == 0

    def test_nonblocking_fail_does_not_fail_the_run(self) -> None:
        # Defensive: even a FAIL marked non-blocking must not flip readiness.
        report = self._report(DoctorCheckResult("b", CheckTier.LOCAL, CheckStatus.FAIL, "soft", blocking=False))
        assert report.ok is True


class TestDefaultSeams:
    """The real (uninjected) execution seams — exercised against the local machine only."""

    def test_tool_probe_finds_the_interpreter_but_not_a_bogus_tool(self) -> None:
        assert _default_tool_probe("python3") is True
        assert _default_tool_probe("shifter-definitely-not-a-real-tool") is False

    def test_command_runner_passes_through_exit_code(self, tmp_path: Path) -> None:
        assert _default_command_runner(["python3", "-c", "raise SystemExit(0)"], tmp_path).returncode == 0
        assert _default_command_runner(["python3", "-c", "raise SystemExit(3)"], tmp_path).returncode == 3

    def test_command_runner_reports_missing_executable_without_raising(self, tmp_path: Path) -> None:
        outcome = _default_command_runner(["shifter-not-an-executable-xyz"], tmp_path)
        assert outcome.returncode is None
        assert outcome.error is not None

    def test_is_global_address_classifies_literals(self) -> None:
        assert _is_global_address("8.8.8.8") is True
        assert _is_global_address("127.0.0.1") is False  # loopback
        assert _is_global_address("10.0.0.1") is False  # private
        assert _is_global_address("not-an-ip") is False  # unparseable

    def test_health_probe_rejects_non_http_scheme(self) -> None:
        outcome = _default_health_probe("ftp://example.invalid/health/", 1)
        assert outcome.reachable is False
        assert "scheme" in (outcome.error or "")

    def test_health_probe_rejects_userinfo(self) -> None:
        outcome = _default_health_probe("https://user:pass@example.com/health/", 1)
        assert outcome.reachable is False
        assert "credentials" in (outcome.error or "")

    @pytest.mark.parametrize(
        "target",
        [
            "http://127.0.0.1/health/",  # loopback
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
            "http://10.0.0.5/health/",  # private
            "http://[::1]/health/",  # IPv6 loopback
        ],
    )
    def test_health_probe_refuses_non_public_addresses(self, target: str) -> None:
        # SSRF guard: a config-controlled domain must not reach loopback/private/metadata.
        outcome = _default_health_probe(target, 1)
        assert outcome.reachable is False
        assert "non-public" in (outcome.error or "")

    def test_no_redirect_handler_blocks_redirects(self) -> None:
        from installation.doctor import _NoRedirectHandler

        # redirect_request returns None so urllib raises rather than following the hop.
        assert _NoRedirectHandler().redirect_request(None, None, 302, "Found", {}, "http://internal/") is None
