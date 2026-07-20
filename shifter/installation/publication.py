"""Published, versioned backend-bundle contract artifact (issue #1323).

This module *publishes* the backend-bundle contract defined in
:mod:`installation.contract` and the bundles in :mod:`installation.registry` as a
committed, canonical JSON artifact that downstream backend-bundle authors and tooling can
build against without reading Shifter internals. The artifact is always *generated* from
the closed Pydantic models and deterministic registry data — it is never hand-maintained —
and CI checks it three ways (see :func:`check_publication`):

* **drift** — the committed artifact must equal the freshly generated one, so the published
  contract can never fall behind the code;
* **breaking change** — a backward-incompatible change to the contract shape (a removed
  field, a removed enum value, or a newly required field) is caught against the *frozen*
  per-version snapshot of the current contract version, and can only be resolved by bumping
  ``contract_version`` (which mints a new frozen snapshot) plus a migration note. The
  snapshots are immutable — ``export`` never overwrites one — so a change cannot refresh the
  reference it is meant to police;
* **registry conformance** — every published backend record validates, exactly as emitted,
  against the published JSON schema.

The backend ``contract_version`` (:data:`installation.contract.SUPPORTED_CONTRACT_VERSIONS`)
is the published version. It is independent of ``RootConfig.version`` and of the
``installation`` package version. Diagnostics are sanitized :class:`ConfigIssue` records —
they name fields, enum values, backend names, versions, and repository-relative artifact
paths, never secret values, raw config bodies, or absolute host paths. Constrained by
ADR-011.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import ValidationError

from ._schema_compat import find_incompatible_changes
from .contract import (
    _BACKEND_NAME_RE,
    _PROFILE_RE,
    _SECRET_NAME_RE,
    _SECRET_VALUE_DESTINATIONS,
    SUPPORTED_CONTRACT_VERSIONS,
    BackendBundle,
    OutputSensitivity,
)
from .errors import ConfigIssue
from .registry import BACKEND_BUNDLES

# Security constraints the base ``model_json_schema()`` omits because they live in custom
# Pydantic validators. These mirror the grammars in ``contract.py`` so the published schema
# rejects the same identifiers, command argv tokens, and repository paths the contract does.
# ``\w`` in the contract's executable regex is ASCII-flagged; spell it out here so the schema
# pattern (interpreted without that flag) stays ASCII-equivalent.
_EXECUTABLE_SCHEMA_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$"
# A structured-argv token: non-empty, no whitespace, no shell metacharacters, not an absolute
# path, no ``..`` path segment. Mirrors ``contract._validate_argv_token``. The ``TOKEN`` in the
# name trips the hardcoded-secret heuristics; this is a regex, not a credential.
_SAFE_ARGV_TOKEN_PATTERN = r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\s;&|`$<>]+$"  # noqa: S105 # nosec B105
# A repository-relative path: non-empty, no surrounding whitespace, not absolute, no ``..``
# segment. Mirrors ``contract._check_repo_relative`` + ``_check_non_empty``.
_REPO_RELATIVE_PATTERN = r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))\S(?:.*\S)?$"

#: The published contract version — the highest supported backend contract-shape version.
PUBLISHED_CONTRACT_VERSION: int = max(SUPPORTED_CONTRACT_VERSIONS)

#: Directory holding the committed published artifacts, relative to this package.
PUBLISHED_CONTRACT_DIR: Path = Path(__file__).resolve().parent / "published_contract"
#: The committed, generated contract artifact (kept in sync with the code by the drift gate).
ARTIFACT_PATH: Path = PUBLISHED_CONTRACT_DIR / "backend-bundle-contract.json"
#: The per-version migration notes / changelog for the published contract.
MIGRATIONS_PATH: Path = PUBLISHED_CONTRACT_DIR / "MIGRATIONS.md"

#: Frozen per-version snapshot filenames: ``backend-bundle-contract.v<N>.json``.
_SNAPSHOT_RE = re.compile(r"^backend-bundle-contract\.v(\d+)\.json$")

#: Repository root, used to render committed paths repo-relative in diagnostics.
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]


def version_snapshot_path(version: int, directory: Path = PUBLISHED_CONTRACT_DIR) -> Path:
    """Path of the frozen snapshot for ``version`` under ``directory``."""
    return directory / f"backend-bundle-contract.v{version}.json"


def _repo_rel(path: Path) -> str:
    """Render ``path`` repository-relative when possible, else by name (never an abs host path)."""
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return path.name


def _published_settings_schema(bundle: BackendBundle) -> dict[str, Any] | None:
    """The public JSON-schema form of a bundle's settings model, or ``None``.

    ``settings_model`` holds a Pydantic *class* — not serializable data — so the published
    bundle never carries it raw. When a bundle supplies a settings model its public form is
    that model's JSON schema; the provisional ``aws``/``gcp`` entries have no model, so this
    is ``None`` for them.
    """
    if bundle.settings_model is None:
        return None
    return bundle.settings_model.model_json_schema()


def published_backend_bundle_schema() -> dict[str, Any]:
    """The JSON schema describing the *published* backend record projection.

    This is the ``BackendBundle`` schema with the ``settings_model`` field (a Python class,
    not serializable) replaced by ``settings_schema`` (the model's JSON schema, or null). It
    therefore describes the records actually emitted in the artifact, so a downstream author
    can validate a candidate bundle against the published contract.
    """
    schema = BackendBundle.model_json_schema()
    properties = schema.get("properties", {})
    properties.pop("settings_model", None)
    properties["settings_schema"] = {
        "anyOf": [{"type": "object"}, {"type": "null"}],
        "default": None,
        "title": "Settings Schema",
        "description": "The backend's settings JSON schema, or null when the bundle declares no settings model.",
    }
    _inject_security_constraints(schema)
    return schema


def _inject_security_constraints(schema: dict[str, Any]) -> None:
    """Encode the security-relevant contract validators the base JSON schema omits.

    ``model_json_schema()`` does not render the custom Pydantic validators, so the raw schema
    would accept identifiers, command argv, repository paths, and secret-value placements the
    contract rejects. This layers on the JSON-Schema-expressible invariants: identifier
    grammars, safe argv tokens (executable at argv[0]), repository-relative owned paths, the
    supported contract versions, and the secret-value destination rule. The cross-collection
    invariants JSON Schema cannot express (unique names, each validation check's executable
    listed in required_tools) remain enforced by :func:`validate_published_bundle`.
    """
    props = schema["properties"]
    props["name"]["pattern"] = _BACKEND_NAME_RE.pattern
    props["contract_version"]["enum"] = sorted(SUPPORTED_CONTRACT_VERSIONS)
    props["supported_profiles"]["items"]["pattern"] = _PROFILE_RE.pattern
    props["docs"]["items"]["pattern"] = _REPO_RELATIVE_PATTERN
    defs = schema["$defs"]
    defs["RequiredTool"]["properties"]["name"]["pattern"] = _EXECUTABLE_SCHEMA_PATTERN
    defs["RequiredSecret"]["properties"]["logical_name"]["pattern"] = _SECRET_NAME_RE.pattern
    argv = defs["CommandSpec"]["properties"]["argv"]
    # minItems: 1 is required — prefixItems only constrains argv[0] when it exists, so without
    # it a standalone validator would accept an empty argv the contract rejects.
    argv["minItems"] = 1
    argv["prefixItems"] = [{"type": "string", "pattern": _EXECUTABLE_SCHEMA_PATTERN}]
    argv["items"] = {"type": "string", "pattern": _SAFE_ARGV_TOKEN_PATTERN}
    for key in ("infrastructure", "kubernetes", "scripts", "workflows", "examples", "docs"):
        defs["OwnedFiles"]["properties"][key]["items"]["pattern"] = _REPO_RELATIVE_PATTERN
    allowed = sorted(dest.value for dest in _SECRET_VALUE_DESTINATIONS)
    defs["GeneratedOutput"].setdefault("allOf", []).append(
        {
            "if": {
                "properties": {"sensitivity": {"const": OutputSensitivity.SECRET_VALUE.value}},
                "required": ["sensitivity"],
            },
            "then": {"properties": {"destination": {"enum": allowed}}},
        }
    )


def _published_bundle(bundle: BackendBundle) -> dict[str, Any]:
    """A deterministic, public dict form of one backend bundle (matching the published schema)."""
    # ``settings_model`` holds a Pydantic class, which is not JSON-serializable, so it is
    # excluded from the dump and replaced by its public JSON-schema form below — the published
    # artifact carries data, never a runtime type reference.
    data = bundle.model_dump(mode="json", exclude={"settings_model"})
    data["settings_schema"] = _published_settings_schema(bundle)
    # Frozenset fields dump to lists in nondeterministic order — sort for a stable artifact.
    data["supported_profiles"] = sorted(data["supported_profiles"])
    data["capabilities"] = sorted(data["capabilities"])
    return data


def build_contract_artifact(bundles: Mapping[str, BackendBundle] | None = None) -> dict[str, Any]:
    """Build the published contract artifact from the contract models and registry.

    ``bundles`` defaults to the production registry
    (:data:`installation.registry.BACKEND_BUNDLES`); it is a parameter only so tests can
    build an artifact from a controlled bundle set. The result is a plain dict; serialize it
    with :func:`serialize_artifact` for the canonical committed form.
    """
    source = BACKEND_BUNDLES if bundles is None else bundles
    return {
        "contract_version": PUBLISHED_CONTRACT_VERSION,
        "supported_contract_versions": sorted(SUPPORTED_CONTRACT_VERSIONS),
        "backend_bundle_schema": published_backend_bundle_schema(),
        "backends": {name: _published_bundle(bundle) for name, bundle in sorted(source.items())},
    }


def serialize_artifact(artifact: Mapping[str, Any]) -> str:
    """Serialize an artifact to canonical JSON: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _has_migration_note(migrations_path: Path, version: int) -> bool:
    """Whether ``MIGRATIONS.md`` carries a ``## Contract version <version>`` section."""
    if not migrations_path.exists():
        return False
    pattern = re.compile(rf"^##\s+Contract version {version}\b", re.IGNORECASE | re.MULTILINE)
    return pattern.search(migrations_path.read_text(encoding="utf-8")) is not None


def frozen_snapshots(directory: Path = PUBLISHED_CONTRACT_DIR) -> dict[int, Path]:
    """Map contract version -> frozen snapshot path for every ``backend-bundle-contract.v<N>.json``."""
    snapshots: dict[int, Path] = {}
    if not directory.exists():
        return snapshots
    for path in directory.iterdir():
        match = _SNAPSHOT_RE.match(path.name)
        if match:
            snapshots[int(match.group(1))] = path
    return snapshots


def _drift_issues(generated_text: str, artifact_path: Path) -> list[ConfigIssue]:
    """Report when the committed artifact is missing or out of date with the generated one."""
    if not artifact_path.exists():
        return [
            ConfigIssue(
                _repo_rel(artifact_path), "published contract artifact is missing; run 'shifter-config contract export'"
            )
        ]
    if artifact_path.read_text(encoding="utf-8") != generated_text:
        return [
            ConfigIssue(
                _repo_rel(artifact_path),
                "published contract artifact is out of date with the code; "
                "regenerate with 'shifter-config contract export'",
            )
        ]
    return []


def _compatibility_issues(generated: Mapping[str, Any], contract_dir: Path, migrations_path: Path) -> list[ConfigIssue]:
    """Enforce version compatibility against the immutable frozen snapshots."""
    issues: list[ConfigIssue] = []
    snapshots = frozen_snapshots(contract_dir)

    # Every frozen version must carry a migration note so the changelog stays complete.
    for version in sorted(snapshots):
        if not _has_migration_note(migrations_path, version):
            issues.append(
                ConfigIssue(
                    _repo_rel(migrations_path),
                    f"contract version {version} has a frozen snapshot but no "
                    f"'## Contract version {version}' migration note",
                )
            )

    current = generated.get("contract_version")
    snapshot_path = snapshots.get(current) if isinstance(current, int) else None
    if snapshot_path is None:
        issues.append(
            ConfigIssue(
                _repo_rel(version_snapshot_path(current if isinstance(current, int) else 0, contract_dir)),
                f"no frozen snapshot for contract version {current}; run 'shifter-config contract export' to create it",
            )
        )
        return issues

    frozen = json.loads(snapshot_path.read_text(encoding="utf-8"))
    breaking = _surface_incompatibilities(frozen, generated)
    if breaking:
        issues.append(
            ConfigIssue(
                _repo_rel(snapshot_path),
                f"backward-incompatible change to published contract version {current} ({'; '.join(breaking)}); "
                "bump contract_version, add a '## Contract version <new>' migration note, and export to mint the new "
                "frozen snapshot",
            )
        )
    return issues


def _surface_incompatibilities(frozen: Mapping[str, Any], generated: Mapping[str, Any]) -> list[str]:
    """Backward-incompatible changes across the whole published validation surface.

    Compares the ``BackendBundle`` schema and every published backend's ``settings_schema``,
    and flags a removed backend, so an incompatible change anywhere consumers validate
    against is caught, not just the top-level bundle schema.
    """
    breaking = find_incompatible_changes(
        frozen.get("backend_bundle_schema") or {}, generated.get("backend_bundle_schema") or {}
    )
    frozen_backends = frozen.get("backends") or {}
    generated_backends = generated.get("backends") or {}
    for name in sorted(set(frozen_backends) - set(generated_backends)):
        breaking.append(f"backends.{name}: published backend removed")
    for name in sorted(set(frozen_backends) & set(generated_backends)):
        old_settings = frozen_backends[name].get("settings_schema")
        new_settings = generated_backends[name].get("settings_schema")
        if isinstance(old_settings, Mapping) and isinstance(new_settings, Mapping):
            breaking.extend(
                f"backends.{name}.settings_schema {change}"
                for change in find_incompatible_changes(old_settings, new_settings)
            )
        elif old_settings is not None and new_settings is None:
            breaking.append(f"backends.{name}.settings_schema: removed")
    return breaking


def _registry_conformance_issues(generated: Mapping[str, Any]) -> list[ConfigIssue]:
    """Every published backend record must validate, exactly as emitted, against the published schema."""
    issues: list[ConfigIssue] = []
    validator = jsonschema.Draft202012Validator(generated.get("backend_bundle_schema") or {})
    supported = set(generated.get("supported_contract_versions") or [])
    for name, record in sorted((generated.get("backends") or {}).items()):
        errors = sorted(validator.iter_errors(record), key=lambda err: list(err.absolute_path))
        if errors:
            # ``json_path`` names the failing location without echoing the (public) instance value.
            issues.append(
                ConfigIssue(
                    f"backends.{name}",
                    f"published bundle does not validate against the published schema at {errors[0].json_path}",
                )
            )
            continue
        if record.get("contract_version") not in supported:
            issues.append(
                ConfigIssue(
                    f"backends.{name}",
                    f"declares contract_version {record.get('contract_version')}, "
                    "which is not a published supported version",
                )
            )
    return issues


def check_publication(
    *,
    bundles: Mapping[str, BackendBundle] | None = None,
    artifact_path: Path = ARTIFACT_PATH,
    contract_dir: Path = PUBLISHED_CONTRACT_DIR,
    migrations_path: Path = MIGRATIONS_PATH,
) -> list[ConfigIssue]:
    """Run the drift, breaking-change, and registry-conformance checks.

    Returns a list of sanitized :class:`~installation.errors.ConfigIssue` records — an empty
    list means the published contract is current, backward-compatible, and conformant. The
    function never raises for a *check* failure (it reports it as an issue); only unexpected
    I/O errors propagate. Paths are parameters so tests can exercise the checks against a
    controlled artifact/snapshot set.
    """
    generated = build_contract_artifact(bundles)
    generated_text = serialize_artifact(generated)
    return [
        *_drift_issues(generated_text, artifact_path),
        *_compatibility_issues(generated, contract_dir, migrations_path),
        *_registry_conformance_issues(generated),
    ]


def validate_published_bundle(record: Mapping[str, Any]) -> list[ConfigIssue]:
    """Validate a candidate backend-bundle record against the full published contract.

    This is the **authoritative, parity-complete** public validation surface (issue #1323): a
    downstream backend-bundle author validates their candidate record here and cannot pass a
    bundle that the internal ``BackendBundle`` contract would reject. It enforces the published
    JSON schema (shape, identifier grammars, safe argv tokens, repository-relative paths, the
    secret-value destination rule) **and** re-runs the full ``BackendBundle`` validators —
    including the cross-collection invariants JSON Schema cannot express (unique record names,
    each validation check's executable listed in ``required_tools``). Returns sanitized
    :class:`~installation.errors.ConfigIssue` records; an empty list means the record is a
    valid published bundle. Diagnostics name locations, never rejected input values.
    """
    issues: list[ConfigIssue] = []
    candidate = dict(record)
    validator = jsonschema.Draft202012Validator(published_backend_bundle_schema())
    for error in sorted(validator.iter_errors(candidate), key=lambda err: list(err.absolute_path)):
        issues.append(ConfigIssue(error.json_path, "does not satisfy the published contract schema"))
    # Re-run the full contract, which owns the invariants JSON Schema cannot express. The
    # published record carries ``settings_schema`` (the settings model's public JSON schema);
    # it is not a ``BackendBundle`` field, so drop it before re-validating the bundle shape.
    try:
        BackendBundle.model_validate({key: value for key, value in candidate.items() if key != "settings_schema"})
    except ValidationError:
        if not issues:
            issues.append(ConfigIssue("<bundle>", "does not satisfy the backend-bundle contract invariants"))
    return issues
