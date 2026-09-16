"""Guardrail-docs, documentation-coverage, and agent-attribution checks."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .._common import (
    Violation,
    _load_json_yaml,
)


GUARDRAIL_PREFIXES = (
    ".github/workflows/",
    ".claude/hooks/",
    "scripts/adr_guard/",
    "docs/adr/",
)
GUARDRAIL_FILES = {
    ".pre-commit-config.yaml",
    ".ground-control.yaml",
    ".gc/plan-rules.md",
    ".claude/settings.json",
    "AGENTS.md",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/copilot-instructions.md",
    ".github/dependabot.yml",
    ".importlinter",
    ".tflint.hcl",
    ".gitleaks.toml",
    ".kube-linter.yaml",
    ".shifter.yaml",
    ".cursor/cli.json",
}
DOC_PATHS = (
    "docs/adr/",
    "docs/technical/dev/adr-enforcement.md",
    "docs/technical/dev/index.md",
    "docs/technical/index.md",
)


def _is_guardrail_file(path: str) -> bool:
    """True when the path is a guardrail definition governed by ADR-002-R1."""
    return path in GUARDRAIL_FILES or any(
        path.startswith(prefix) for prefix in GUARDRAIL_PREFIXES
    )


def _is_docs_file(path: str) -> bool:
    """True when the path is one of the docs that can satisfy a guardrail change."""
    return any(path == item or path.startswith(item) for item in DOC_PATHS)


def check_guardrail_docs(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Require documentation updates when guardrails change."""
    del repo_root
    paths = files or []
    touched_guardrails = [path for path in paths if _is_guardrail_file(path)]
    if not touched_guardrails or any(_is_docs_file(path) for path in paths):
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


def check_no_agent_attribution(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Reject AI/agent marketing or co-author attribution in tracked text."""
    from agent_attribution import find_agent_attribution_matches

    candidates = files
    if candidates is None:
        candidates = [
            rel
            for rel in subprocess.check_output(
                ["git", "ls-files"], cwd=repo_root, text=True
            ).splitlines()
            if rel
        ]

    violations: list[Violation] = []
    for rel in candidates:
        if rel in _AGENT_ATTRIBUTION_SCAN_SKIP:
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        matches = find_agent_attribution_matches(text)
        if not matches:
            continue
        first = matches[0]
        violations.append(
            Violation(
                "no-agent-attribution",
                "ADR-002-R2",
                rel,
                f"Prohibited AI/agent attribution ({first.rule}): {first.excerpt}",
            )
        )
    return violations


DOCS_COVERAGE_MANIFEST = "docs/adr/documentation-coverage.yaml"
DOCS_COVERAGE_RULE_ID = "ADR-022-R1"
LILRAE_IDENTITY_RULE_ID = "ADR-024-R6"
ADR_INDEX_PATH = "docs/adr/index.yaml"
_LILRAE_IDENTITY_PREFLIGHT = (
    "docs/architecture/aptl-lilrae-techvault-identity-preflight-2062.md"
)
_LILRAE_CURRENT_PROSE_FILES = {
    ADR_INDEX_PATH,
    "docs/architecture/aces-polaris-acceptance-parity-gate-preflight-1237.md",
    "docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md",
    "docs/architecture/polaris-aws-agent-credentials-preflight-1377.md",
    "docs/architecture/polaris-support-decomposition-preflight-691.md",
    "docs/architecture/raes-hard-cutover-preflight-1862.md",
    "docs/architecture/raes-migration-adr.md",
    "docs/requirements/PLAT-2010/requirement.md",
    "docs/requirements/PLAT-211/requirement.md",
    "docs/requirements/PLAT-212/requirement.md",
    "docs/requirements/PLAT-213/requirement.md",
    "docs/requirements/PLAT-214/requirement.md",
    "docs/requirements/PLAT-215/requirement.md",
    "docs/requirements/PLAT-216/requirement.md",
}
_RETIRED_TECHVAULT_DOCS = {
    "docs/architecture/gce-per-instance-image-resolution-preflight-1761.md",
    "docs/architecture/gcp-normal-scenario-range-cell-migration-preflight-1350.md",
    "docs/architecture/gcp-techvault-gce-image-preflight-1760.md",
    "docs/architecture/packer-scenario-bake-standardization-preflight-1469.md",
    "docs/architecture/rev1-build-deployment-provenance-preflight-1519.md",
    "docs/architecture/techvault-encrypted-ami-preflight-1455.md",
}
_HISTORICAL_BOUNDARY_MARKER = "**Historical boundary (issue #2062, 2026-08-19):**"
_FALSE_TECHVAULT_PAIR = re.compile(
    r"\bTechVault\s*/\s*(?:APTL|LilRAE)\b", re.IGNORECASE
)
_FALSE_IDENTITY_SPLIT = re.compile(
    r"\b(?:APTL\s+and\s+LilRAE|LilRAE\s+and\s+APTL)\s+"
    r"(?:are|remain|represent)\s+(?:two\s+|separate\s+|distinct\s+|different\s+)",
    re.IGNORECASE,
)
_FALSE_TECHVAULT_ROLE = re.compile(
    r"\bTechVault\s+(?:is|was|remains|acts\s+as|serves\s+as)\s+"
    r"(?:an?\s+)?(?:APTL|LilRAE|product|experience|plugin|platform|layer)\b",
    re.IGNORECASE,
)
_FALSE_APTL_HOST_RELATION = re.compile(
    r"(?:\bAPTL\b.{0,80}\b(?:hosted\s+(?:by|on|inside)|plugin|experience)\b"
    r".{0,80}\bLilRAE\b|\bLilRAE\b.{0,80}\bhosts?\b.{0,80}\bAPTL\b)",
    re.IGNORECASE | re.DOTALL,
)
_AGENT_ATTRIBUTION_SCAN_SKIP = {
    "scripts/adr_guard/agent_attribution.py",
    "scripts/adr_guard/block_agent_attribution_commit_msg.py",
    "scripts/adr_guard/tests/test_agent_attribution.py",
}
_DOCS_EXCLUDED_PART = "_deprecated"
_MARKDOWN_LINK_PATTERN = re.compile(r"\]\(([^)\s]+)")


def _normalize_doc_slug(value: str) -> str:
    """Normalize a posix doc slug, resolving ``.``/``..`` segments."""
    segments: list[str] = []
    for segment in value.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    return "/".join(segments)


def _doc_path_is_excluded(slug: str) -> bool:
    """A doc under a ``_deprecated`` or hidden path part is not serveable."""
    return any(
        part == _DOCS_EXCLUDED_PART or part.startswith(".")
        for part in slug.split("/")
        if part
    )


def _index_link_targets(text: str) -> list[str]:
    """Return the relative, extension-stripped doc targets linked from index markdown."""
    targets: list[str] = []
    for raw in _MARKDOWN_LINK_PATTERN.findall(text):
        target = raw.split("#", 1)[0].split("?", 1)[0]
        if not target or "://" in target or target.startswith(("mailto:", "/")):
            continue
        if target.endswith(".md"):
            target = target[: -len(".md")]
        targets.append(target)
    return targets


def _collect_index_link_slugs(docs_root: Path) -> set[str]:
    """Return the set of docs-root-relative slugs linked from any index.md."""
    linked: set[str] = set()
    if not docs_root.is_dir():
        return linked
    for index_file in docs_root.rglob("index.md"):
        rel_parts = index_file.relative_to(docs_root).parts
        if any(
            part == _DOCS_EXCLUDED_PART or part.startswith(".") for part in rel_parts
        ):
            continue
        index_dir = "/".join(rel_parts[:-1])
        try:
            text = index_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in _index_link_targets(text):
            linked.add(_normalize_doc_slug(f"{index_dir}/{target}"))
    return linked


def _coverage_violation(path: str, message: str) -> Violation:
    """Build a documentation-coverage violation for ``path``."""
    return Violation("documentation-coverage", DOCS_COVERAGE_RULE_ID, path, message)


def _coverage_manifest_shape_error(manifest: object) -> str | None:
    """Return the shape error for a loaded coverage manifest, or None when valid."""
    if not isinstance(manifest, dict):
        return "documentation coverage manifest must be a JSON object"
    if not isinstance(manifest.get("docs_root"), str) or not isinstance(
        manifest.get("features"), list
    ):
        return "manifest must define a string 'docs_root' and a list of 'features'"
    return None


def _load_coverage_manifest(
    repo_root: Path,
) -> tuple[dict[str, object] | None, list[Violation]]:
    """Load the coverage manifest, returning it or the violations that block the check."""
    try:
        manifest = _load_json_yaml(repo_root / DOCS_COVERAGE_MANIFEST)
    except (OSError, ValueError) as err:
        return None, [_coverage_violation(DOCS_COVERAGE_MANIFEST, str(err))]

    shape_error = _coverage_manifest_shape_error(manifest)
    if shape_error is not None:
        return None, [_coverage_violation(DOCS_COVERAGE_MANIFEST, shape_error)]
    return manifest, []


def _check_feature_doc(
    feature_id: object,
    rel: str,
    docs_root_rel: str,
    docs_root: Path,
    linked_slugs: set[str],
) -> list[Violation]:
    """Validate one doc referenced by a feature: served, present, and index-linked."""
    slug = _normalize_doc_slug(rel)
    doc_path = f"{docs_root_rel}/{slug}"
    doc_slug = slug[: -len(".md")] if slug.endswith(".md") else slug
    if _doc_path_is_excluded(slug):
        message = f"feature {feature_id} references a deprecated or hidden doc that is not served"
    elif not (docs_root / slug).is_file():
        message = f"feature {feature_id} references a missing doc"
    elif doc_slug not in linked_slugs:
        message = f"feature {feature_id} references an orphaned doc not linked from any index.md"
    else:
        return []
    return [_coverage_violation(doc_path, message)]


def _check_feature_coverage(
    feature: object,
    docs_root_rel: str,
    docs_root: Path,
    linked_slugs: set[str],
) -> list[Violation]:
    """Validate a single manifest feature entry and every doc it references."""
    if not isinstance(feature, dict):
        return [
            _coverage_violation(
                DOCS_COVERAGE_MANIFEST, "each feature entry must be a JSON object"
            )
        ]

    feature_id = feature.get("id") or "<unknown>"
    user_docs = feature.get("user_docs") or []
    technical_docs = feature.get("technical_docs") or []
    violations: list[Violation] = []
    if not user_docs:
        violations.append(
            _coverage_violation(
                DOCS_COVERAGE_MANIFEST,
                f"feature {feature_id} must declare at least one user doc",
            )
        )
    if not technical_docs:
        violations.append(
            _coverage_violation(
                DOCS_COVERAGE_MANIFEST,
                f"feature {feature_id} must declare at least one technical doc",
            )
        )
    for rel in list(user_docs) + list(technical_docs):
        violations.extend(
            _check_feature_doc(feature_id, rel, docs_root_rel, docs_root, linked_slugs)
        )
    return violations


def check_documentation_coverage(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Require every major feature to carry user and technical documentation.

    The coverage manifest (``docs/adr/documentation-coverage.yaml``) is the
    source of truth, so the check validates the whole manifest on every run
    regardless of ``files`` (like ``check_adr_registry``). Each feature must
    declare at least one user doc and one technical doc; every referenced doc
    must exist as a serveable file under the in-app docs tree (not under a
    ``_deprecated``/hidden path) and be reachable from an ``index.md``.
    """
    # the manifest is the source of truth, so the check is not scoped to `files`
    del files
    manifest, load_violations = _load_coverage_manifest(repo_root)
    if manifest is None:
        return load_violations

    docs_root_rel = manifest["docs_root"]
    docs_root = repo_root / docs_root_rel
    linked_slugs = _collect_index_link_slugs(docs_root)

    violations: list[Violation] = []
    for feature in manifest["features"]:
        violations.extend(
            _check_feature_coverage(feature, docs_root_rel, docs_root, linked_slugs)
        )
    return violations


def _lilrae_violation(path: str, message: str) -> Violation:
    """Build a LilRAE/TechVault identity-boundary violation."""
    return Violation("lilrae-identity-boundary", LILRAE_IDENTITY_RULE_ID, path, message)


def _lilrae_candidates(repo_root: Path, files: list[str] | None) -> list[str]:
    """Return current prose plus the machine-readable ADR authority."""
    if files is not None:
        return sorted(
            {path for path in files if path.endswith(".md") or path == ADR_INDEX_PATH}
        )
    candidates = {
        path.relative_to(repo_root).as_posix()
        for path in repo_root.rglob("*.md")
        if ".git" not in path.relative_to(repo_root).parts
    }
    if (repo_root / ADR_INDEX_PATH).is_file():
        candidates.add(ADR_INDEX_PATH)
    return sorted(candidates)


def _adr024_registry_prose(repo_root: Path) -> str | None:
    """Return ADR-024's decision and R6 description from the registry."""
    try:
        registry = _load_json_yaml(repo_root / ADR_INDEX_PATH)
    except (OSError, ValueError):
        registry = None
    entry = (
        next(
            (
                item
                for item in registry
                if isinstance(item, dict) and item.get("id") == "ADR-024"
            ),
            None,
        )
        if isinstance(registry, list)
        else None
    )
    if isinstance(entry, dict):
        values = [entry.get("decision")]
        rules = entry.get("rules")
        if isinstance(rules, list):
            values.extend(
                rule.get("description")
                for rule in rules
                if isinstance(rule, dict) and rule.get("id") == LILRAE_IDENTITY_RULE_ID
            )
        return "\n".join(value for value in values if isinstance(value, str))
    return None


def _read_lilrae_candidate(repo_root: Path, rel: str) -> str | None:
    """Read a candidate document, deriving ADR-024 prose from the registry."""
    if rel == ADR_INDEX_PATH:
        return _adr024_registry_prose(repo_root)
    try:
        return (repo_root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _identity_boundary_message(rel: str, text: str) -> str | None:
    """Return the first prohibited LilRAE/APTL/TechVault identity claim."""
    if (
        rel == "CHANGELOG.md"
        or rel.startswith("changelog.d/")
        or rel == _LILRAE_IDENTITY_PREFLIGHT
    ):
        return None
    checks = (
        (
            _FALSE_TECHVAULT_PAIR,
            "TechVault/APTL or TechVault/LilRAE is a false pairing; TechVault is only a scenario pack",
        ),
        (
            _FALSE_IDENTITY_SPLIT,
            "APTL and LilRAE are one continuous identity across a rename",
        ),
        (
            _FALSE_APTL_HOST_RELATION,
            "APTL is the former name of LilRAE across a rename, not a LilRAE-hosted product, plugin, or experience",
        ),
        (
            _FALSE_TECHVAULT_ROLE,
            "TechVault is a scenario pack, not a product, experience, plugin, platform, or layer",
        ),
    )
    return next((message for pattern, message in checks if pattern.search(text)), None)


def _rename_continuity_message(rel: str, text: str) -> str | None:
    """Return a continuity error for current prose that omits the rename."""
    if (
        rel in _LILRAE_CURRENT_PROSE_FILES
        and "APTL" in text
        and "LilRAE (formerly APTL)" not in text
    ):
        return (
            "current conceptual APTL references must establish LilRAE rename continuity"
        )
    return None


def _retired_techvault_message(rel: str, text: str) -> str | None:
    """Return an error when retired TechVault evidence lacks its boundary note."""
    if rel not in _RETIRED_TECHVAULT_DOCS:
        return None
    normalized = re.sub(r"\s+", " ", re.sub(r"(?m)^>\s?", "", text))
    required = (
        _HISTORICAL_BOUNDARY_MARKER,
        "TechVault is a scenario pack",
        "APTL is the former name of LilRAE",
        "retired by the RAES hard cut",
    )
    if any(phrase not in normalized for phrase in required):
        return "retired TechVault implementation evidence must carry the canonical historical boundary"
    return None


def check_lilrae_identity_boundary(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Keep the LilRAE rename and TechVault scenario-pack boundary unambiguous.

    Release history and literal external identifiers remain factual. Current
    prose cannot split APTL from LilRAE or promote TechVault into a product or
    layer, while retired TechVault implementation notes carry an explicit
    historical boundary before their preserved paths, symbols, and commands.
    """
    violations: list[Violation] = []
    for rel in _lilrae_candidates(repo_root, files):
        text = _read_lilrae_candidate(repo_root, rel)
        if text is None:
            continue
        message = _identity_boundary_message(rel, text)
        if message is None:
            message = _rename_continuity_message(rel, text)
        if message is None:
            message = _retired_techvault_message(rel, text)
        if message is not None:
            violations.append(_lilrae_violation(rel, message))
    return violations
