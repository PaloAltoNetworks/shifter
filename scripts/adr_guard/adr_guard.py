#!/usr/bin/env python3
"""Repo-native ADR enforcement checks."""

from __future__ import annotations

import argparse
from datetime import date
from fnmatch import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYERS = ("shared", "engine", "cms", "management", "mission_control", "ctf")
IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+((?:shared|engine|cms|management|mission_control|ctf)(?:\.\w+)*)",
    re.MULTILINE,
)
REQUIRED_ADR_KEYS = {
    "id",
    "title",
    "status",
    "scope",
    "decision",
    "rules",
    "exceptions",
    "enforcement",
    "evidence",
}
REQUIRED_EXCEPTION_KEYS = {"rule_id", "owner", "reason", "expires_on"}
GUARDRAIL_PREFIXES = (
    ".github/workflows/",
    ".claude/hooks/",
    "scripts/adr_guard/",
    "docs/adr/",
)
GUARDRAIL_FILES = {
    ".pre-commit-config.yaml",
    ".claude/settings.json",
    "AGENTS.md",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/copilot-instructions.md",
    ".importlinter",
    ".tflint.hcl",
    ".gitleaks.toml",
}
DOC_PATHS = (
    "docs/adr/",
    "shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md",
    "shifter/shifter_platform/documentation/docs/technical/dev/index.md",
    "shifter/shifter_platform/documentation/docs/technical/index.md",
)


@dataclass(frozen=True)
class Violation:
    """A single ADR guard violation."""

    check: str
    rule_id: str
    path: str
    message: str


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _repo_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _normalize_files(files: list[str] | None, repo_root: Path) -> list[str] | None:
    if files is None:
        return None

    normalized: list[str] = []
    for item in files:
        if not item:
            continue
        path = Path(item)
        if path.is_absolute():
            normalized.append(_repo_relative(path, repo_root))
        else:
            normalized.append(Path(item).as_posix().lstrip("./"))

    return sorted(set(normalized))


def _load_json_yaml(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_adr_registry(repo_root: Path) -> list[dict]:
    """Load and validate the ADR registry shape."""
    path = repo_root / "docs" / "adr" / "index.yaml"
    data = _load_json_yaml(path)
    if not isinstance(data, list):
        raise ValueError("docs/adr/index.yaml must contain a top-level list")
    return data


def load_adr_exceptions(repo_root: Path) -> list[dict]:
    """Load and validate the exception registry shape."""
    path = repo_root / "docs" / "adr" / "exceptions.yaml"
    data = _load_json_yaml(path)
    if not isinstance(data, list):
        raise ValueError("docs/adr/exceptions.yaml must contain a top-level list")
    return data


def validate_adr_exceptions(exceptions: list[dict]) -> list[str]:
    """Validate exception schema and expiry dates."""
    errors: list[str] = []
    for index, exception in enumerate(exceptions):
        missing = REQUIRED_EXCEPTION_KEYS - set(exception)
        if missing:
            errors.append(f"Exception entry {index} is missing keys: {sorted(missing)}")
            continue

        try:
            expires_on = _parse_iso_date(exception["expires_on"])
        except ValueError:
            errors.append(
                f"Exception entry {index} has invalid expires_on date: {exception['expires_on']!r}"
            )
            continue

        if expires_on < date.today():
            errors.append(
                f"Exception entry {index} for {exception['rule_id']} expired on {exception['expires_on']}"
            )

        paths = exception.get("paths", [])
        if paths and not isinstance(paths, list):
            errors.append(f"Exception entry {index} paths must be a list when present")

        checks = exception.get("checks", [])
        if checks and not isinstance(checks, list):
            errors.append(f"Exception entry {index} checks must be a list when present")

    return errors


def exception_matches(violation: Violation, exception: dict) -> bool:
    """Return True if an exception covers a given violation."""
    if exception.get("rule_id") != violation.rule_id:
        return False

    checks = exception.get("checks") or []
    if checks and violation.check not in checks:
        return False

    paths = exception.get("paths") or []
    if not paths:
        return True

    return any(fnmatch(violation.path, pattern) for pattern in paths)


def filter_excepted_violations(violations: list[Violation], exceptions: list[dict]) -> list[Violation]:
    """Drop violations that are covered by a non-expired exception."""
    filtered: list[Violation] = []
    for violation in violations:
        if any(exception_matches(violation, exception) for exception in exceptions):
            continue
        filtered.append(violation)
    return filtered


def load_allowed_imports(config_path: Path) -> dict[str, list[str]]:
    """Load the simple layer import policy without external YAML dependencies."""
    allowed: dict[str, list[str]] = {}
    current_layer: str | None = None

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if stripped == "allowed:":
            continue

        if indent == 2 and stripped.endswith(":"):
            current_layer = stripped[:-1]
            allowed[current_layer] = []
            continue

        if current_layer and indent >= 4 and stripped.startswith("- "):
            allowed[current_layer].append(stripped[2:].strip())

    return allowed


def is_import_allowed(from_layer: str, module_path: str, allowed: dict[str, list[str]]) -> bool:
    """Check whether an import is allowed by the layer policy."""
    for entry in allowed.get(from_layer, []):
        if entry == "shared":
            if module_path == "shared" or module_path.startswith("shared."):
                return True
        elif "." in entry:
            if module_path == entry or module_path.startswith(entry + "."):
                return True
        elif module_path == entry:
            return True
    return False


def iter_layer_files(repo_root: Path, files: list[str] | None) -> list[tuple[str, str]]:
    """Return repo-relative Python files grouped by originating layer."""
    candidates: list[Path]
    if files is None:
        candidates = list((repo_root / "shifter" / "shifter_platform").rglob("*.py"))
    else:
        candidates = [repo_root / rel for rel in files if rel.endswith(".py")]

    layer_files: list[tuple[str, str]] = []
    for path in candidates:
        if not path.exists():
            continue
        rel = _repo_relative(path, repo_root)
        parts = Path(rel).parts
        if len(parts) < 4:
            continue
        if parts[0:2] != ("shifter", "shifter_platform"):
            continue
        layer = parts[2]
        if layer in LAYERS:
            layer_files.append((rel, layer))

    return sorted(set(layer_files))


def get_changed_files(repo_root: Path) -> list[str]:
    """Get staged files, falling back to the current working tree diff."""
    commands = (
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "HEAD"],
    )

    for cmd in commands:
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if files:
                return sorted(set(files))

    return []


def check_adr_registry(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Validate the ADR registry and exception references."""
    violations: list[Violation] = []

    try:
        registry = load_adr_registry(repo_root)
        exceptions = load_adr_exceptions(repo_root)
    except (OSError, ValueError, json.JSONDecodeError) as err:
        return [Violation("adr-registry", "ADR-REGISTRY", "docs/adr", str(err))]

    for error in validate_adr_exceptions(exceptions):
        violations.append(
            Violation(
                "adr-registry",
                "ADR-REGISTRY",
                "docs/adr/exceptions.yaml",
                error,
            )
        )

    adr_ids: set[str] = set()
    rule_ids: set[str] = set()
    for entry in registry:
        missing = REQUIRED_ADR_KEYS - set(entry)
        if missing:
            violations.append(
                Violation(
                    "adr-registry",
                    "ADR-REGISTRY",
                    "docs/adr/index.yaml",
                    f"ADR entry {entry.get('id', '<missing-id>')} is missing keys: {sorted(missing)}",
                )
            )
            continue

        adr_id = entry["id"]
        if adr_id in adr_ids:
            violations.append(
                Violation(
                    "adr-registry",
                    "ADR-REGISTRY",
                    "docs/adr/index.yaml",
                    f"Duplicate ADR id: {adr_id}",
                )
            )
        adr_ids.add(adr_id)

        rules = entry.get("rules", [])
        if not isinstance(rules, list):
            violations.append(
                Violation(
                    "adr-registry",
                    "ADR-REGISTRY",
                    "docs/adr/index.yaml",
                    f"{adr_id} rules must be a list",
                )
            )
            continue

        for rule in rules:
            rule_id = rule.get("id")
            if not rule_id:
                violations.append(
                    Violation(
                        "adr-registry",
                        "ADR-REGISTRY",
                        "docs/adr/index.yaml",
                        f"{adr_id} has a rule without an id",
                    )
                )
                continue
            if rule_id in rule_ids:
                violations.append(
                    Violation(
                        "adr-registry",
                        "ADR-REGISTRY",
                        "docs/adr/index.yaml",
                        f"Duplicate rule id: {rule_id}",
                    )
                )
            rule_ids.add(rule_id)

    for exception in exceptions:
        rule_id = exception.get("rule_id")
        if not rule_id or rule_id not in rule_ids:
            violations.append(
                Violation(
                    "adr-registry",
                    "ADR-REGISTRY",
                    "docs/adr/exceptions.yaml",
                    f"Exception references unknown rule id: {rule_id!r}",
                )
            )

    return violations


def check_layer_imports(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Check the layer import policy against selected files."""
    violations: list[Violation] = []
    config_path = repo_root / "scripts" / "check_layer_imports" / "layer_imports.yaml"
    allowed = load_allowed_imports(config_path)

    for rel, from_layer in iter_layer_files(repo_root, files):
        text = (repo_root / rel).read_text(encoding="utf-8")
        for module in sorted(set(IMPORT_PATTERN.findall(text))):
            to_layer = module.split(".", 1)[0]
            if to_layer == from_layer:
                continue
            if not is_import_allowed(from_layer, module, allowed):
                violations.append(
                    Violation(
                        "layer-imports",
                        "ADR-001-R1",
                        rel,
                        f"{from_layer} may not import {module}",
                    )
                )

    return violations


def check_cross_layer_model_imports(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Find direct cross-layer model imports in selected runtime files."""
    violations: list[Violation] = []

    for rel, from_layer in iter_layer_files(repo_root, files):
        text = (repo_root / rel).read_text(encoding="utf-8")
        for module in sorted(set(IMPORT_PATTERN.findall(text))):
            parts = module.split(".")
            to_layer = parts[0]
            if to_layer == from_layer:
                continue
            if len(parts) >= 2 and parts[1] == "models":
                violations.append(
                    Violation(
                        "cross-layer-model-imports",
                        "ADR-001-R2",
                        rel,
                        f"{from_layer} imports {module}; prefer a service seam or shared contract",
                    )
                )

    return violations


def _is_guardrail_file(path: str) -> bool:
    return path in GUARDRAIL_FILES or any(path.startswith(prefix) for prefix in GUARDRAIL_PREFIXES)


def _is_docs_file(path: str) -> bool:
    return any(path == item or path.startswith(item) for item in DOC_PATHS)


def check_guardrail_docs(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Require documentation updates when guardrails change."""
    if not files:
        return []

    touched_guardrails = [path for path in files if _is_guardrail_file(path)]
    if not touched_guardrails:
        return []

    if any(_is_docs_file(path) for path in files):
        return []

    first_path = touched_guardrails[0]
    return [
        Violation(
            "guardrail-docs",
            "ADR-002-R1",
            first_path,
            "Guardrail changes must update docs/adr or the developer ADR enforcement docs in the same change",
        )
    ]


CHECKS = {
    "adr-registry": check_adr_registry,
    "layer-imports": check_layer_imports,
    "cross-layer-model-imports": check_cross_layer_model_imports,
    "guardrail-docs": check_guardrail_docs,
}
CHECK_LEVELS = {
    "fast": ["adr-registry", "layer-imports", "cross-layer-model-imports", "guardrail-docs"],
    "ci": ["adr-registry", "layer-imports", "cross-layer-model-imports"],
    "all": list(CHECKS),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ADR conformance checks")
    parser.add_argument("checks", nargs="*", choices=sorted(CHECKS), help="Explicit checks to run")
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
    return parser.parse_args()


def _selected_files(args: argparse.Namespace, repo_root: Path) -> list[str] | None:
    if args.all:
        return None
    if args.changed:
        return _normalize_files(get_changed_files(repo_root), repo_root)
    if args.files:
        return _normalize_files(args.files, repo_root)
    return None


def _print_text(violations: list[Violation], checks: list[str], files: list[str] | None) -> None:
    if not violations:
        scope = "all files" if files is None else f"{len(files)} file(s)"
        print(f"ADR guard passed: {', '.join(checks)} on {scope}")
        return

    print("ADR guard failed:")
    for violation in violations:
        print(
            f"- [{violation.rule_id}] {violation.path}: {violation.message}"
            f" (check: {violation.check})"
        )


def main() -> int:
    args = _parse_args()
    repo_root = REPO_ROOT
    files = _selected_files(args, repo_root)
    checks = args.checks or CHECK_LEVELS[args.level]
    try:
        exceptions = load_adr_exceptions(repo_root)
    except (OSError, ValueError, json.JSONDecodeError):
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


if __name__ == "__main__":
    sys.exit(main())
