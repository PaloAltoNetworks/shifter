"""Backend-aware ``doctor``: validate a selected backend before infrastructure is applied (#727).

``doctor`` reads the selected backend from ``shifter.yaml`` (via the one parser,
:func:`installation.loader.load_root_config`), resolves the backend's
:class:`~installation.contract.BackendBundle`, and runs the checks the bundle *already
declares* — required tools, required secret references, generated outputs, owned repo
paths, validation checks, and health checks. It adds no backend-specific check list of its
own: a new backend gets doctor coverage by declaring bundle metadata, not by editing a
central ``if backend == ...`` here (preflight #727).

Every check is labelled by side-effect tier so the operator knows what doctor did and what
it deliberately did not do:

* **local-only** (default): parse/validate config, look up tools on PATH, classify
  generated outputs, check owned repo paths exist, and run the bundle's credential-free,
  non-mutating validation checks (``terraform fmt -check``, ``helm template``,
  ``kubectl kustomize``, ``kube-linter lint``, root-config validate).
* **cloud-read-only** (opt-in, ``--checks cloud``): read-only health probes of the
  deployment endpoint. Never fetches a secret payload, never mutates.
* **deployment-mutating**: never run by doctor — only reported, so the operator knows the
  step is required and stays owned by the deploy workflow.

Reports are sanitized: they name the backend, profile, check names, missing tools, and
repo-relative paths, never config bodies, secret references or values, or captured command
output. The data model lives in :mod:`installation._doctor_model` and the real execution
seams in :mod:`installation._doctor_seams`; both are re-exported here so callers import a
single ``installation.doctor`` surface. Constrained by ADR-011 / ADR-035.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ._doctor_model import (
    DOMAIN_PLACEHOLDER,
    HEALTHY_MAX,
    HEALTHY_MIN,
    CheckScope,
    CheckStatus,
    CheckTier,
    CommandOutcome,
    DoctorCheckResult,
    DoctorReport,
    HealthOutcome,
)
from ._doctor_seams import (
    COMMAND_TIMEOUT_SECONDS,
    DEFAULT_PROBES,
    CommandRunner,
    DoctorProbes,
    HealthProbe,
    ToolProbe,
    _default_command_runner,
    _default_health_probe,
    _default_tool_probe,
    _is_global_address,
    _NoRedirectHandler,
    _probe,
    _resolves_to_public_only,
    _validate_health_target,
)
from .contract import BackendBundle
from .errors import ConfigIssue, InstallationConfigError
from .loader import load_root_config
from .registry import get_backend_bundle

__all__ = [
    "COMMAND_TIMEOUT_SECONDS",
    "DEFAULT_PROBES",
    "DOMAIN_PLACEHOLDER",
    "HEALTHY_MAX",
    "HEALTHY_MIN",
    "CheckScope",
    "CheckStatus",
    "CheckTier",
    "CommandOutcome",
    "CommandRunner",
    "DoctorCheckResult",
    "DoctorProbes",
    "DoctorReport",
    "HealthOutcome",
    "HealthProbe",
    "ToolProbe",
    "_NoRedirectHandler",
    "_default_command_runner",
    "_default_health_probe",
    "_default_tool_probe",
    "_is_global_address",
    "_probe",
    "_resolves_to_public_only",
    "_validate_health_target",
    "check_backend",
    "run_doctor",
]


def _tool_results(bundle: BackendBundle, tool_probe: ToolProbe) -> list[DoctorCheckResult]:
    """Check that each of the backend's required tools resolves on PATH (blocking on miss)."""
    results: list[DoctorCheckResult] = []
    for tool in bundle.required_tools:
        if tool_probe(tool.name):
            results.append(
                DoctorCheckResult(f"tool:{tool.name}", CheckTier.LOCAL, CheckStatus.PASS, f"{tool.name} found on PATH")
            )
        else:
            results.append(
                DoctorCheckResult(
                    f"tool:{tool.name}",
                    CheckTier.LOCAL,
                    CheckStatus.FAIL,
                    f"{tool.name} not found on PATH",
                    blocking=True,
                    remediation=f"install {tool.name} — {tool.purpose}",
                )
            )
    return results


def _secret_results(bundle: BackendBundle, secrets: Mapping[str, Any]) -> DoctorCheckResult:
    """Check that the config's secret references satisfy the backend's declared grammar."""
    issues = bundle.secret_reference_issues(secrets)
    if issues:
        summary = f"{len(issues)} secret-reference problem(s) for backend {bundle.name!r}: " + "; ".join(
            issue.render() for issue in issues
        )
        return DoctorCheckResult(
            "secret-references",
            CheckTier.LOCAL,
            CheckStatus.FAIL,
            summary,
            blocking=True,
            remediation="fix the secrets: block in shifter.yaml (references only — never secret values)",
        )
    count = len(bundle.required_secrets)
    return DoctorCheckResult(
        "secret-references",
        CheckTier.LOCAL,
        CheckStatus.PASS,
        f"{count} secret reference(s) present for backend {bundle.name!r}; "
        "values resolved from the secret store at deploy time",
    )


def _generated_env_result(bundle: BackendBundle) -> DoctorCheckResult:
    """Classify the runtime-env outputs the backend generates (informational, local-only)."""
    outputs = bundle.generated_outputs
    public = sum(1 for output in outputs if output.sensitivity.value == "public")
    secret_ref = sum(1 for output in outputs if output.sensitivity.value == "secret-reference")
    summary = (
        f"backend {bundle.name!r} generates {len(outputs)} runtime env output(s): "
        f"{public} public, {secret_ref} secret-reference (fetched from the secret store at startup)"
    )
    return DoctorCheckResult("generated-env", CheckTier.LOCAL, CheckStatus.INFO, summary)


def _declared_paths(bundle: BackendBundle) -> list[str]:
    """The de-duplicated repo-relative paths the backend bundle declares it owns."""
    owned = bundle.owned_files
    groups = (
        owned.infrastructure,
        owned.kubernetes,
        owned.scripts,
        owned.workflows,
        owned.examples,
        owned.docs,
        bundle.docs,
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for path in group:
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    return ordered


def _owned_path_results(bundle: BackendBundle, repo_root: Path) -> list[DoctorCheckResult]:
    """Check that the backend's declared owned paths exist (non-blocking WARN on miss)."""
    declared = _declared_paths(bundle)
    missing = [path for path in declared if not (repo_root / path).exists()]
    if not missing:
        return [
            DoctorCheckResult(
                "owned-paths",
                CheckTier.LOCAL,
                CheckStatus.PASS,
                f"all {len(declared)} backend-owned path(s) present",
            )
        ]
    # A missing declared path is a bundle/repo-integrity signal, not an operator-config error,
    # so it warns without blocking the run.
    return [
        DoctorCheckResult(
            f"owned-path:{path}",
            CheckTier.LOCAL,
            CheckStatus.WARN,
            f"path {path!r} declared by backend {bundle.name!r} not found in the repository",
        )
        for path in missing
    ]


def _validation_check_results(
    bundle: BackendBundle, repo_root: Path, tool_probe: ToolProbe, command_runner: CommandRunner
) -> list[DoctorCheckResult]:
    """Run the backend's declared (credential-free, non-mutating) validation checks."""
    results: list[DoctorCheckResult] = []
    for check in bundle.validation_checks:
        name = f"check:{check.name}"
        executable = check.command.argv[0]
        if not tool_probe(executable):
            results.append(
                DoctorCheckResult(
                    name,
                    CheckTier.LOCAL,
                    CheckStatus.SKIP,
                    f"skipped — required tool {executable!r} not installed",
                )
            )
            continue
        outcome = command_runner(check.command.argv, repo_root)
        results.append(_validation_outcome_result(name, check.description, check.blocking, check.command.argv, outcome))
    return results


def _validation_outcome_result(
    name: str, description: str, blocking: bool, argv: Sequence[str], outcome: CommandOutcome
) -> DoctorCheckResult:
    """Turn one command outcome into a check result (blocking failures FAIL, others WARN)."""
    if outcome.returncode == 0:
        return DoctorCheckResult(name, CheckTier.LOCAL, CheckStatus.PASS, description)
    # Every non-success outcome (timeout, run error, or non-zero exit) fails a *blocking*
    # check and only warns a non-blocking one, so a FAIL result always implies a blocking
    # failure and the readiness contract (ok == no blocking failure) holds.
    if outcome.timed_out:
        detail = f"timed out after {COMMAND_TIMEOUT_SECONDS}s"
    elif outcome.error is not None:
        detail = "could not run"
    else:
        detail = f"exited {outcome.returncode}"
    status = CheckStatus.FAIL if blocking else CheckStatus.WARN
    return DoctorCheckResult(
        name,
        CheckTier.LOCAL,
        status,
        f"{description} — {detail}",
        blocking=blocking,
        remediation=f"run `{' '.join(argv)}` from the repo root for details",
    )


def _health_results(
    bundle: BackendBundle, *, domain: str, scope: CheckScope, health_probe: HealthProbe
) -> list[DoctorCheckResult]:
    """Run the backend's read-only health probes (cloud-read tier; skipped unless opted in)."""
    run_cloud = scope in (CheckScope.CLOUD, CheckScope.ALL)
    results: list[DoctorCheckResult] = []
    for check in bundle.health_checks:
        name = f"health:{check.name}"
        if not run_cloud:
            results.append(
                DoctorCheckResult(
                    name,
                    CheckTier.CLOUD_READ,
                    CheckStatus.SKIP,
                    f"{check.description} — cloud-read-only; re-run with --checks cloud to probe it",
                )
            )
            continue
        target = check.target.replace(DOMAIN_PLACEHOLDER, domain)
        outcome = health_probe(target, check.timeout_seconds)
        results.append(_health_outcome_result(name, check.description, target, outcome))
    return results


def _health_outcome_result(name: str, description: str, target: str, outcome: HealthOutcome) -> DoctorCheckResult:
    """Turn one health-probe outcome into a (non-blocking) cloud-read check result."""
    if outcome.reachable and outcome.status_code is not None and HEALTHY_MIN <= outcome.status_code <= HEALTHY_MAX:
        return DoctorCheckResult(
            name, CheckTier.CLOUD_READ, CheckStatus.PASS, f"{description} — {target} responded {outcome.status_code}"
        )
    if outcome.reachable:
        return DoctorCheckResult(
            name,
            CheckTier.CLOUD_READ,
            CheckStatus.WARN,
            f"{description} — {target} responded HTTP {outcome.status_code}",
        )
    return DoctorCheckResult(
        name,
        CheckTier.CLOUD_READ,
        CheckStatus.WARN,
        f"{description} — {target} unreachable ({outcome.error or 'no response'}); expected before deploy",
    )


def _mutating_note() -> DoctorCheckResult:
    """The informational note that doctor never runs deployment-mutating steps."""
    return DoctorCheckResult(
        "deployment-mutating",
        CheckTier.MUTATING,
        CheckStatus.INFO,
        "doctor runs no deployment-mutating steps (terraform apply/destroy, provider or GitHub secret writes, "
        "helm/kubectl apply, image promotion); run those through the deploy workflow after doctor passes",
    )


def check_backend(
    bundle: BackendBundle,
    *,
    domain: str,
    secrets: Mapping[str, Any],
    scope: CheckScope,
    repo_root: Path,
    probes: DoctorProbes = DEFAULT_PROBES,
) -> list[DoctorCheckResult]:
    """Run every declared check for ``bundle``, returning tier-labelled results.

    ``domain`` fills the health-check target's ``<deployment.domain>`` placeholder; ``secrets``
    is the root config's reference mapping (checked for presence/grammar, never resolved to a
    value). ``probes`` bundles the execution seams (tool lookup, command runner, health probe),
    defaulting to the real implementations and injected as fakes in tests.
    """
    results: list[DoctorCheckResult] = []
    results.extend(_tool_results(bundle, probes.tool_probe))
    results.append(_secret_results(bundle, secrets))
    results.append(_generated_env_result(bundle))
    results.extend(_owned_path_results(bundle, repo_root))
    results.extend(_validation_check_results(bundle, repo_root, probes.tool_probe, probes.command_runner))
    results.extend(_health_results(bundle, domain=domain, scope=scope, health_probe=probes.health_probe))
    results.append(_mutating_note())
    return results


def _config_failure_report(issues: Sequence[ConfigIssue]) -> DoctorReport:
    """Build a report of blocking ``root-config`` failures from a config-load error."""
    if not issues:
        results = [
            DoctorCheckResult(
                "root-config", CheckTier.LOCAL, CheckStatus.FAIL, "invalid root installation config", blocking=True
            )
        ]
    else:
        results = [
            DoctorCheckResult("root-config", CheckTier.LOCAL, CheckStatus.FAIL, issue.render(), blocking=True)
            for issue in issues
        ]
    return DoctorReport(backend=None, profile=None, results=results)


def run_doctor(
    config_path: str | Path,
    *,
    scope: CheckScope = CheckScope.LOCAL,
    repo_root: str | Path = Path("."),
    probes: DoctorProbes = DEFAULT_PROBES,
) -> DoctorReport:
    """Validate the backend selected by ``config_path`` and return a tier-labelled report.

    The config is parsed by the single loader (:func:`load_root_config`); an invalid config
    is reported as blocking ``root-config`` failures and no backend checks run (there is no
    validated backend to check). A valid config resolves its bundle and runs every declared
    check via :func:`check_backend`.
    """
    root = Path(repo_root)
    try:
        config = load_root_config(config_path)
    except InstallationConfigError as exc:
        return _config_failure_report(exc.issues)

    bundle = get_backend_bundle(config.backend)
    if bundle is None:
        return DoctorReport(
            backend=config.backend,
            profile=config.deployment.profile,
            results=[
                DoctorCheckResult(
                    "root-config",
                    CheckTier.LOCAL,
                    CheckStatus.FAIL,
                    f"no backend bundle registered for {config.backend!r}",
                    blocking=True,
                )
            ],
        )

    results = [
        DoctorCheckResult(
            "root-config",
            CheckTier.LOCAL,
            CheckStatus.PASS,
            f"root config valid: backend {config.backend!r}, profile {config.deployment.profile!r}",
        )
    ]
    results.extend(
        check_backend(
            bundle,
            domain=config.deployment.domain,
            secrets=config.secrets,
            scope=scope,
            repo_root=root,
            probes=probes,
        )
    )
    return DoctorReport(backend=config.backend, profile=config.deployment.profile, results=results)
