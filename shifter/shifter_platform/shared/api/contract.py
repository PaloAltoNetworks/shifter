"""Generation, canonicalization, and drift checking for the committed
``/api/v1/`` OpenAPI contract (#1329, ADR-040).

The runtime DRF routes, serializers, permissions, and drf-spectacular
annotations remain the authoring source. This module renders that source into
the single committed publication artifact and provides the deterministic
regenerate-and-compare used by the CI drift gate. It is the one place that owns
the artifact path and canonical formatting so the committed file, the SPA type
generation, and the drift check never disagree on bytes.
"""

from __future__ import annotations

import difflib
import io
import json
import shutil
import subprocess  # nosec B404 - fixed argv, no shell; read-only git and pinned oasdiff only  # NOSONAR
import tempfile
from pathlib import Path
from typing import Any

from django.core.management import call_command

# The published API major. Version-keyed so ``/api/v2/`` can be published beside
# ``/api/v1/`` by selecting another artifact without copying this module.
API_MAJOR = "v1"

# ``shared/api/contract.py`` -> ``shared/api`` -> ``shared`` -> app root.
_APP_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = _APP_ROOT / "openapi"

# Max unified-diff lines surfaced by the drift gate. Keeps CI output bounded and
# never dumps the whole artifact (preflight: bounded diagnostics).
_MAX_DIFF_LINES = 60

# Fixed name of the pinned OpenAPI-aware compatibility checker, resolved from
# PATH. Not caller-configurable: the binary is provisioned by CI (ADR-037 pin +
# checksum) so no external/untrusted value ever reaches the subprocess argv.
_OASDIFF_BIN = "oasdiff"


def artifact_path(major: str = API_MAJOR) -> Path:
    """Return the committed artifact path for an API major."""
    return ARTIFACT_DIR / f"{major}.json"


def retirement_path(major: str = API_MAJOR) -> Path:
    """Return the accepted whole-feature retirement metadata for an API major."""
    return ARTIFACT_DIR / f"{major}.retirements.json"


def _read_retirements(path: Path, major: str) -> list[dict[str, Any]]:
    """Load and validate the retirement list for the requested API major."""
    metadata = json.loads(path.read_text(encoding="utf-8"))
    retirements = metadata.get("retirements")
    if metadata.get("api_major") != major or not isinstance(retirements, list) or not retirements:
        raise RuntimeError(f"Invalid API retirement metadata: {path}")
    if any(not _has_valid_retirement_header(retirement) for retirement in retirements):
        raise RuntimeError(f"Invalid API retirement metadata: {path}")
    return retirements


def _has_valid_retirement_header(retirement: object) -> bool:
    """Return whether a retirement entry has its required audit identity."""
    if not isinstance(retirement, dict) or not retirement.get("adr"):
        return False
    issue = retirement.get("issue")
    return isinstance(issue, int) and issue > 0


def _remove_retired_path(base: dict[str, Any], current: dict[str, Any], retired_path: str) -> None:
    """Remove one retired path unless the current contract reintroduced it."""
    if retired_path in current.get("paths", {}):
        raise RuntimeError(f"Retired API path was reintroduced: {retired_path}")
    base.get("paths", {}).pop(retired_path, None)


def _remove_retired_property(
    base: dict[str, Any],
    current: dict[str, Any],
    retired_property: dict[str, str],
) -> None:
    """Remove one retired response field unless the current contract restored it."""
    schema_name = retired_property["schema"]
    property_name = retired_property["property"]
    current_schema = current.get("components", {}).get("schemas", {}).get(schema_name, {})
    if property_name in current_schema.get("properties", {}):
        raise RuntimeError(f"Retired API response property was reintroduced: {schema_name}.{property_name}")

    base_schema = base.get("components", {}).get("schemas", {}).get(schema_name, {})
    base_schema.get("properties", {}).pop(property_name, None)
    if property_name in base_schema.get("required", []):
        base_schema["required"].remove(property_name)


def _apply_retirement(base: dict[str, Any], current: dict[str, Any], retirement: dict[str, Any]) -> None:
    """Project every exact path and response field in one retirement record."""
    for retired_path in retirement.get("paths", []):
        _remove_retired_path(base, current, retired_path)
    for retired_property in retirement.get("response_schema_properties", []):
        _remove_retired_property(base, current, retired_property)


def apply_accepted_retirements(base_text: str, current_text: str, major: str = API_MAJOR) -> str:
    """Project accepted whole-feature retirements out of the trusted baseline.

    Ordinary breaking changes still go through oasdiff unchanged. This narrow
    projection exists for the ADR-040 carve-out where a separately accepted ADR
    removes a complete product instead of preserving it under another API
    major. Every path and response property is exact and must be absent from the
    current runtime contract; metadata cannot waive unrelated changes or hide a
    reintroduced surface.
    """
    path = retirement_path(major)
    if not path.exists():
        return base_text

    retirements = _read_retirements(path, major)
    base: dict[str, Any] = json.loads(base_text)
    current: dict[str, Any] = json.loads(current_text)
    for retirement in retirements:
        _apply_retirement(base, current, retirement)

    return _canonicalize(base)


def generate_openapi_document() -> str:
    """Return the canonical committed-artifact text for the ``/api/v1/`` surface.

    Generation runs drf-spectacular with validation and fail-on-warn, so an
    unresolved serializer, operation-id collision, schema warning, or invalid
    document raises rather than producing a graceful-fallback artifact.
    """
    buffer = io.StringIO()
    call_command(
        "spectacular",
        format="openapi-json",
        validate=True,
        fail_on_warn=True,
        stdout=buffer,
    )
    document: dict[str, Any] = json.loads(buffer.getvalue())
    return _canonicalize(document)


def _canonicalize(document: dict[str, Any]) -> str:
    """Render an OpenAPI document to stable, review-friendly JSON.

    drf-spectacular emits keys in a deterministic order already; re-dumping with
    a fixed indent, non-escaped unicode, and a trailing newline pins the exact
    bytes the drift gate compares and keeps the end-of-file-fixer hook a no-op.
    """
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_artifact(major: str = API_MAJOR) -> Path:
    """Regenerate and write the committed OpenAPI artifact. Returns its path."""
    path = artifact_path(major)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_openapi_document(), encoding="utf-8")
    return path


def check_drift(major: str = API_MAJOR) -> tuple[bool, str]:
    """Compare a fresh generation against the committed artifact.

    Returns ``(is_current, detail)``. ``detail`` is empty on success and a
    bounded unified diff (or a missing-file message) on drift.
    """
    path = artifact_path(major)
    if not path.exists():
        return False, f"Committed artifact is missing: {path}. Run `manage.py api_contract`."
    current = generate_openapi_document()
    committed = path.read_text(encoding="utf-8")
    if current == committed:
        return True, ""
    diff = difflib.unified_diff(
        committed.splitlines(),
        current.splitlines(),
        fromfile=f"committed:{path.name}",
        tofile="regenerated",
        lineterm="",
    )
    lines = list(diff)
    detail = "\n".join(lines[:_MAX_DIFF_LINES])
    if len(lines) > _MAX_DIFF_LINES:
        detail += f"\n... ({len(lines) - _MAX_DIFF_LINES} more diff lines truncated)"
    return False, detail


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a read-only git command (defaults to the artifact directory)."""
    git = shutil.which("git") or "git"
    return subprocess.run(  # noqa: S603  # nosec B603 - fixed argv, no shell; read-only git
        [git, *args],
        cwd=cwd or ARTIFACT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def resolve_base_document(base_ref: str, major: str = API_MAJOR) -> str | None:
    """Return the committed artifact text from ``base_ref`` (trusted history).

    Reads the artifact from the base branch via ``git show`` so the
    breaking-change comparison uses the already-published contract, never a
    baseline the current PR can rewrite.

    Fails closed: an unresolvable base ref or an unreadable artifact object
    raises, so a broken baseline lookup can never silently let a breaking change
    through. Returns ``None`` ONLY when the base ref resolves but genuinely has no
    committed artifact (the legitimate first-publication case).
    """
    toplevel_result = _git("rev-parse", "--show-toplevel")
    if toplevel_result.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {toplevel_result.stderr.strip()}")
    toplevel = Path(toplevel_result.stdout.strip())
    # Path-scoped git commands run from the repo root so the repo-relative
    # pathspec (ls-tree) and the ``<ref>:<path>`` lookup (git show) resolve
    # consistently regardless of where the process was launched.
    repo_relative = artifact_path(major).relative_to(toplevel).as_posix()
    # The base ref itself must resolve; if it does not, fail rather than skip.
    resolved = _git("rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}")
    if resolved.returncode != 0:
        raise RuntimeError(f"base ref {base_ref!r} could not be resolved for the breaking-change gate")
    # Discriminate "path genuinely absent" from "lookup failed": ls-tree exits 0
    # for a resolvable ref and prints a tree entry only when the path exists. A
    # nonzero status is an error and must fail closed, never skip the gate.
    listed = _git("ls-tree", base_ref, "--", repo_relative, cwd=toplevel)
    if listed.returncode != 0:
        raise RuntimeError(f"failed to query {repo_relative} at {base_ref}: {listed.stderr.strip()}")
    if not listed.stdout.strip():
        # Ref resolves but has no committed artifact — the legitimate first-publication skip.
        return None
    shown = _git("show", f"{base_ref}:{repo_relative}", cwd=toplevel)
    if shown.returncode != 0:
        raise RuntimeError(f"failed to read {repo_relative} at {base_ref}: {shown.stderr.strip()}")
    return shown.stdout


def check_breaking_changes(base_text: str, current_text: str) -> tuple[bool, str]:
    """Compare two OpenAPI documents for consumer-breaking changes via oasdiff.

    Returns ``(is_compatible, detail)``. ``oasdiff breaking --fail-on ERR`` exits
    non-zero when it finds a breaking change; the OpenAPI-aware semantics live in
    oasdiff, not in this wrapper. An ordinary breaking change to ``/api/v1/``
    must ship as a parallel ``/api/v2/`` with a migration note; a complete
    product retirement requires accepted retirement metadata (ADR-040).
    """
    binary = shutil.which(_OASDIFF_BIN) or _OASDIFF_BIN
    with tempfile.TemporaryDirectory() as tmp:
        # Fixed, literal file names under a private temp dir — the paths never
        # derive from the document contents; only trusted OpenAPI JSON is written
        # through the open file handle.
        base_file = Path(tmp) / "base.json"
        revision_file = Path(tmp) / "revision.json"
        with base_file.open("w", encoding="utf-8") as handle:
            handle.write(base_text)
        with revision_file.open("w", encoding="utf-8") as handle:
            handle.write(current_text)
        result = subprocess.run(  # noqa: S603  # nosec B603 - fixed argv, no shell; pinned oasdiff binary
            [binary, "breaking", str(base_file), str(revision_file), "--fail-on", "ERR"],
            capture_output=True,
            text=True,
            check=False,
        )
    detail = (result.stdout + result.stderr).strip()
    return result.returncode == 0, detail


def check_breaking_against(base_ref: str, major: str = API_MAJOR) -> tuple[bool, str]:
    """Run the breaking-change gate for the committed artifact against ``base_ref``.

    Returns ``(ok, detail)``. When the base ref has no committed artifact the gate
    passes (a newly published major has no prior consumer to break).
    """
    base_text = resolve_base_document(base_ref, major)
    if base_text is None:
        return True, f"No committed artifact on {base_ref}; new API major, breaking-change gate skipped."
    path = artifact_path(major)
    if not path.exists():
        return False, f"Committed artifact is missing: {path}. Run `manage.py api_contract`."
    current_text = path.read_text(encoding="utf-8")
    projected_base = apply_accepted_retirements(base_text, current_text, major)
    return check_breaking_changes(projected_base, current_text)
