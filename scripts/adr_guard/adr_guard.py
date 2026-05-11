#!/usr/bin/env python3
"""Repo-native ADR enforcement checks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatch
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
    ".kube-linter.yaml",
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
            errors.append(f"Exception entry {index} has invalid expires_on date: {exception['expires_on']!r}")
            continue

        if expires_on < date.today():
            errors.append(f"Exception entry {index} for {exception['rule_id']} expired on {exception['expires_on']}")

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


CLOUD_ROOTS = (
    "shifter/shifter_platform/shared/cloud",
    "shifter/engine/provisioner/cloud",
)
CLOUD_SKIP_FILES = {"__init__.py", "base.py"}


def check_cloud_factory_seam(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Ensure cloud adapter parity between AWS and GCP (ADR-005-R1).

    Every adapter module in cloud/aws/ must have a counterpart in cloud/gcp/
    and vice versa.  Modules named __init__.py and base.py are excluded since
    they serve structural rather than adapter roles.
    """
    if files is not None:
        cloud_touched = any(any(f.startswith(root + "/") for root in CLOUD_ROOTS) for f in files)
        if not cloud_touched:
            return []

    violations: list[Violation] = []
    for root in CLOUD_ROOTS:
        aws_dir = repo_root / root / "aws"
        gcp_dir = repo_root / root / "gcp"
        if not aws_dir.exists() or not gcp_dir.exists():
            continue
        aws_modules = {f.name for f in aws_dir.glob("*.py")} - CLOUD_SKIP_FILES
        gcp_modules = {f.name for f in gcp_dir.glob("*.py")} - CLOUD_SKIP_FILES
        for missing in sorted(aws_modules - gcp_modules):
            violations.append(
                Violation(
                    "cloud-factory-seam",
                    "ADR-005-R1",
                    f"{root}/gcp/{missing}",
                    f"AWS adapter {missing} has no GCP counterpart",
                )
            )
        for missing in sorted(gcp_modules - aws_modules):
            violations.append(
                Violation(
                    "cloud-factory-seam",
                    "ADR-005-R1",
                    f"{root}/aws/{missing}",
                    f"GCP adapter {missing} has no AWS counterpart",
                )
            )
    return violations


# child_process import shapes we care about (any form — named, default,
# namespace, CJS destructure, bare CJS require — with or without the
# `node:` prefix). We require the import as evidence that this file
# really pulls Node's child_process; without it, an `execSync` token
# could be an unrelated function with the same name.
_CHILD_PROCESS_IMPORT = re.compile(
    r"""(?x)
    (
        from\s*["'](?:node:)?child_process["']
    )
    |
    (
        require\s*\(\s*["'](?:node:)?child_process["']\s*\)
    )
    """,
)
# `execSync as <alias>` in an ESM named-import. Captures the alias
# so we can search for `<alias>(` as a call site too.
_EXEC_SYNC_ALIAS = re.compile(r"\bexecSync\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)")


# Tiny per-state helpers for _strip_js_comments_and_strings.
# Splitting the state machine across these helpers keeps per-function
# cognitive complexity low and avoids a single mega-regex whose
# alternation complexity tripped SonarCloud. Each helper consumes one
# or two characters and returns the next loop state.

_BLANK_KEEP_NEWLINES = {"\n": "\n"}


def _blank_for(ch: str) -> str:
    return _BLANK_KEEP_NEWLINES.get(ch, " ")


def _consume_code(text: str, i: int) -> tuple[int, str, str, str]:
    """Code state. Detects start of comment / string / nothing."""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "/" and nxt == "/":
        return i + 2, "  ", "line_comment", ""
    if ch == "/" and nxt == "*":
        return i + 2, "  ", "block_comment", ""
    if ch in ("'", '"', "`"):
        return i + 1, " ", "string", ch
    return i + 1, ch, "code", ""


def _consume_line_comment(text: str, i: int) -> tuple[int, str, str, str]:
    ch = text[i]
    if ch == "\n":
        return i + 1, "\n", "code", ""
    return i + 1, " ", "line_comment", ""


def _consume_block_comment(text: str, i: int) -> tuple[int, str, str, str]:
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "*" and nxt == "/":
        return i + 2, "  ", "code", ""
    return i + 1, _blank_for(ch), "block_comment", ""


def _consume_string(text: str, i: int, quote: str) -> tuple[int, str, str, str]:
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "\\" and nxt:
        # Two-char escape consumed as whitespace; backslash never
        # closes the string prematurely.
        return i + 2, "  ", "string", quote
    if ch == quote:
        return i + 1, " ", "code", ""
    return i + 1, _blank_for(ch), "string", quote


def _strip_js_comments_and_strings(text: str) -> str:
    """Flatten JS string-literal and comment contents to whitespace.

    Newlines are preserved so error positions stay sane and so `^` /
    line-mode regexes still work. Template-literal substitutions
    (`${...}`) are intentionally not parsed; an `execSync(` inside a
    `` `${...}` `` substitution is a vanishingly rare bypass and falls
    under code-review, not regex.
    """
    out: list[str] = []
    n = len(text)
    i = 0
    state = "code"
    quote = ""
    while i < n:
        if state == "code":
            i, emit, state, quote = _consume_code(text, i)
        elif state == "line_comment":
            i, emit, state, quote = _consume_line_comment(text, i)
        elif state == "block_comment":
            i, emit, state, quote = _consume_block_comment(text, i)
        else:  # state == "string"
            i, emit, state, quote = _consume_string(text, i, quote)
        out.append(emit)
    return "".join(out)


def _build_call_site_pattern(aliases: list[str]) -> re.Pattern[str]:
    """Pattern matching `execSync(` / `exec(` and any captured alias `(`.

    `exec` and `execSync` are the two child_process call shapes that
    take a shell command string. `spawnSync(... { shell: true })` is
    handled by a separate matcher because it requires looking at the
    options object as well as the function name.

    Using `(?<![A-Za-z0-9_$])` rejects unrelated identifiers that
    happen to end in `exec` or `execSync` (e.g. `myExecSync`,
    `regexExec`).
    """
    names = ["execSync", "exec", *aliases]
    alt = "|".join(re.escape(name) for name in names)
    return re.compile(rf"(?<![A-Za-z0-9_$])(?:{alt})\s*\(")


# `spawn` / `spawnSync` / `execFile` / `execFileSync` with
# `{ shell: true }` is just as bad as `exec` from a shell-string
# point of view; the option re-routes the call through `/bin/sh -c`.
# We match the function name immediately followed (eventually) by an
# options object that contains `shell: true`. Because we cannot parse
# JS in a regex, the matcher is intentionally generous: any `shell:
# true` within ~400 characters of a `spawn`/`execFile` call counts.
_SHELL_TRUE_SPAWN = re.compile(
    r"""(?xs)
    (?<![A-Za-z0-9_$])
    (?:spawnSync|spawn|execFileSync|execFile)
    \s*\([^)]{0,400}?
    \bshell\s*:\s*true\b
    """,
)


def check_mcp_no_shell_exec(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid execSync call sites in mcp/ servers (ADR-010-R1).

    Static lower bound for catching shell-string aws-cli invocations:
    if a file under mcp/ both imports `child_process` (in any form —
    named ESM, default ESM, namespace ESM, named CJS, or whole-module
    CJS — including the `node:` prefix) AND contains an `execSync(`
    or aliased call site (`import { execSync as run } ... run(...)`),
    flag it. String literals and comments are flattened to whitespace
    first so they cannot false-positive trip the check or hide a
    real call site. Exceptions (e.g. mcp/ngfw) are filtered through
    docs/adr/exceptions.yaml.

    Static analysis cannot catch every motivated bypass (e.g.
    `const run = cp.execSync; run(...)`); ADR-010 is enforced at
    multiple layers and the static check is the cheap pre-commit
    backstop, not the only line of defence.
    """
    mcp_root = repo_root / "mcp"
    if not mcp_root.exists():
        return []

    if files is not None:
        candidate_paths = [
            repo_root / path for path in files if path.startswith("mcp/") and path.endswith((".js", ".mjs", ".cjs"))
        ]
    else:
        candidate_paths = [
            p
            for p in mcp_root.rglob("*")
            if p.is_file() and p.suffix in (".js", ".mjs", ".cjs") and "node_modules" not in p.parts
        ]

    violations: list[Violation] = []
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Import detection runs on raw text so the matched
        # `"child_process"` string literal is preserved.
        if not _CHILD_PROCESS_IMPORT.search(text):
            continue
        # Alias and call-site detection run on the comment-and-string
        # flattened form so that an `execSync(` token inside a comment
        # or string cannot trigger the check, a real `execSync(` call
        # on a line containing a URL like `"https://..."` is not
        # erased, and a comment like `// execSync as run` cannot
        # synthesise a fake alias that turns innocent `run(` calls
        # into false positives.
        stripped = _strip_js_comments_and_strings(text)
        aliases = _EXEC_SYNC_ALIAS.findall(stripped)
        call_pattern = _build_call_site_pattern(aliases)
        rel = _repo_relative(path, repo_root)
        if call_pattern.search(stripped):
            violations.append(
                Violation(
                    "mcp-no-shell-exec",
                    "ADR-010-R1",
                    rel,
                    "Calls exec/execSync from child_process; MCP servers must invoke external CLIs via argv arrays (spawn/spawnSync/execFile)",
                )
            )
        elif _SHELL_TRUE_SPAWN.search(stripped):
            violations.append(
                Violation(
                    "mcp-no-shell-exec",
                    "ADR-010-R1",
                    rel,
                    "Uses spawn/spawnSync/execFile/execFileSync with { shell: true }; MCP servers must invoke external CLIs via argv arrays without a shell",
                )
            )
    return violations


K8S_BASE_DEPLOYMENT_DIR = "platform/k8s/gcp/base"
HELM_CHART_DIR = "platform/charts/shifter"
# Values files to render for ADR-006-R2 validation. Mirrors the helm-lint
# pre-commit hook's input set so the guard validates the same chart-rendered
# output devs already lint locally.
HELM_VALUES_FILES = (
    "platform/charts/shifter/values-gcp-dev.yaml",
    "platform/charts/shifter/values-gcp-prod.yaml",
)


def _is_real_int(value: object) -> bool:
    """True when value is an int but not a bool (bool subclasses int in Python)."""
    return type(value) is int  # noqa: E721 - intentional exact type check


def _check_k8s_pod_security(pod_sc: dict, rel: str) -> list[Violation]:
    seccomp = pod_sc.get("seccompProfile") or {}
    if not isinstance(seccomp, dict):
        seccomp = {}
    seccomp_type = seccomp.get("type")
    if seccomp_type != "RuntimeDefault":
        return [
            Violation(
                "k8s-deployment-security-context",
                "ADR-006-R2",
                rel,
                f"pod-level securityContext.seccompProfile.type must be 'RuntimeDefault' (got {seccomp_type!r})",
            )
        ]
    return []


def _effective_field(container_sc: dict, pod_sc: dict, key: str) -> object:
    """Resolve a securityContext field that K8s lets the pod default cover.

    Per the Pod spec, container-level overrides take precedence; if the
    container does not set the field, the pod-level value applies. Used
    for runAsNonRoot, runAsUser, runAsGroup.
    """
    if key in container_sc:
        return container_sc.get(key)
    return pod_sc.get(key)


def _coerce_container_sc(raw_sc: object, label: str) -> tuple[dict, list[Violation]]:
    """Coerce a container's `securityContext` into a dict, surfacing structural problems.

    Non-mapping values (YAML aliases resolved to scalars, malformed shapes)
    produce a violation and the caller continues against an empty dict so
    individual field checks don't AttributeError.
    """
    if raw_sc is not None and not isinstance(raw_sc, dict):
        return (
            {},
            [
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    "",  # rel filled in by caller
                    f"{label} securityContext must be a mapping "
                    "(YAML aliases or non-mapping values are not supported by this guard)",
                )
            ],
        )
    return (raw_sc or {}, [])


def _check_container_basic_fields(sc: dict, label: str) -> list[str]:
    """Per-container fields that don't inherit from the pod (ADR-006-R2)."""
    msgs: list[str] = []
    if sc.get("privileged") is True:
        msgs.append(f"{label} must not set securityContext.privileged: true")
    if sc.get("allowPrivilegeEscalation") is not False:
        msgs.append(f"{label} must set allowPrivilegeEscalation: false")
    if sc.get("readOnlyRootFilesystem") is not True:
        msgs.append(f"{label} must set readOnlyRootFilesystem: true")
    return msgs


def _check_container_capabilities(sc: dict, label: str) -> list[str]:
    """capabilities.drop == [ALL] and no capabilities.add key (ADR-006-R2)."""
    msgs: list[str] = []
    capabilities = sc.get("capabilities")
    if capabilities is not None and not isinstance(capabilities, dict):
        msgs.append(f"{label} securityContext.capabilities must be a mapping if set")
        capabilities = {}
    if capabilities is None:
        capabilities = {}
    drop = capabilities.get("drop")
    if drop != ["ALL"]:
        msgs.append(f"{label} must drop ALL capabilities (got {drop!r})")
    if "add" in capabilities:
        msgs.append(
            f"{label} must not set capabilities.add (would re-grant after drop ALL); got {capabilities['add']!r}"
        )
    return msgs


def _check_container_seccomp(sc: dict, label: str) -> list[str]:
    """Container-level seccompProfile.type must be RuntimeDefault when set."""
    block = sc.get("seccompProfile")
    if block is not None and not isinstance(block, dict):
        return [f"{label} securityContext.seccompProfile must be a mapping if set"]
    seccomp_type = (block or {}).get("type")
    if seccomp_type is not None and seccomp_type != "RuntimeDefault":
        return [f"{label} container-level seccompProfile.type must be 'RuntimeDefault' if set (got {seccomp_type!r})"]
    return []


def _check_container_identity(sc: dict, pod_sc: dict, label: str) -> list[str]:
    """runAsNonRoot, runAsUser, runAsGroup with pod-level inheritance."""
    msgs: list[str] = []
    if _effective_field(sc, pod_sc, "runAsNonRoot") is not True:
        msgs.append(f"{label} must set runAsNonRoot: true (directly or via pod-level securityContext)")
    run_as_user = _effective_field(sc, pod_sc, "runAsUser")
    if not _is_real_int(run_as_user) or run_as_user <= 0:
        msgs.append(
            f"{label} runAsUser must be a positive integer "
            f"(directly or via pod-level securityContext); got {run_as_user!r}"
        )
    run_as_group = _effective_field(sc, pod_sc, "runAsGroup")
    if not _is_real_int(run_as_group) or run_as_group <= 0:
        msgs.append(
            f"{label} runAsGroup must be a positive integer "
            f"(directly or via pod-level securityContext); got {run_as_group!r}"
        )
    return msgs


def _check_k8s_container_security(container: dict, pod_sc: dict, rel: str, role: str) -> list[Violation]:
    """Validate a single container or init container's securityContext.

    Honors pod-level inheritance for runAsNonRoot/runAsUser/runAsGroup
    (Kubernetes lets these be set on the pod and inherited by containers
    unless overridden). Container-only fields (allowPrivilegeEscalation,
    capabilities, readOnlyRootFilesystem, privileged) must be set on the
    container itself.
    """
    name = container.get("name", "<unnamed>")
    label = f"{role} {name!r}"
    sc, structural_violations = _coerce_container_sc(container.get("securityContext"), label)

    field_msgs: list[str] = []
    field_msgs += _check_container_basic_fields(sc, label)
    field_msgs += _check_container_capabilities(sc, label)
    field_msgs += _check_container_seccomp(sc, label)
    field_msgs += _check_container_identity(sc, pod_sc, label)

    violations = [Violation("k8s-deployment-security-context", "ADR-006-R2", rel, msg) for msg in field_msgs]
    # Re-stamp rel onto any structural violations from the coercion step.
    for v in structural_violations:
        violations.append(Violation(v.check, v.rule_id, rel, v.message))
    return violations


def _iter_yaml_documents(text: str, rel: str) -> tuple[list[object], list[Violation]]:
    """Parse a (possibly multi-document) YAML file and return docs + parse violations."""
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return (
            [],
            [
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    _ADR_GUARD_PATH,
                    "PyYAML is required to validate K8s deployment security contexts; "
                    "install pyyaml in the runtime environment",
                )
            ],
        )

    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        return (
            [],
            [
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    rel,
                    f"YAML parse error: {exc}",
                )
            ],
        )
    return ([d for d in docs if d is not None], [])


def _v(rel: str, msg: str) -> Violation:
    """Shorthand: ADR-006-R2 violation builder for the K8s deployment check."""
    return Violation("k8s-deployment-security-context", "ADR-006-R2", rel, msg)


def _resolve_pod_spec(doc: dict, rel: str) -> tuple[dict | None, list[Violation]]:
    """Walk doc.spec.template.spec, validating each level is a mapping.

    Returns (pod_spec_or_None, violations). When any level is non-mapping,
    pod_spec is None and the caller skips the per-document checks.
    """
    spec = doc.get("spec")
    if spec is not None and not isinstance(spec, dict):
        return None, [_v(rel, f"spec must be a mapping (got {type(spec).__name__})")]
    spec = spec or {}

    template = spec.get("template")
    if template is not None and not isinstance(template, dict):
        return None, [_v(rel, f"spec.template must be a mapping (got {type(template).__name__})")]
    template = template or {}

    pod_spec = template.get("spec")
    if pod_spec is not None and not isinstance(pod_spec, dict):
        return None, [
            _v(
                rel,
                f"spec.template.spec must be a mapping (got {type(pod_spec).__name__})",
            )
        ]
    return pod_spec or {}, []


def _resolve_pod_sc(pod_spec: dict, rel: str) -> tuple[dict, list[Violation]]:
    """Coerce pod_spec.securityContext to a dict, surfacing structural problems."""
    pod_sc = pod_spec.get("securityContext") or {}
    if not isinstance(pod_sc, dict):
        return {}, [
            _v(
                rel,
                "spec.template.spec.securityContext must be a mapping "
                "(YAML aliases or non-mapping values are not supported by this guard)",
            )
        ]
    return pod_sc, []


def _validate_containers_list(
    pod_spec: dict, pod_sc: dict, rel: str, key: str, role: str, *, required: bool
) -> list[Violation]:
    """Validate every container entry in pod_spec[key]. `required=True` rejects empty/missing."""
    raw = pod_spec.get(key)
    if raw is None and not required:
        return []
    if not isinstance(raw, list) or (required and len(raw) == 0):
        if required:
            return [
                _v(
                    rel,
                    f"spec.template.spec.{key} must be a non-empty list (got {type(raw).__name__})",
                )
            ]
        return []

    violations: list[Violation] = []
    for entry in raw:
        if not isinstance(entry, dict):
            violations.append(_v(rel, f"{role} entry must be a mapping (got {type(entry).__name__})"))
            continue
        violations.extend(_check_k8s_container_security(entry, pod_sc, rel, role))
    return violations


def _validate_deployment_documents(docs: list[object], rel: str) -> list[Violation]:
    """Apply the ADR-006-R2 security-context rule to every Deployment in a parsed document set.

    rel is the file-or-source label included in any Violation produced.
    """
    violations: list[Violation] = []
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "Deployment":
            continue

        pod_spec, structural = _resolve_pod_spec(doc, rel)
        violations.extend(structural)
        if pod_spec is None:
            continue

        pod_sc, sc_violations = _resolve_pod_sc(pod_spec, rel)
        violations.extend(sc_violations)
        violations.extend(_check_k8s_pod_security(pod_sc, rel))
        violations.extend(_validate_containers_list(pod_spec, pod_sc, rel, "containers", "container", required=True))
        violations.extend(
            _validate_containers_list(pod_spec, pod_sc, rel, "initContainers", "initContainer", required=False)
        )
    return violations


def _render_chart_for_validation(
    repo_root: Path, values_files: tuple[str, ...]
) -> tuple[list[tuple[list[object], str]], list[Violation]]:
    """Run `helm template` for each values file and return (parsed docs, label) pairs.

    Returns (rendered_docs_per_values_file, violations). When helm is not
    available the call returns a single Violation pointing at adr_guard.py
    so CI surfaces the missing prerequisite rather than passing silently.
    """
    chart_dir = repo_root / HELM_CHART_DIR
    if not chart_dir.exists():
        return [], [
            Violation(
                "k8s-deployment-security-context",
                "ADR-006-R2",
                HELM_CHART_DIR,
                "configured Helm chart directory is missing; cannot validate "
                "the authoritative deployment contract per ADR-007",
            )
        ]

    import shutil

    helm = shutil.which("helm")
    if helm is None:
        return [], [
            Violation(
                "k8s-deployment-security-context",
                "ADR-006-R2",
                _ADR_GUARD_PATH,
                "helm CLI is required to render the chart for ADR-006-R2 validation; "
                "install helm in the runtime environment "
                "(CI installs it in the adr-conformance and adr-guard-tests jobs)",
            )
        ]

    rendered: list[tuple[list[object], str]] = []
    violations: list[Violation] = []
    for vf in values_files:
        values_path = repo_root / vf
        if not values_path.exists():
            violations.append(
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    vf,
                    "configured Helm values file is missing; cannot validate this environment's chart-rendered output",
                )
            )
            continue
        result = subprocess.run(
            [helm, "template", str(chart_dir), "-f", str(values_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            violations.append(
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    vf,
                    f"helm template failed: {result.stderr.strip() or result.stdout.strip()}",
                )
            )
            continue
        # Violation.path stays repo-relative (the values file) so existing
        # exception globs in docs/adr/exceptions.yaml can match. The render
        # context goes in messages via _validate_deployment_documents, which
        # callers extend with their own context if needed.
        docs, parse_violations = _iter_yaml_documents(result.stdout, vf)
        violations.extend(parse_violations)
        rendered.append((docs, vf))
    return rendered, violations


def _scan_targets(repo_root: Path, files: list[str] | None) -> tuple[bool, bool, list[Path]]:
    """Decide whether to scan base manifests, chart, and which base files to read.

    --all/CI mode (`files is None`) always exercises the chart branch so a
    missing chart directory surfaces as a violation. files-mode (pre-commit)
    triggers each branch only when the changed file set actually overlaps.
    """
    base_dir = repo_root / K8S_BASE_DEPLOYMENT_DIR
    if files is None:
        scan_base = base_dir.exists()
        base_files = sorted(list(base_dir.rglob("*.yaml")) + list(base_dir.rglob("*.yml"))) if scan_base else []
        return scan_base, True, base_files

    scan_base = False
    scan_chart = False
    base_files: list[Path] = []
    for f in files:
        if f.startswith(K8S_BASE_DEPLOYMENT_DIR + "/") and (f.endswith(".yaml") or f.endswith(".yml")):
            scan_base = True
            full = repo_root / f
            if full.exists():
                base_files.append(full)
        if f.startswith(HELM_CHART_DIR + "/"):
            scan_chart = True
    return scan_base, scan_chart, base_files


def _validate_base_files(repo_root: Path, base_files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in base_files:
        rel = _repo_relative(path, repo_root)
        docs, parse_violations = _iter_yaml_documents(path.read_text(encoding="utf-8"), rel)
        violations.extend(parse_violations)
        violations.extend(_validate_deployment_documents(docs, rel))
    return violations


def _validate_chart_renders(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    rendered, render_violations = _render_chart_for_validation(repo_root, HELM_VALUES_FILES)
    violations.extend(render_violations)
    for docs, label in rendered:
        violations.extend(_validate_deployment_documents(docs, label))
    return violations


def _network_policy_violation(path: str, message: str) -> Violation:
    return Violation(
        "k8s-network-policy-coverage",
        "ADR-006-R3",
        path,
        message,
    )


def _as_network_policy_violations(violations: list[Violation]) -> list[Violation]:
    return [_network_policy_violation(violation.path, violation.message) for violation in violations]


def _is_shifter_namespace(name: object) -> bool:
    return isinstance(name, str) and name.startswith("shifter-")


def _document_namespace(doc: object) -> str | None:
    if not isinstance(doc, dict):
        return None
    metadata = doc.get("metadata")
    if not isinstance(metadata, dict):
        return None
    namespace = metadata.get("namespace")
    if isinstance(namespace, str):
        return namespace
    return None


def _collect_shifter_namespaces(docs: list[object]) -> set[str]:
    namespaces: set[str] = set()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        metadata = doc.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if doc.get("kind") == "Namespace":
            name = metadata.get("name")
            if _is_shifter_namespace(name):
                namespaces.add(name)
        namespace = metadata.get("namespace")
        if _is_shifter_namespace(namespace):
            namespaces.add(namespace)
    return namespaces


def _is_default_deny_network_policy(doc: dict) -> bool:
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        return False
    policy_types = spec.get("policyTypes")
    if not isinstance(policy_types, list):
        return False
    if not {"Ingress", "Egress"}.issubset(set(policy_types)):
        return False
    if spec.get("podSelector") != {}:
        return False
    ingress = spec.get("ingress", [])
    egress = spec.get("egress", [])
    return ingress == [] and egress == []


def _network_policy_name(doc: dict) -> str:
    metadata = doc.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
        return metadata["name"]
    return "<unnamed>"


def _shifter_network_policy_docs(docs: list[object]) -> list[tuple[dict, str]]:
    policies: list[tuple[dict, str]] = []
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "NetworkPolicy":
            continue
        namespace = _document_namespace(doc)
        if not _is_shifter_namespace(namespace):
            continue
        policies.append((doc, namespace))
    return policies


def _default_deny_network_policy_namespaces(
    policies: list[tuple[dict, str]],
) -> set[str]:
    return {namespace for doc, namespace in policies if _is_default_deny_network_policy(doc)}


def _iter_egress_destinations(doc: dict) -> list[tuple[int, object]]:
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        return []
    egress_rules = spec.get("egress", [])
    if not isinstance(egress_rules, list):
        return []

    destinations: list[tuple[int, object]] = []
    for rule_index, rule in enumerate(egress_rules):
        if not isinstance(rule, dict) or not isinstance(rule.get("to"), list):
            continue
        destinations.extend((rule_index, destination) for destination in rule["to"])
    return destinations


def _destination_ip_block_cidr(destination: object) -> object:
    if not isinstance(destination, dict):
        return None
    ip_block = destination.get("ipBlock")
    if not isinstance(ip_block, dict):
        return None
    return ip_block.get("cidr")


def _broad_egress_network_policy_violations(policies: list[tuple[dict, str]], rel: str) -> list[Violation]:
    violations: list[Violation] = []
    broad_cidrs = {"0.0.0.0/0", "::/0"}
    for doc, namespace in policies:
        for rule_index, destination in _iter_egress_destinations(doc):
            cidr = _destination_ip_block_cidr(destination)
            if cidr not in broad_cidrs:
                continue
            violations.append(
                _network_policy_violation(
                    rel,
                    f"NetworkPolicy {namespace}/{_network_policy_name(doc)} "
                    f"egress rule {rule_index} allows broad CIDR {cidr}; "
                    "ADR-006-R3 requires explicit service ranges",
                )
            )
    return violations


def _missing_default_deny_network_policy_violations(
    namespaces: set[str], default_deny_namespaces: set[str], rel: str
) -> list[Violation]:
    return [
        _network_policy_violation(
            rel,
            f"namespace {namespace} lacks a default-deny NetworkPolicy covering both ingress and egress",
        )
        for namespace in sorted(namespaces - default_deny_namespaces)
    ]


def _validate_network_policy_documents(docs: list[object], rel: str) -> list[Violation]:
    namespaces = _collect_shifter_namespaces(docs)
    policies = _shifter_network_policy_docs(docs)
    default_deny_namespaces = _default_deny_network_policy_namespaces(policies)
    return [
        *_broad_egress_network_policy_violations(policies, rel),
        *_missing_default_deny_network_policy_violations(namespaces, default_deny_namespaces, rel),
    ]


def _validate_network_policy_base_files(repo_root: Path, base_files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    docs: list[object] = []
    for path in base_files:
        rel = _repo_relative(path, repo_root)
        parsed, parse_violations = _iter_yaml_documents(path.read_text(encoding="utf-8"), rel)
        docs.extend(parsed)
        violations.extend(_as_network_policy_violations(parse_violations))
    if base_files:
        violations.extend(_validate_network_policy_documents(docs, K8S_BASE_DEPLOYMENT_DIR))
    return violations


def _validate_network_policy_chart_renders(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    rendered, render_violations = _render_chart_for_validation(repo_root, HELM_VALUES_FILES)
    violations.extend(_as_network_policy_violations(render_violations))
    for docs, label in rendered:
        violations.extend(_validate_network_policy_documents(docs, label))
    return violations


def check_k8s_deployment_security_context(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Verify pod, container, and init-container securityContext on Deployments (ADR-006-R2).

    Two enforcement sources are scanned per ADR-006-R2 and ADR-007:

    1. **Base manifest snapshots** under `platform/k8s/gcp/base/` (recursive):
       every YAML document with `kind: Deployment` is validated regardless of
       filename or extension.
    2. **Helm chart rendered output**: the chart at
       `platform/charts/shifter` is rendered via `helm template` for each
       supported values file in `HELM_VALUES_FILES`, and every Deployment
       document in the rendered output is validated. Per ADR-007 the chart is
       the authoritative deployment contract; this catches regressions where
       a chart template or values file removes a required securityContext
       field even if the base snapshots remain compliant.

    Honors pod-level securityContext inheritance for runAsNonRoot, runAsUser,
    and runAsGroup (Kubernetes lets these be set on the pod and inherited by
    containers unless overridden).

    Per Deployment:
    - pod-level seccompProfile.type == 'RuntimeDefault'
    - every container AND initContainer (effective context after pod-level
      inheritance):
      - allowPrivilegeEscalation: false (container-only)
      - capabilities.drop: ['ALL'] AND no capabilities.add (container-only)
      - readOnlyRootFilesystem: true (container-only)
      - privileged: not true (container-only)
      - container-level seccompProfile.type, when set, equals 'RuntimeDefault'
      - runAsNonRoot: true (effective)
      - runAsUser, runAsGroup are positive integers (effective; booleans rejected)
    """
    scan_base, scan_chart, base_files = _scan_targets(repo_root, files)
    if not (scan_base or scan_chart):
        return []

    violations: list[Violation] = []
    if scan_base:
        violations.extend(_validate_base_files(repo_root, base_files))
    if scan_chart:
        violations.extend(_validate_chart_renders(repo_root))
    return violations


def check_k8s_network_policy_coverage(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Verify Shifter namespaces are isolated by default-deny NetworkPolicies."""
    scan_base, scan_chart, base_files = _scan_targets(repo_root, files)
    if not (scan_base or scan_chart):
        return []

    violations: list[Violation] = []
    if scan_base:
        violations.extend(_validate_network_policy_base_files(repo_root, base_files))
    if scan_chart:
        violations.extend(_validate_network_policy_chart_renders(repo_root))
    return violations


_TFVARS_SCOPE = ("platform/terraform/environments",)
_SECRET_NAME_GROUP = (
    r"([A-Za-z_][A-Za-z0-9_]*"
    r"(?:_passwords?|_secrets?|_tokens?|_keys?|_credentials?))"
)
_SECRET_VAR_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r'\s*=\s*"[^"]+"',
)
# HCL also supports heredoc string literals (`name = <<EOF` /
# `name = <<-EOF`), which would otherwise bypass the line regex above.
_SECRET_HEREDOC_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*<<-?[A-Za-z_][A-Za-z0-9_]*\s*$",
)
# Object / array assignments to secret-bearing variables. These are
# walked forward to the matching brace/bracket and flagged when any
# string literal appears inside.
_SECRET_BLOCK_OPEN_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*([\{\[])",
)
# Generic single-line assignment to a secret-bearing variable. Used to
# catch function-wrapped string literals like
# `db_password = trimspace("...")` or `api_token = sensitive("...")`
# that the bare-string and block-open patterns above don't cover. The
# RHS is whatever follows `=` on the same line; the violation walker
# then scans for a string literal in that RHS (after stripping trailing
# # / // comments) and flags when present.
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*(.+)$",
)
_STRING_LITERAL_PATTERN = re.compile(r'"[^"]+"')
_BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
# Variable-name suffixes that mark share-only material (SSH/JWT public
# keys, authorized_keys files, public certificates) so the suffix-based
# regex doesn't over-flag them. Matched against `var_name.endswith(...)`
# so a variable like `public_key_password` is NOT exempted (the secret
# suffix `_password` still wins, even though `public_key` appears in
# the name).
_NON_SECRET_NAME_SUFFIXES = (
    "_public_key",
    "_public_keys",
    "_public_cert",
    "_public_certs",
    "_pub_key",
    "_pub_keys",
    "_pubkey",
    "_pubkeys",
    "_authorized_keys",
    "public_key",
    "public_keys",
    "public_cert",
    "public_certs",
    "pub_key",
    "pub_keys",
    "pubkey",
    "pubkeys",
    "authorized_keys",
)


def _strip_hcl_comments(text: str) -> str:
    """Replace HCL block comments with whitespace (preserving newlines).

    Line comments (`#`, `//`) are handled per-line by the caller so it can
    keep line numbers aligned for violation reporting. Block comments are
    stripped here because they can span lines; we replace each character
    with whitespace except newlines so subsequent regexes still see the
    same line numbers.
    """

    def _blank(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return _BLOCK_COMMENT_PATTERN.sub(_blank, text)


def _is_line_commented(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#") or stripped.startswith("//")


def _strip_trailing_line_comment(line: str) -> str:
    """Drop trailing `#` or `//` line-comment tail from an HCL line.

    Walks the line keeping track of whether we're inside a `"..."`
    string so a `#` or `//` inside a string is preserved.
    """
    in_string = False
    escape = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "#":
                return line[:i]
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                return line[:i]
        i += 1
    return line


def _balance_scan(chars: str, depth: int) -> tuple[int, bool, bool]:
    """Scan ``chars`` updating the ``()``/``[]``/``{}`` ``depth``.

    Returns ``(new_depth, saw_delimiter, closed_to_zero)``. ``closed_to_zero``
    is ``True`` the moment depth drops to ``<= 0`` — the expression closed
    within ``chars``.
    """
    saw = False
    for ch in chars:
        if ch in "([{":
            depth += 1
            saw = True
        elif ch in ")]}":
            depth -= 1
            saw = True
            if depth <= 0:
                return depth, saw, True
    return depth, saw, False


def _block_depth_scan(chars: str, depth: int, opener: str, closer: str) -> tuple[int, bool]:
    """Scan ``chars`` updating the ``opener``/``closer`` ``depth``.

    Returns ``(new_depth, closed_to_zero)``; ``closed_to_zero`` is ``True``
    the moment depth returns to ``0``.
    """
    for ch in chars:
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return depth, True
    return depth, False


def _scrub_line(line: str) -> str:
    """Blank out ``"..."`` string contents and drop the trailing ``#``/``//``
    line comment so brace/paren counting ignores both.
    """
    return _strip_trailing_line_comment(_STRING_LITERAL_PATTERN.sub('""', line))


def _find_balanced_close_index(lines: list[str], start_idx: int, start_pos: int) -> int | None:
    """Walk forward from ``lines[start_idx][start_pos:]`` tracking the
    running depth of ``()``/``[]``/``{}`` (string-literal- and line-comment-aware)
    until the depth returns to zero. Returns the line index containing
    the closing delimiter, or ``None`` if no balance by end-of-file. A start
    line with no delimiter at all is treated as the close (nothing to balance).

    Used by the wrapped-expression arm of the secrets check so multi-line
    wrappers like ``db_password = jsonencode({\\n  password = "leak"\\n})``
    are walked across newlines and scanned for inner string literals.
    """
    depth = 0
    started = False
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if _is_line_commented(line):
            continue
        offset = start_pos if idx == start_idx else 0
        depth, saw, closed = _balance_scan(_scrub_line(line)[offset:], depth)
        if saw:
            started = True
        if closed:
            return idx
        if not started:
            return idx  # no opener on the start line — nothing to balance
    return None


def _find_block_close_index(lines: list[str], start_idx: int, opener: str) -> int | None:
    """Return the line index containing the brace/bracket that closes the block.

    ``opener`` is ``"{"`` or ``"["``; matched closer is ``"}"`` / ``"]"``. The
    walk treats string literals and ``#`` / ``//`` line comments as inert
    (their contents don't change the brace count). Returns the matching line
    index, or ``None`` if no close is found by end-of-file.
    """
    closer = "}" if opener == "{" else "]"
    depth = 0
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if _is_line_commented(line):
            continue
        depth, closed = _block_depth_scan(_scrub_line(line), depth, opener, closer)
        if closed:
            return idx
    return None


def _collect_tfvars_candidates(repo_root: Path, files: list[str] | None) -> list[Path]:
    """Resolve the ``*.tfvars`` files in scope: the subset of ``files`` that
    sits under ``platform/terraform/environments/`` when an explicit list is
    given, otherwise every ``*.tfvars`` file under that tree.
    """
    if files is not None:
        in_scope = [p for p in files if p.startswith(_TFVARS_SCOPE) and p.endswith(".tfvars")]
        return [repo_root / p for p in in_scope]
    candidates: list[Path] = []
    for scope in _TFVARS_SCOPE:
        base = repo_root / scope
        if not base.exists():
            continue
        candidates.extend(p for p in base.rglob("*.tfvars") if p.is_file())
    return candidates


def _is_public_material_name(var_name: str) -> bool:
    """``True`` for names ending in a public-material suffix (``*_public_key``,
    ``*_authorized_keys``, ``*_pubkey``, …) — material that is share-only by
    design, so a string literal there is not a leaked secret.
    """
    return any(var_name.endswith(suffix) for suffix in _NON_SECRET_NAME_SUFFIXES)


def _lines_have_string_literal(lines: list[str], start_idx: int, end_idx: int) -> bool:
    """``True`` if any line in ``lines[start_idx:end_idx + 1]`` carries a
    ``"..."`` literal once full-line comments are skipped and trailing
    ``#``/``//`` comment tails are stripped.
    """
    for idx in range(start_idx, end_idx + 1):
        inner = lines[idx]
        if _is_line_commented(inner):
            continue
        if _STRING_LITERAL_PATTERN.search(_strip_trailing_line_comment(inner)):
            return True
    return False


def _wrapped_rhs_has_literal(lines: list[str], idx: int, line: str, rhs: str) -> bool:
    """``True`` if a function-wrapped / expression RHS of a secret assignment
    materializes a string literal — scanning the RHS on the assignment line
    and, when it opens a balanced ``()``/``[]``/``{}`` that spans lines, the
    rest of the multi-line expression.
    """
    if _STRING_LITERAL_PATTERN.search(_strip_trailing_line_comment(rhs)):
        return True
    close_idx = _find_balanced_close_index(lines, idx, line.find("=") + 1)
    if close_idx is None or close_idx <= idx:
        return False
    return _lines_have_string_literal(lines, idx + 1, close_idx)


def _block_assignment_has_literal(lines: list[str], idx: int, opener: str) -> bool:
    """``True`` if the object/array block opened on ``lines[idx]`` carries a
    string literal somewhere between the opener and its matching close (an
    empty block, or one composed solely of var/local/data references, is
    acceptable). A block whose close is never found scans to end-of-file.
    """
    close_idx = _find_block_close_index(lines, idx, opener)
    end_idx = close_idx if close_idx is not None else len(lines) - 1
    return _lines_have_string_literal(lines, idx, end_idx)


def _flagged_secret_var(lines: list[str], idx: int) -> str | None:
    """Return the secret-bearing variable on ``lines[idx]`` that is assigned a
    plaintext string literal — directly, via a heredoc, via an object/array
    block, or wrapped in a function/expression — or ``None`` when the line is
    clean or the variable name is public material.
    """
    line = lines[idx]
    # Priority: a direct ``= "..."`` / heredoc literal, then an object/array
    # block, then any other RHS expression. ``_SECRET_ASSIGNMENT_PATTERN`` is
    # the catch-all, so it is consulted last.
    direct = _SECRET_VAR_PATTERN.match(line) or _SECRET_HEREDOC_PATTERN.match(line)
    block_match = _SECRET_BLOCK_OPEN_PATTERN.match(line)
    wrapped = _SECRET_ASSIGNMENT_PATTERN.match(line)
    match = direct or block_match or wrapped
    if match is None:
        return None
    var_name = match.group(1)
    if _is_public_material_name(var_name):
        return None
    if direct is not None:
        return var_name
    if block_match is not None:
        return var_name if _block_assignment_has_literal(lines, idx, block_match.group(2)) else None
    return var_name if _wrapped_rhs_has_literal(lines, idx, line, wrapped.group(2)) else None


def _scan_tfvars_file(path: Path, repo_root: Path) -> list[Violation]:
    """Scan one ``*.tfvars`` file for plaintext-secret assignments (ADR-004-R7).

    Block comments are spanned BEFORE line splitting so their contents
    (including any ``password = "..."`` examples) cannot trigger the regex;
    line numbers are preserved.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = _strip_hcl_comments(raw_text).splitlines()
    rel = _repo_relative(path, repo_root)
    violations: list[Violation] = []
    for idx, line in enumerate(lines):
        if _is_line_commented(line):
            continue
        var_name = _flagged_secret_var(lines, idx)
        if var_name is None:
            continue
        violations.append(
            Violation(
                "no-plaintext-secrets-in-tfvars",
                "ADR-004-R7",
                rel,
                f"Line {idx + 1}: {var_name!r} is assigned a "
                f"plaintext string literal; reference an out-of-band "
                f"secret store (Secrets Manager, SSM, environment) instead",
            )
        )
    return violations


def check_no_plaintext_secrets_in_tfvars(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid string literals on secret-bearing tfvars assignments (ADR-004-R7).

    Scans ``*.tfvars`` files committed under ``platform/terraform/environments/``
    and flags any line that assigns a quoted string to a variable whose name
    ends in ``_password``, ``_secret``, ``_token``, ``_key``, ``_credentials``,
    or ``_credential``. Var/local/data references and empty strings are allowed
    (they don't materialize a credential in source). ``*.tfvars.example`` files
    and full-line comments are skipped.

    gitleaks catches high-entropy random strings; this is the complementary
    backstop for low-entropy committed credentials that gitleaks ignores
    (e.g. human-typed passwords with mixed case and a single digit suffix).
    """
    violations: list[Violation] = []
    for path in _collect_tfvars_candidates(repo_root, files):
        if path.exists():
            violations.extend(_scan_tfvars_file(path, repo_root))
    return violations


# Canonical Python packages whose pyproject.toml must enforce the per-function
# complexity gate. Keyed off `.pre-commit-config.yaml` ruff hooks. Adding a new
# Python package with a ruff-pre-commit hook means adding it here too.
PYTHON_COMPLEXITY_GATE_PYPROJECTS = (
    "shifter/shifter_platform",
    "shifter/engine/provisioner",
    "shifter/packer",
    "shifter/installation",
    "scripts/bootstrap",
    "scripts/gcp",
    "scripts/check_layer_imports",
    "scripts/check_rds_pending_modifications",
)

# Single repo-wide threshold for ruff's McCabe (C901) check. Equality, not <=.
# Ratchet edits update this constant and the production pyprojects in one PR;
# the constant exists so the ratchet point is searchable.
PYTHON_COMPLEXITY_THRESHOLD = 15

# Path constants referenced by violations and the consistency / reconciliation
# passes. Defined once so messages stay consistent and so SonarCloud's
# duplicate-literal rule is satisfied.
_PRECOMMIT_CONFIG_PATH = ".pre-commit-config.yaml"
_BACKLOG_DOC_PATH = "docs/adr/complexity-backlog.md"
_ADR_GUARD_PATH = "scripts/adr_guard/adr_guard.py"
_CHECK_NAME = "python-complexity-gate"
_RULE_R1 = "ADR-012-R1"
_RULE_R2 = "ADR-012-R2"

# Match `- id: ruff` (not `id: ruff-format`) anywhere in the line.
_RUFF_HOOK_ID_PATTERN = re.compile(r"^\s*-\s+id:\s+ruff\b(?!-)")
# Any new hook entry (used as a "we've moved on" marker by the state machine).
_HOOK_ID_PATTERN = re.compile(r"^\s*-\s+id:")
# `files: ^<path>/` line of a hook.
_HOOK_FILES_LINE_PATTERN = re.compile(r"^\s*files:\s*\^(\S+?)/\s*$")
# A line carrying a `# noqa: ...` exemption that includes C901 anywhere in
# the rules list (e.g. `# noqa: C901`, `# noqa: E501, C901`, `# noqa:C901`).
_NOQA_C901_PATTERN = re.compile(r"#\s*noqa\s*:\s*([A-Z0-9, ]+)")
# A bare `# noqa` with no code list. Ruff treats this as line-level
# suppression of ALL rules, which silently covers C901 on a def line — the
# scanner must detect this even though there is no explicit C901 code.
_NOQA_BARE_PATTERN = re.compile(r"#\s*noqa\b(?!\s*:)")
# `def NAME(` on the same line as a `# noqa: C901` is the repo convention
# (see docs/adr/complexity-backlog.md). Methods (`    def NAME(`) match too.
_DEF_NAME_PATTERN = re.compile(r"\bdef\s+(\w+)\s*\(")
# Source-file directories we never scan for noqa sites.
_NOQA_SCAN_SKIP_PARTS = frozenset({".venv", "venv", "__pycache__", "node_modules", "staticfiles", "migrations"})


def _selector_covers_c901(selector: str) -> bool:
    """Return True if a Ruff selector string would cover the ``C901`` rule.

    Ruff supports both exact codes (``C901``) and category prefixes
    (``C``, ``C9``, ``C90``) plus the wildcard ``ALL``. A selector covers
    ``C901`` whenever ``C901`` starts with it (after upper-casing). This is the
    same semantic ruff uses when expanding selectors against the rule set.
    """
    s = selector.strip().upper()
    if not s:
        return False
    if s == "ALL":
        return True
    return "C901".startswith(s)


def _any_selector_covers_c901(selectors: list[str]) -> bool:
    """Convenience: True iff any selector in ``selectors`` covers C901."""
    return any(_selector_covers_c901(s) for s in selectors)


def _classify_noqa_line(line: str) -> str | None:
    """Classify how a source line relates to C901 suppression.

    Returns:
    - ``"c901"`` — explicit ``# noqa: C901`` (alone or alongside other codes).
    - ``"<noqa-without-def>"`` — explicit ``# noqa: C901`` but no same-line def.
    - ``"<bare-noqa>"`` — bare ``# noqa`` (no code list) on a def line.
    - ``None`` — line does not affect C901.

    The two sentinel strings match the sentinel function names used in
    :func:`_scan_noqa_c901_sites` so the caller can route them straight to
    :func:`_classify_sentinel_noqa`.
    """
    coded_match = _NOQA_C901_PATTERN.search(line)
    def_match = _DEF_NAME_PATTERN.search(line)
    if coded_match:
        codes = {c.strip() for c in coded_match.group(1).split(",")}
        if "C901" not in codes:
            return None
        return "c901" if def_match else "<noqa-without-def>"
    if _NOQA_BARE_PATTERN.search(line) and def_match:
        return "<bare-noqa>"
    return None


def _scan_file_for_noqa(path: Path, relpath: str, sites: dict[tuple[str, str], tuple[str, int]]) -> None:
    """Scan one source file and record any C901-affecting noqa sites."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    for lineno, line in enumerate(lines, start=1):
        classification = _classify_noqa_line(line)
        if classification is None:
            continue
        if classification == "c901":
            # def_match is guaranteed by the "c901" branch in _classify_noqa_line.
            def_match = _DEF_NAME_PATTERN.search(line)
            assert def_match is not None
            sites[(relpath, def_match.group(1))] = (line.strip(), lineno)
        else:
            sites[(relpath, classification)] = (line.strip(), lineno)


def _scan_noqa_c901_sites(repo_root: Path) -> dict[tuple[str, str], tuple[str, int]]:
    """Walk canonical packages for noqa lines that suppress C901.

    Returns a mapping ``(file_relpath, function_name) -> (line_text, line_no)``.
    The line text/number are surfaced so violations can cite the source.

    Recognized exemption shapes on a ``def NAME(`` line:
    - ``# noqa: ..., C901, ...`` — explicit C901 code list (the repo convention).
    - ``# noqa`` (bare, no code list) — ruff suppresses every rule on the line,
      including C901. The scanner records this under the sentinel function name
      ``"<bare-noqa>"`` so the caller can emit a "use explicit codes" violation.

    Lines that carry ``# noqa: C901`` but no same-line ``def NAME(`` are recorded
    under ``"<noqa-without-def>"`` so the caller can emit a wrong-placement
    violation.
    """
    sites: dict[tuple[str, str], tuple[str, int]] = {}
    for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS:
        root = repo_root / pkg
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in _NOQA_SCAN_SKIP_PARTS for part in path.parts):
                continue
            relpath = path.resolve().relative_to(repo_root.resolve()).as_posix()
            _scan_file_for_noqa(path, relpath, sites)
    return sites


def _parse_complexity_backlog(repo_root: Path) -> set[tuple[str, str]] | None:
    """Parse the ADR-012 backlog doc into a set of ``(file, function)`` pairs.

    Returns ``None`` if the doc is missing (the caller emits a dedicated
    "missing backlog" violation). Empty backlog returns an empty set.

    Implementation: cell-by-cell split on ``|`` rather than a multi-quantifier
    regex. Linear in input size with no backtracking surface.
    """
    path = repo_root / _BACKLOG_DOC_PATH
    if not path.exists():
        return None
    entries: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        # A markdown table row has empty leading/trailing cells. The required
        # leading columns are `<pkg>|<file>|<fn>|<complexity>`; downstream
        # columns (tracking issue, owner, etc.) are accepted as long as the
        # leading shape is intact.
        if len(cells) < 6 or cells[0] or cells[-1]:
            continue
        _pkg, file_cell, fn_cell, comp_cell = cells[1], cells[2], cells[3], cells[4]
        if not (file_cell.startswith("`") and file_cell.endswith("`")):
            continue
        if not (fn_cell.startswith("`") and fn_cell.endswith("`")):
            continue
        if not comp_cell.isdigit():
            continue
        entries.add((file_cell.strip("`"), fn_cell.strip("`")))
    return entries


def _ruff_hook_paths_from_precommit(repo_root: Path) -> set[str] | None:
    """Return package paths covered by `id: ruff` hooks in .pre-commit-config.yaml.

    Returns ``None`` if the file is missing (synthetic test fixtures may omit
    it). Returns a set of path strings without leading ``^`` or trailing ``/``.

    Implementation: a simple line-by-line state machine, not a single multi-line
    regex. Avoids nested quantifiers (and the ReDoS-style backtracking risk
    SonarCloud's ``python:S5852`` would flag) and reads cleanly: a hook entry
    with ``id: ruff`` arms the state, and the next ``files:`` line emits the
    captured path.
    """
    config_path = repo_root / _PRECOMMIT_CONFIG_PATH
    if not config_path.exists():
        return None
    paths: set[str] = set()
    armed = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if _RUFF_HOOK_ID_PATTERN.match(line):
            armed = True
            continue
        if armed:
            files_match = _HOOK_FILES_LINE_PATTERN.match(line)
            if files_match:
                paths.add(files_match.group(1))
                armed = False
            elif _HOOK_ID_PATTERN.match(line):
                # A new hook started before we saw `files:`; disarm but
                # don't lose a fresh `id: ruff` line that may be this one.
                armed = bool(_RUFF_HOOK_ID_PATTERN.match(line))
    return paths


def _is_change_relevant(files: list[str] | None) -> bool:
    """Return True if the file list (``--files`` / ``--changed``) requires the check.

    The complexity gate runs unconditionally on ``--all`` (``files is None``).
    For targeted runs, only changes that could affect the gate are relevant:
    canonical pyprojects, ``.pre-commit-config.yaml``, the backlog doc,
    ``scripts/adr_guard/adr_guard.py`` (where the constants live), or any
    ``.py`` file under one of the canonical packages.
    """
    if files is None:
        return True
    canonical_paths = {f"{pkg}/pyproject.toml" for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS}
    fixed_relevant = canonical_paths | {
        _PRECOMMIT_CONFIG_PATH,
        _BACKLOG_DOC_PATH,
        _ADR_GUARD_PATH,
    }
    touched = set(files)
    if touched & fixed_relevant:
        return True
    return any(
        f.endswith(".py") and any(f.startswith(f"{pkg}/") for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS) for f in touched
    )


def _violation_r1(path: str, message: str) -> Violation:
    """Shorthand for an ADR-012-R1 violation under this check."""
    return Violation(_CHECK_NAME, _RULE_R1, path, message)


def _violation_r2(path: str, message: str) -> Violation:
    """Shorthand for an ADR-012-R2 violation under this check."""
    return Violation(_CHECK_NAME, _RULE_R2, path, message)


def _load_lint_section(path: Path) -> tuple[dict, Violation | None]:
    """Read a pyproject.toml and return its ``[tool.ruff.lint]`` mapping.

    Returns ``({}, Violation)`` on TOML decode errors so the caller can record
    the failure and continue to the next package. The relative path is derived
    from ``path``'s last two components (``<pkg>/pyproject.toml``).
    """
    relative = f"{path.parent.name}/{path.name}" if path.parent.name else path.name
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return {}, _violation_r1(relative, f"pyproject.toml is not valid TOML: {exc}")
    lint = data.get("tool", {}).get("ruff", {}).get("lint", {})
    return lint, None


def _check_select(lint: dict, relative: str) -> list[Violation]:
    """C901 must be covered by ``select`` or ``extend-select``."""
    if _any_selector_covers_c901(lint.get("select", [])) or _any_selector_covers_c901(lint.get("extend-select", [])):
        return []
    return [
        _violation_r1(
            relative,
            '[tool.ruff.lint].select must enable "C901" (per-function complexity gate)',
        )
    ]


def _check_ignore_field(lint: dict, field: str, relative: str) -> list[Violation]:
    """``ignore`` / ``extend-ignore`` must not suppress C901 by any prefix."""
    covers = [s for s in lint.get(field, []) if _selector_covers_c901(s)]
    if not covers:
        return []
    return [
        _violation_r1(
            relative,
            f'[tool.ruff.lint].{field} must not suppress "C901" (selectors that cover it: {sorted(covers)})',
        )
    ]


def _check_per_file_ignores(lint: dict, relative: str) -> list[Violation]:
    """``per-file-ignores`` must not exempt C901 from any glob."""
    per_file_ignores = lint.get("per-file-ignores", {})
    broad = sorted(glob for glob, rules in per_file_ignores.items() if any(_selector_covers_c901(r) for r in rules))
    if not broad:
        return []
    return [
        _violation_r1(
            relative,
            '[tool.ruff.lint.per-file-ignores] must not suppress "C901" '
            f"(globs with covering selectors: {broad}); use per-function "
            "`# noqa: C901` instead",
        )
    ]


def _check_max_complexity(lint: dict, relative: str) -> list[Violation]:
    """``mccabe.max-complexity`` must equal the repo-wide threshold."""
    mccabe = lint.get("mccabe", {})
    if "max-complexity" not in mccabe:
        return [
            _violation_r1(
                relative,
                f"[tool.ruff.lint.mccabe].max-complexity must be set to {PYTHON_COMPLEXITY_THRESHOLD}",
            )
        ]
    if mccabe["max-complexity"] != PYTHON_COMPLEXITY_THRESHOLD:
        return [
            _violation_r1(
                relative,
                "[tool.ruff.lint.mccabe].max-complexity must equal "
                f"{PYTHON_COMPLEXITY_THRESHOLD} (got {mccabe['max-complexity']})",
            )
        ]
    return []


def _check_canonical_pyproject(pkg: str, repo_root: Path) -> list[Violation]:
    """Run all per-package pyproject checks for one canonical package."""
    relative = f"{pkg}/pyproject.toml"
    path = repo_root / pkg / "pyproject.toml"
    if not path.exists():
        return [
            _violation_r1(
                relative,
                f"missing pyproject.toml for canonical Python package {pkg}",
            )
        ]
    lint, decode_violation = _load_lint_section(path)
    if decode_violation is not None:
        return [decode_violation]
    return [
        *_check_select(lint, relative),
        *_check_ignore_field(lint, "ignore", relative),
        *_check_ignore_field(lint, "extend-ignore", relative),
        *_check_per_file_ignores(lint, relative),
        *_check_max_complexity(lint, relative),
    ]


def _check_precommit_consistency(repo_root: Path) -> list[Violation]:
    """Cross-check the constant against ``.pre-commit-config.yaml`` ruff hooks.

    Skips silently when the config file is missing (synthetic test fixtures
    legitimately omit it).
    """
    hook_paths = _ruff_hook_paths_from_precommit(repo_root)
    if hook_paths is None:
        return []
    constant = set(PYTHON_COMPLEXITY_GATE_PYPROJECTS)
    violations: list[Violation] = []
    for missing in sorted(hook_paths - constant):
        violations.append(
            _violation_r1(
                _PRECOMMIT_CONFIG_PATH,
                f"ruff pre-commit hook covers {missing!r} but it is not in "
                "PYTHON_COMPLEXITY_GATE_PYPROJECTS; add it or remove the hook",
            )
        )
    for stale in sorted(constant - hook_paths):
        violations.append(
            _violation_r1(
                _ADR_GUARD_PATH,
                f"PYTHON_COMPLEXITY_GATE_PYPROJECTS includes {stale!r} but no "
                "matching `id: ruff` hook exists in .pre-commit-config.yaml",
            )
        )
    return violations


def _classify_sentinel_noqa(file_: str, func: str, line_text: str, lineno: int) -> Violation | None:
    """Return a violation for sentinel noqa entries (wrong placement / bare)."""
    if func == "<noqa-without-def>":
        return _violation_r2(
            f"{file_}:{lineno}",
            f"`# noqa: C901` must be on the `def NAME(` line, not {line_text!r}",
        )
    if func == "<bare-noqa>":
        return _violation_r2(
            f"{file_}:{lineno}",
            "bare `# noqa` on a `def` line is forbidden — it silently "
            "suppresses C901; use an explicit code list (e.g. `# noqa: C901`) "
            "and add a backlog row",
        )
    return None


def _check_backlog_reconciliation(repo_root: Path) -> list[Violation]:
    """Compare in-source ``# noqa: C901`` sites against the ADR-012 backlog."""
    backlog = _parse_complexity_backlog(repo_root)
    if backlog is None:
        return [
            _violation_r2(
                _BACKLOG_DOC_PATH,
                "ADR-012 backlog doc is missing; the reconciliation gate cannot operate without it",
            )
        ]

    violations: list[Violation] = []
    noqa_sites = _scan_noqa_c901_sites(repo_root)
    # Sentinels first so authors get the clearer hint before the set-diff one.
    for (file_, func), (line_text, lineno) in sorted(noqa_sites.items()):
        sentinel = _classify_sentinel_noqa(file_, func, line_text, lineno)
        if sentinel is not None:
            violations.append(sentinel)

    # The keys of noqa_sites are already (file, func) tuples; filter on the
    # function-name component without redundant unpacking-on-iteration.
    noqa_pairs = {key for key in noqa_sites if not key[1].startswith("<")}
    for file_, func in sorted(noqa_pairs - backlog):
        _line_text, lineno = noqa_sites[(file_, func)]
        violations.append(
            _violation_r2(
                f"{file_}:{lineno}",
                f"unauthorized `# noqa: C901` exemption on `{func}` — add a row "
                f"to {_BACKLOG_DOC_PATH} or refactor the function below the threshold",
            )
        )
    for file_, func in sorted(backlog - noqa_pairs):
        violations.append(
            _violation_r2(
                _BACKLOG_DOC_PATH,
                f"stale backlog row for `{file_}::{func}` — no matching "
                "`# noqa: C901` exists in source; remove the row",
            )
        )
    return violations


def check_python_complexity_gate(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Enforce ADR-012-R1 / R2: per-package ruff config + backlog reconciliation.

    Three layers, applied independently:

    1. **Per-package pyproject.toml checks.** For each canonical package, verify
       that C901 is enabled (``select`` / ``extend-select`` with prefix
       semantics), not suppressed via ``ignore`` / ``extend-ignore`` /
       ``per-file-ignores``, and that ``mccabe.max-complexity`` equals
       :data:`PYTHON_COMPLEXITY_THRESHOLD`.
    2. **Pre-commit consistency.** ``PYTHON_COMPLEXITY_GATE_PYPROJECTS`` must
       match the ``id: ruff`` hook working directories in
       ``.pre-commit-config.yaml`` (in both directions).
    3. **Backlog reconciliation.** Every ``# noqa: C901`` in source must map
       1:1 to a row in ``docs/adr/complexity-backlog.md``; bare ``# noqa`` on
       a def line and ``# noqa: C901`` on a non-def line are explicit errors.

    This is a config-shape and reconciliation validator only. Computing
    per-function complexity is Ruff's job; this check is the structural
    backstop against silent gate removal and untracked exemptions.

    When ``files`` is supplied, the check is a no-op unless one of the relevant
    surfaces is in the change set (see :func:`_is_change_relevant`).
    """
    if not _is_change_relevant(files):
        return []
    violations: list[Violation] = []
    for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS:
        violations.extend(_check_canonical_pyproject(pkg, repo_root))
    violations.extend(_check_precommit_consistency(repo_root))
    violations.extend(_check_backlog_reconciliation(repo_root))
    return violations


CHECKS = {
    "adr-registry": check_adr_registry,
    "layer-imports": check_layer_imports,
    "cross-layer-model-imports": check_cross_layer_model_imports,
    "guardrail-docs": check_guardrail_docs,
    "cloud-factory-seam": check_cloud_factory_seam,
    "mcp-no-shell-exec": check_mcp_no_shell_exec,
    "k8s-deployment-security-context": check_k8s_deployment_security_context,
    "k8s-network-policy-coverage": check_k8s_network_policy_coverage,
    "no-plaintext-secrets-in-tfvars": check_no_plaintext_secrets_in_tfvars,
    "python-complexity-gate": check_python_complexity_gate,
}
CHECK_LEVELS = {
    "fast": [
        "adr-registry",
        "layer-imports",
        "cross-layer-model-imports",
        "guardrail-docs",
        "cloud-factory-seam",
        "mcp-no-shell-exec",
        "no-plaintext-secrets-in-tfvars",
        "python-complexity-gate",
    ],
    "ci": [
        "adr-registry",
        "layer-imports",
        "cross-layer-model-imports",
        "cloud-factory-seam",
        "mcp-no-shell-exec",
        "k8s-deployment-security-context",
        "k8s-network-policy-coverage",
        "no-plaintext-secrets-in-tfvars",
        "python-complexity-gate",
    ],
    "all": list(CHECKS),
}


def _parse_args() -> argparse.Namespace:
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
        print(f"- [{violation.rule_id}] {violation.path}: {violation.message} (check: {violation.check})")


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
