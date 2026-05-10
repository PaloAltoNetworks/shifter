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
        cloud_touched = any(
            any(f.startswith(root + "/") for root in CLOUD_ROOTS) for f in files
        )
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
            repo_root / path
            for path in files
            if path.startswith("mcp/") and path.endswith((".js", ".mjs", ".cjs"))
        ]
    else:
        candidate_paths = [
            p
            for p in mcp_root.rglob("*")
            if p.is_file()
            and p.suffix in (".js", ".mjs", ".cjs")
            and "node_modules" not in p.parts
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
                f"pod-level securityContext.seccompProfile.type must be 'RuntimeDefault' "
                f"(got {seccomp_type!r})",
            )
        ]
    return []


def _effective_field(
    container_sc: dict, pod_sc: dict, key: str
) -> object:
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
            f"{label} must not set capabilities.add (would re-grant after drop ALL); "
            f"got {capabilities['add']!r}"
        )
    return msgs


def _check_container_seccomp(sc: dict, label: str) -> list[str]:
    """Container-level seccompProfile.type must be RuntimeDefault when set."""
    block = sc.get("seccompProfile")
    if block is not None and not isinstance(block, dict):
        return [f"{label} securityContext.seccompProfile must be a mapping if set"]
    seccomp_type = (block or {}).get("type")
    if seccomp_type is not None and seccomp_type != "RuntimeDefault":
        return [
            f"{label} container-level seccompProfile.type must be 'RuntimeDefault' "
            f"if set (got {seccomp_type!r})"
        ]
    return []


def _check_container_identity(sc: dict, pod_sc: dict, label: str) -> list[str]:
    """runAsNonRoot, runAsUser, runAsGroup with pod-level inheritance."""
    msgs: list[str] = []
    if _effective_field(sc, pod_sc, "runAsNonRoot") is not True:
        msgs.append(
            f"{label} must set runAsNonRoot: true "
            "(directly or via pod-level securityContext)"
        )
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


def _check_k8s_container_security(
    container: dict, pod_sc: dict, rel: str, role: str
) -> list[Violation]:
    """Validate a single container or init container's securityContext.

    Honors pod-level inheritance for runAsNonRoot/runAsUser/runAsGroup
    (Kubernetes lets these be set on the pod and inherited by containers
    unless overridden). Container-only fields (allowPrivilegeEscalation,
    capabilities, readOnlyRootFilesystem, privileged) must be set on the
    container itself.
    """
    name = container.get("name", "<unnamed>")
    label = f"{role} {name!r}"
    sc, structural_violations = _coerce_container_sc(
        container.get("securityContext"), label
    )

    field_msgs: list[str] = []
    field_msgs += _check_container_basic_fields(sc, label)
    field_msgs += _check_container_capabilities(sc, label)
    field_msgs += _check_container_seccomp(sc, label)
    field_msgs += _check_container_identity(sc, pod_sc, label)

    violations = [
        Violation("k8s-deployment-security-context", "ADR-006-R2", rel, msg)
        for msg in field_msgs
    ]
    # Re-stamp rel onto any structural violations from the coercion step.
    for v in structural_violations:
        violations.append(
            Violation(v.check, v.rule_id, rel, v.message)
        )
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
                    "scripts/adr_guard/adr_guard.py",
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
        return None, [
            _v(rel, f"spec.template must be a mapping (got {type(template).__name__})")
        ]
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
                    f"spec.template.spec.{key} must be a non-empty list "
                    f"(got {type(raw).__name__})",
                )
            ]
        return []

    violations: list[Violation] = []
    for entry in raw:
        if not isinstance(entry, dict):
            violations.append(
                _v(rel, f"{role} entry must be a mapping (got {type(entry).__name__})")
            )
            continue
        violations.extend(_check_k8s_container_security(entry, pod_sc, rel, role))
    return violations


def _validate_deployment_documents(
    docs: list[object], rel: str
) -> list[Violation]:
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
        violations.extend(
            _validate_containers_list(
                pod_spec, pod_sc, rel, "containers", "container", required=True
            )
        )
        violations.extend(
            _validate_containers_list(
                pod_spec, pod_sc, rel, "initContainers", "initContainer", required=False
            )
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
                "scripts/adr_guard/adr_guard.py",
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
                    "configured Helm values file is missing; cannot validate this "
                    "environment's chart-rendered output",
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


def _scan_targets(
    repo_root: Path, files: list[str] | None
) -> tuple[bool, bool, list[Path]]:
    """Decide whether to scan base manifests, chart, and which base files to read.

    --all/CI mode (`files is None`) always exercises the chart branch so a
    missing chart directory surfaces as a violation. files-mode (pre-commit)
    triggers each branch only when the changed file set actually overlaps.
    """
    base_dir = repo_root / K8S_BASE_DEPLOYMENT_DIR
    if files is None:
        scan_base = base_dir.exists()
        base_files = (
            sorted(list(base_dir.rglob("*.yaml")) + list(base_dir.rglob("*.yml")))
            if scan_base
            else []
        )
        return scan_base, True, base_files

    scan_base = False
    scan_chart = False
    base_files: list[Path] = []
    for f in files:
        if f.startswith(K8S_BASE_DEPLOYMENT_DIR + "/") and (
            f.endswith(".yaml") or f.endswith(".yml")
        ):
            scan_base = True
            full = repo_root / f
            if full.exists():
                base_files.append(full)
        if f.startswith(HELM_CHART_DIR + "/"):
            scan_chart = True
    return scan_base, scan_chart, base_files


def _validate_base_files(
    repo_root: Path, base_files: list[Path]
) -> list[Violation]:
    violations: list[Violation] = []
    for path in base_files:
        rel = _repo_relative(path, repo_root)
        docs, parse_violations = _iter_yaml_documents(
            path.read_text(encoding="utf-8"), rel
        )
        violations.extend(parse_violations)
        violations.extend(_validate_deployment_documents(docs, rel))
    return violations


def _validate_chart_renders(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    rendered, render_violations = _render_chart_for_validation(
        repo_root, HELM_VALUES_FILES
    )
    violations.extend(render_violations)
    for docs, label in rendered:
        violations.extend(_validate_deployment_documents(docs, label))
    return violations


def check_k8s_deployment_security_context(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
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


CHECKS = {
    "adr-registry": check_adr_registry,
    "layer-imports": check_layer_imports,
    "cross-layer-model-imports": check_cross_layer_model_imports,
    "guardrail-docs": check_guardrail_docs,
    "cloud-factory-seam": check_cloud_factory_seam,
    "mcp-no-shell-exec": check_mcp_no_shell_exec,
    "k8s-deployment-security-context": check_k8s_deployment_security_context,
}
CHECK_LEVELS = {
    "fast": [
        "adr-registry",
        "layer-imports",
        "cross-layer-model-imports",
        "guardrail-docs",
        "cloud-factory-seam",
        "mcp-no-shell-exec",
    ],
    "ci": [
        "adr-registry",
        "layer-imports",
        "cross-layer-model-imports",
        "cloud-factory-seam",
        "mcp-no-shell-exec",
        "k8s-deployment-security-context",
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
