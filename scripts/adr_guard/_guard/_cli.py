"""Command-line interface: argument parsing and the main() entry point."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ._common import (
    REPO_ROOT,
    Violation,
    _normalize_files,
    filter_excepted_violations,
    get_changed_files,
    load_adr_exceptions,
)
from ._registry import (
    CHECKS,
    CHECK_LEVELS,
)


def _parse_args() -> argparse.Namespace:
    """Parse the ADR guard command line and validate the requested check names."""
    valid_checks = sorted(CHECKS)
    parser = argparse.ArgumentParser(description="Run ADR conformance checks")
    parser.add_argument("--checks", nargs="*", default=[], help=f"Explicit checks to run ({', '.join(valid_checks)})")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true", help="Check the full repo")
    scope.add_argument("--changed", action="store_true", help="Check staged or modified files")
    scope.add_argument("--files", nargs="+", help="Check specific repo-relative files")
    parser.add_argument(
        "--level",
        choices=sorted(CHECK_LEVELS),
        default="fast",
        help="Named check profile",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    args = parser.parse_args()
    if args.checks:
        invalid = set(args.checks) - set(valid_checks)
        if invalid:
            parser.error(f"invalid check(s): {', '.join(sorted(invalid))} (choose from {', '.join(valid_checks)})")
    return args


def _selected_files(args: argparse.Namespace, repo_root: Path) -> list[str] | None:
    """Resolve the scope flags to repo-relative files, or None for the whole repo."""
    if args.all:
        return None
    if args.changed:
        return _normalize_files(get_changed_files(repo_root), repo_root)
    return _normalize_files(args.files, repo_root)


def _print_text(violations: list[Violation], checks: list[str], files: list[str] | None) -> None:
    """Print a human-readable summary of the run and any violations found."""
    if not violations:
        scope = "all files" if files is None else f"{len(files)} file(s)"
        print(f"ADR guard passed: {', '.join(checks)} on {scope}")
        return

    print("ADR guard failed:")
    for violation in violations:
        print(f"- [{violation.rule_id}] {violation.path}: {violation.message} (check: {violation.check})")


def main() -> int:
    """Run the selected checks and return the process exit code."""
    args = _parse_args()
    repo_root = REPO_ROOT
    files = _selected_files(args, repo_root)
    checks = args.checks or CHECK_LEVELS[args.level]
    try:
        exceptions = load_adr_exceptions(repo_root)
    except (OSError, ValueError):
        exceptions = []

    violations: list[Violation] = []
    for check in checks:
        violations.extend(CHECKS[check](repo_root, files))
    violations = filter_excepted_violations(violations, exceptions)

    if args.json:
        payload = {
            "checks": checks,
            "files": files,
            "violations": [violation.__dict__ for violation in violations],
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_text(violations, checks, files)

    return 1 if violations else 0
