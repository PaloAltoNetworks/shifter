"""``shifter-config`` — inspect, validate, and render Shifter installation config.

``validate`` checks the shape of ``shifter.yaml`` — the backend selector, deployment
identity, secret references, and backend-specific ``settings`` mapping — so CI, deploy
scripts, and operators catch malformed root config before Terraform, Helm, Django,
workers, or deployment scripts run. ``runtime-inventory`` checks the checked-in runtime
env surfaces by file path and env-key name only. The *contents* of ``settings`` (and
which settings a backend requires) are validated by the selected backend bundle's
contract (#1113). This command deliberately stays small: parse paths, read files, print
sanitized results.

``init`` and ``doctor`` are the backend-aware setup/validation UX (#1115). ``init`` copies
a checked ``examples/<backend>.yaml`` to ``shifter.yaml`` so an operator starts from a
valid, backend-shaped config (local-only — it touches no cloud API and writes no secrets).
``doctor`` validates the selected backend before infrastructure is applied: it runs the
checks the selected backend bundle declares (required tools, secret references, generated
outputs, owned paths, validation checks, and — opt-in — read-only health probes),
classifies each by side-effect tier (local-only, cloud-read-only, deployment-mutating),
and is non-mutating by default.

``render`` (#958) turns the validated, normalized ``settings.range_egress`` policy into
the provider-specific Terraform bridge ``.tfvars`` for the config's backend, so the
deployed firewall rules are generated from the single authoritative source rather than
hand-copied into a second gitignored allowlist (ADR-017-R4).

``render-runtime`` (PLAT-2005) renders the selected backend into the renderer-owned
``cloud_provider`` Terraform tfvar, so the runtime cloud-provider identity is derived
from the validated installation config rather than hardcoded or inferred from a branch
name.

``contract`` (#1323) exports and checks the published, versioned backend-bundle contract
artifact: ``contract export`` regenerates the committed artifact from the Pydantic contract
and registry, and ``contract check`` runs the drift, breaking-change, and registry-
conformance gates (also enforced in the ``installation`` test lane).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cli_parser import build_parser
from .doctor import CheckScope, CheckStatus, DoctorReport, run_doctor
from .errors import InstallationConfigError
from .loader import load_root_config
from .publication import (
    ARTIFACT_PATH,
    build_contract_artifact,
    check_publication,
    serialize_artifact,
    version_snapshot_path,
)
from .render import (
    render_cloud_provider_tfvars,
    render_mission_control_lease_env,
    render_model_access_catalog,
    render_model_access_env,
    render_tfvars,
    render_warm_pool_env,
)
from .runtime_inventory import RUNTIME_SURFACES, validate_runtime_inventory
from .scaffold import ScaffoldError, available_backends, scaffold_config


def _cmd_validate(path_str: str) -> int:
    """Validate the installation root config at ``path_str``; return the process exit code."""
    config_path = Path(path_str)
    try:
        config = load_root_config(config_path)
    except InstallationConfigError as exc:
        print(f"{config_path}: invalid", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue.render()}", file=sys.stderr)
        return 1
    print(
        f"{config_path}: OK — root config shape is valid "
        f"(backend={config.backend}, profile={config.deployment.profile})"
    )
    return 0


def _emit_rendered(rendered: str, output: str | None, backend: str, *, what: str = "range egress bridge tfvars") -> int:
    """Write rendered tfvars to ``output`` (or stdout when None); return the exit code."""
    if output is None:
        sys.stdout.write(rendered)
        return 0
    try:
        # Normalize the operator-supplied path (collapsing `..`); a NUL byte in
        # ``output`` raises ValueError here rather than reaching the filesystem.
        output_path = Path(output).resolve()
        output_path.write_text(rendered, encoding="utf-8")
    except (OSError, ValueError) as exc:
        detail = getattr(exc, "strerror", None) or str(exc)
        print(f"{output!r}: could not write rendered {what}: {detail}", file=sys.stderr)
        return 1
    print(f"{output_path}: wrote {what} ({backend}).", file=sys.stderr)
    return 0


def _cmd_render(path_str: str, output: str | None) -> int:
    """Render the range egress bridge tfvars for the config at ``path_str``."""
    config_path = Path(path_str)
    try:
        config = load_root_config(config_path)
    except InstallationConfigError as exc:
        print(f"{config_path}: invalid", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue.render()}", file=sys.stderr)
        return 1
    return _emit_rendered(render_tfvars(config), output, config.backend)


def _cmd_render_runtime(path_str: str, output: str | None) -> int:
    """Render the renderer-owned ``cloud_provider`` tfvar for the config at ``path_str``."""
    config_path = Path(path_str)
    try:
        config = load_root_config(config_path)
    except InstallationConfigError as exc:
        print(f"{config_path}: invalid", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue.render()}", file=sys.stderr)
        return 1
    return _emit_rendered(render_cloud_provider_tfvars(config), output, config.backend, what="cloud_provider tfvar")


def _cmd_render_warm_pool_env(path_str: str, output: str | None) -> int:
    """Render the ``WARM_POOL_POLICY_JSON`` runtime env line for the config at ``path_str``."""
    config_path = Path(path_str)
    try:
        config = load_root_config(config_path)
    except InstallationConfigError as exc:
        print(f"{config_path}: invalid", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue.render()}", file=sys.stderr)
        return 1
    return _emit_rendered(render_warm_pool_env(config), output, config.backend, what="warm-pool runtime env")


def _cmd_render_mission_control_lease_env(path_str: str, output: str | None) -> int:
    """Render the ``MISSION_CONTROL_LEASE_POLICY_JSON`` runtime env line for ``path_str``."""
    config_path = Path(path_str)
    try:
        config = load_root_config(config_path)
    except InstallationConfigError as exc:
        print(f"{config_path}: invalid", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue.render()}", file=sys.stderr)
        return 1
    return _emit_rendered(
        render_mission_control_lease_env(config), output, config.backend, what="Mission Control lease runtime env"
    )


def _cmd_render_model_access(path_str: str, output: str | None, *, catalog: bool) -> int:
    """Render the mounted model-access artifact or its bounded env references."""
    config_path = Path(path_str)
    try:
        config = load_root_config(config_path)
    except InstallationConfigError as exc:
        print(f"{config_path}: invalid", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue.render()}", file=sys.stderr)
        return 1
    rendered = render_model_access_catalog(config) if catalog else render_model_access_env(config)
    what = "model-access catalog" if catalog else "model-access runtime env"
    return _emit_rendered(rendered, output, config.backend, what=what)


def _cmd_runtime_inventory(repo_root_str: str, *, check: bool) -> int:
    """List or validate checked-in runtime configuration surfaces."""

    repo_root = Path(repo_root_str)
    if check:
        issues = validate_runtime_inventory(repo_root)
        if issues:
            print(f"{repo_root}: runtime inventory invalid", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue.render()}", file=sys.stderr)
            return 1
        print(f"{repo_root}: OK — runtime inventory is current")
        return 0

    print("Runtime configuration surfaces:")
    for surface in RUNTIME_SURFACES:
        print(f"- {surface.path}: {surface.authority} ({surface.owner})")
    return 0


def _cmd_contract_export(output: str | None) -> int:
    """Write the generated contract artifact, and freeze the current version's snapshot if new.

    Writing to a custom ``--output`` only emits the artifact. Writing to the default path also
    mints the frozen per-version snapshot the first time a contract version is published; it
    never overwrites an existing snapshot, so a published version's shape stays immutable.
    """
    artifact = build_contract_artifact()
    rendered = serialize_artifact(artifact)
    destination = Path(output) if output is not None else ARTIFACT_PATH
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        if output is None:
            snapshot = version_snapshot_path(artifact["contract_version"])
            if not snapshot.exists():
                snapshot.write_text(rendered, encoding="utf-8")
                print(f"{snapshot}: froze contract version {artifact['contract_version']} snapshot.", file=sys.stderr)
    except (OSError, ValueError) as exc:
        detail = getattr(exc, "strerror", None) or str(exc)
        print(f"{output or destination}: could not write contract artifact: {detail}", file=sys.stderr)
        return 1
    print(f"{destination}: wrote backend-bundle contract artifact.", file=sys.stderr)
    return 0


def _cmd_contract_check() -> int:
    """Run the drift, breaking-change, and registry-conformance gates."""
    issues = check_publication()
    if issues:
        print("backend-bundle contract check failed:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue.render()}", file=sys.stderr)
        return 1
    print("backend-bundle contract: OK — artifact current, compatible, and conformant")
    return 0


def _cmd_init(backend: str | None, output: str | None, *, force: bool) -> int:
    """Scaffold a starting ``shifter.yaml`` from the checked example for ``backend``."""
    if backend is None:
        print("Available backends:")
        for name in available_backends():
            print(f"  - {name}")
        print("Specify one with: shifter-config init --backend <name>", file=sys.stderr)
        return 2
    try:
        result = scaffold_config(backend, output, force=force)
    except ScaffoldError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"{result.destination}: scaffolded the {result.backend} config from {result.source.name}. "
        f"Next: edit it, then run 'shifter-config doctor {result.destination}'."
    )
    return 0


#: The fixed-width status tags used in the human-readable doctor report.
_STATUS_TAG = {
    CheckStatus.PASS: "PASS",
    CheckStatus.FAIL: "FAIL",
    CheckStatus.WARN: "WARN",
    CheckStatus.SKIP: "SKIP",
    CheckStatus.INFO: "INFO",
}


def _print_doctor_report(report: DoctorReport) -> None:
    """Print a sanitized, tier-labelled doctor report to stdout."""
    print(f"doctor: backend={report.backend or '(unresolved)'} profile={report.profile or '(unknown)'}")
    for result in report.results:
        tag = _STATUS_TAG[result.status]
        line = f"  [{tag}] ({result.tier.value}) {result.name}: {result.summary}"
        if result.remediation:
            line += f"\n         -> {result.remediation}"
        print(line)
    counts = {status: sum(1 for r in report.results if r.status is status) for status in CheckStatus}
    summary = ", ".join(f"{counts[status]} {_STATUS_TAG[status].lower()}" for status in CheckStatus if counts[status])
    print(f"doctor: {summary or 'no checks run'} — {'OK' if report.ok else 'FAILED'}")


def _cmd_doctor(path_str: str, repo_root: str, checks: str, *, as_json: bool) -> int:
    """Validate the backend selected by ``path_str`` and print a tier-labelled report."""
    report = run_doctor(Path(path_str), scope=CheckScope(checks), repo_root=Path(repo_root))
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_doctor_report(report)
    if not report.ok:
        print("doctor: backend not ready — resolve the failures above before deploying.", file=sys.stderr)
    return report.exit_code()


def _cmd_contract(contract_command: str | None, output: str | None, parser: argparse.ArgumentParser) -> int:
    """Dispatch the ``contract`` subcommand."""
    if contract_command == "export":
        return _cmd_contract_export(output)
    if contract_command == "check":
        return _cmd_contract_check()
    parser.print_help(sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    """Run the shifter-config command-line interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    if args.command == "validate":
        exit_code = _cmd_validate(args.path)
    elif args.command == "render":
        exit_code = _cmd_render(args.path, args.output)
    elif args.command == "render-runtime":
        exit_code = _cmd_render_runtime(args.path, args.output)
    elif args.command == "render-warm-pool-env":
        exit_code = _cmd_render_warm_pool_env(args.path, args.output)
    elif args.command == "render-mission-control-lease-env":
        exit_code = _cmd_render_mission_control_lease_env(args.path, args.output)
    elif args.command == "render-model-access-catalog":
        exit_code = _cmd_render_model_access(args.path, args.output, catalog=True)
    elif args.command == "render-model-access-env":
        exit_code = _cmd_render_model_access(args.path, args.output, catalog=False)
    elif args.command == "runtime-inventory":
        exit_code = _cmd_runtime_inventory(args.repo_root, check=args.check)
    elif args.command == "init":
        exit_code = _cmd_init(args.backend, args.output, force=args.force)
    elif args.command == "doctor":
        exit_code = _cmd_doctor(args.path, args.repo_root, args.checks, as_json=args.as_json)
    elif args.command == "contract":
        exit_code = _cmd_contract(args.contract_command, getattr(args, "output", None), parser)
    else:
        parser.print_help(sys.stderr)  # pragma: no cover - argparse rejects unknown subcommands first
        exit_code = 2
    return exit_code


if __name__ == "__main__":  # pragma: no cover - exercised via ``python -m installation``
    sys.exit(main())
