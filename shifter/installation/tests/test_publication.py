"""Tests for the published backend-bundle contract artifact and its gates (#1323).

These cover the three CI gates — drift, breaking change, and registry conformance — plus
the artifact generator, canonical serializer, projected schema, compatibility differ, and
the ``shifter-config contract`` CLI. The gates are behavioral: each would go red if the
enforcement it protects were removed or weakened.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from installation import cli
from installation.contract import (
    SUPPORTED_CONTRACT_VERSIONS,
    BackendBundle,
    BackendMaturity,
)
from installation.errors import ConfigIssue
from installation.publication import (
    ARTIFACT_PATH,
    MIGRATIONS_PATH,
    PUBLISHED_CONTRACT_VERSION,
    _compatibility_issues,
    _published_bundle,
    _registry_conformance_issues,
    _surface_incompatibilities,
    build_contract_artifact,
    check_publication,
    find_incompatible_changes,
    frozen_snapshots,
    published_backend_bundle_schema,
    serialize_artifact,
    validate_published_bundle,
    version_snapshot_path,
)
from installation.registry import BACKEND_BUNDLES

# --------------------------------------------------------------------------------------
# Artifact generation, projected schema, and canonical serialization
# --------------------------------------------------------------------------------------


def test_build_artifact_shape() -> None:
    artifact = build_contract_artifact()
    assert set(artifact) == {"contract_version", "supported_contract_versions", "backend_bundle_schema", "backends"}
    assert artifact["contract_version"] == PUBLISHED_CONTRACT_VERSION == max(SUPPORTED_CONTRACT_VERSIONS)
    assert artifact["supported_contract_versions"] == sorted(SUPPORTED_CONTRACT_VERSIONS)
    assert set(artifact["backends"]) == set(BACKEND_BUNDLES)


def test_published_schema_describes_the_projected_records() -> None:
    props = published_backend_bundle_schema()["properties"]
    # The published schema describes the projection actually emitted: no ``settings_model``
    # Python-class field, and a ``settings_schema`` field instead.
    assert "settings_model" not in props
    assert "settings_schema" in props


def test_published_records_validate_against_published_schema() -> None:
    """Every emitted backend record validates, exactly as emitted, against the published schema."""
    artifact = build_contract_artifact()
    validator = jsonschema.Draft202012Validator(artifact["backend_bundle_schema"])
    for name, record in artifact["backends"].items():
        assert list(validator.iter_errors(record)) == [], name


def test_published_bundle_drops_settings_model_class() -> None:
    backends = build_contract_artifact()["backends"]
    aws = backends["aws"]
    # The Python class is never serialized; it is projected to ``settings_schema``.
    assert "settings_model" not in aws
    # AWS is migrated (#728): its closed settings model publishes as a JSON schema object.
    assert isinstance(aws["settings_schema"], dict)
    assert "region" in aws["settings_schema"].get("properties", {})
    # GCP is migrated too (#729): its closed settings model publishes as a JSON schema object.
    gcp = backends["gcp"]
    assert "settings_model" not in gcp
    assert isinstance(gcp["settings_schema"], dict)
    assert {"project_id", "region"} <= set(gcp["settings_schema"].get("properties", {}))
    assert aws["supported_profiles"] == sorted(aws["supported_profiles"])
    assert aws["capabilities"] == sorted(aws["capabilities"])


def test_published_aws_settings_schema_enforces_the_region_grammar() -> None:
    # #728: the runtime region grammar (AwsSettings) must also be expressed in the
    # *published* schema. If it were enforced only by a @field_validator, the published
    # artifact would permit any string and a downstream consumer validating against it
    # would accept a region that load_root_config rejects (boundary-contract gap).
    settings_schema = build_contract_artifact()["backends"]["aws"]["settings_schema"]
    validator = jsonschema.Draft202012Validator(settings_schema)
    assert list(validator.iter_errors({"region": "us-east-2"})) == []
    # The same malformed region the runtime rejects must fail against the published schema.
    assert list(validator.iter_errors({"region": "US_EAST_2"}))


def test_published_bundle_emits_settings_schema_when_model_present() -> None:
    class _Settings(BaseModel):
        model_config = ConfigDict(extra="forbid")

        region: str

    bundle = BackendBundle(
        contract_version=PUBLISHED_CONTRACT_VERSION,
        name="demo",
        title="Demo backend",
        maturity=BackendMaturity.EXPERIMENTAL,
        description="A demo backend with a settings model.",
        supported_profiles=frozenset({"dev"}),
        settings_model=_Settings,
    )
    published = _published_bundle(bundle)
    assert "settings_model" not in published
    assert published["settings_schema"] == _Settings.model_json_schema()


def test_build_artifact_accepts_custom_bundles() -> None:
    subset = {"aws": BACKEND_BUNDLES["aws"]}
    assert set(build_contract_artifact(subset)["backends"]) == {"aws"}


def test_serialize_artifact_is_canonical() -> None:
    assert serialize_artifact({"b": 2, "a": 1}) == '{\n  "a": 1,\n  "b": 2\n}\n'


def test_artifact_generation_is_deterministic() -> None:
    # Comparing two calls in one process is a weak check (fixed hash seed). Also assert the
    # sortedness invariant on every backend's frozenset-derived fields, which is what actually
    # protects cross-process/CI stability of the committed artifact: drop the sorts and this
    # goes red because frozenset iteration order is not guaranteed sorted.
    artifact = build_contract_artifact()
    assert serialize_artifact(artifact) == serialize_artifact(build_contract_artifact())
    for name, record in artifact["backends"].items():
        assert record["supported_profiles"] == sorted(record["supported_profiles"]), name
        assert record["capabilities"] == sorted(record["capabilities"]), name


# --------------------------------------------------------------------------------------
# Compatibility differ (recursive, over the full schema surface)
# --------------------------------------------------------------------------------------


def _schema(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    enum: list[str] | None = None,
) -> dict[str, Any]:
    """An object schema whose ``colour`` property references a ``$defs`` enum."""
    props = {"name": {"type": "string"}, "title": {"type": "string"}, "colour": {"$ref": "#/$defs/Colour"}}
    props.update(properties or {})
    return {
        "title": "BackendBundle",
        "type": "object",
        "properties": props,
        "required": required if required is not None else ["name"],
        "additionalProperties": False,
        "$defs": {"Colour": {"enum": enum if enum is not None else ["red", "green"]}},
    }


BASE_SCHEMA = _schema()


def test_no_incompatible_changes_when_identical() -> None:
    assert find_incompatible_changes(BASE_SCHEMA, BASE_SCHEMA) == []


def test_additive_changes_are_compatible() -> None:
    additive = _schema(properties={"extra": {"type": "string"}}, enum=["red", "green", "blue"])
    assert find_incompatible_changes(BASE_SCHEMA, additive) == []


def test_removed_property_is_incompatible() -> None:
    changed = _schema()
    del changed["properties"]["title"]
    assert any("title: property removed" in c for c in find_incompatible_changes(BASE_SCHEMA, changed))


def test_removed_enum_value_is_incompatible_through_a_ref() -> None:
    changed = _schema(enum=["red"])
    assert any("enum value 'green' removed" in c for c in find_incompatible_changes(BASE_SCHEMA, changed))


def test_newly_required_property_is_incompatible() -> None:
    changed = _schema(required=["name", "title"])
    assert any("title: newly required" in c for c in find_incompatible_changes(BASE_SCHEMA, changed))


def test_narrowed_type_is_incompatible() -> None:
    changed = _schema(properties={"name": {"type": "integer"}})
    assert any("type(s) ['string'] no longer accepted" in c for c in find_incompatible_changes(BASE_SCHEMA, changed))


def test_tightened_constraint_is_incompatible() -> None:
    changed = _schema(properties={"name": {"type": "string", "minLength": 1}})
    assert any("minLength tightened" in c for c in find_incompatible_changes(BASE_SCHEMA, changed))


def test_additional_properties_restriction_is_incompatible() -> None:
    old = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": True}
    new = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    assert any("additionalProperties restricted to false" in c for c in find_incompatible_changes(old, new))


def test_anyof_narrowing_is_incompatible() -> None:
    old = {"properties": {"x": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    new = {"properties": {"x": {"anyOf": [{"type": "string"}]}}}
    assert any("anyOf narrowed" in c for c in find_incompatible_changes(old, new))


def test_array_items_narrowing_is_incompatible() -> None:
    old = {"properties": {"tags": {"type": "array", "items": {"type": "string"}}}}
    new = {"properties": {"tags": {"type": "array", "items": {"type": "integer"}}}}
    changes = find_incompatible_changes(old, new)
    assert any("tags.items" in c and "no longer accepted" in c for c in changes)


def _narrow(old_field: Any, new_field: Any) -> list[str]:
    return find_incompatible_changes({"properties": {"x": old_field}}, {"properties": {"x": new_field}})


def test_differ_covers_narrowing_variants() -> None:
    assert any("type restricted" in c for c in _narrow({}, {"type": "string"}))
    assert any("values restricted to a fixed enum" in c for c in _narrow({}, {"enum": ["a"]}))
    assert any("maxLength tightened" in c for c in _narrow({"type": "string"}, {"type": "string", "maxLength": 5}))
    assert any("pattern tightened" in c for c in _narrow({"type": "string"}, {"type": "string", "pattern": "^a"}))
    assert any("multipleOf tightened" in c for c in _narrow({"type": "number"}, {"type": "number", "multipleOf": 2}))
    assert any(
        "uniqueItems now required" in c for c in _narrow({"type": "array"}, {"type": "array", "uniqueItems": True})
    )
    # additionalProperties schema narrowing recurses.
    ap = find_incompatible_changes(
        {"additionalProperties": {"type": "string"}}, {"additionalProperties": {"type": "integer"}}
    )
    assert any("additionalProperties" in c and "no longer accepted" in c for c in ap)
    # Non-mapping subschemas (boolean schemas) are skipped without error.
    assert find_incompatible_changes({"properties": {"x": True}}, {"properties": {"x": True}}) == []


def test_allof_semantics_are_correct() -> None:
    old = {"allOf": [{"type": "string"}]}
    new = {"allOf": [{"type": "string"}, {"minLength": 1}]}
    # Adding an allOf branch narrows (more constraints must all hold) -> break.
    assert any("allOf narrowed" in c for c in find_incompatible_changes(old, new))
    # Removing an allOf branch widens -> compatible (this was the inverted-logic bug).
    assert find_incompatible_changes(new, old) == []


def test_const_change_is_incompatible() -> None:
    assert any("const" in c for c in _narrow({"const": "a"}, {"const": "b"}))
    assert any("const" in c for c in _narrow({}, {"const": "a"}))


def test_boolean_subschema_narrowing() -> None:
    assert any("rejects all values" in c for c in _narrow(True, False))
    assert _narrow(False, True) == []
    assert _narrow({"type": "string"}, True) == []
    assert any("type restricted" in c for c in _narrow(True, {"type": "string"}))


def test_additional_properties_true_to_schema_is_incompatible() -> None:
    old = {"type": "object", "additionalProperties": True}
    new = {"type": "object", "additionalProperties": {"type": "string"}}
    assert any("additionalProperties restricted to a schema" in c for c in find_incompatible_changes(old, new))


def test_not_constraint_added_is_incompatible() -> None:
    assert any("'not' constraint" in c for c in _narrow({"type": "string"}, {"type": "string", "not": {"const": "x"}}))


def test_unrecognized_keyword_change_fails_closed() -> None:
    old = {"type": "object", "dependentRequired": {"a": ["b"]}}
    new = {"type": "object", "dependentRequired": {"a": ["b", "c"]}}
    assert any("unrecognized validation keyword 'dependentRequired'" in c for c in find_incompatible_changes(old, new))


def test_annotation_only_change_is_compatible() -> None:
    old = {"type": "string", "description": "old", "default": "a"}
    new = {"type": "string", "description": "new", "title": "X", "examples": ["a"]}
    assert find_incompatible_changes(old, new) == []


def test_prefix_items_narrowing_is_incompatible() -> None:
    old = {"type": "array", "prefixItems": [{"type": "string"}]}
    new = {"type": "array", "prefixItems": [{"type": "string"}, {"type": "integer"}]}
    assert any("prefixItems added positional constraints" in c for c in find_incompatible_changes(old, new))


def test_added_branch_and_array_constraints_are_incompatible() -> None:
    # Adding a branch/array keyword to a previously unconstrained schema narrows it, and the
    # keyword being in the handled set must not let the transition slip past the gate.
    assert any("anyOf constraint added" in c for c in _narrow({}, {"anyOf": [{"type": "string"}]}))
    assert any("oneOf constraint added" in c for c in _narrow({}, {"oneOf": [{"type": "string"}]}))
    assert any("allOf constraint added" in c for c in _narrow({}, {"allOf": [{"type": "string"}]}))
    assert any(
        "items constraint added" in c
        for c in _narrow({"type": "array"}, {"type": "array", "items": {"type": "string"}})
    )
    assert any(
        "prefixItems constraint added" in c
        for c in _narrow({"type": "array"}, {"type": "array", "prefixItems": [{"type": "string"}]})
    )


def test_non_mapping_subschema_is_ignored() -> None:
    assert _narrow({"type": "string"}, "not-a-schema") == []


def test_deep_nesting_is_bounded() -> None:
    def _nest(levels: int) -> dict[str, Any]:
        node: dict[str, Any] = {"type": "integer"}
        for _ in range(levels):
            node = {"type": "object", "properties": {"c": node}}
        return node

    # Nested well past the recursion cap; the differ must terminate without error.
    assert find_incompatible_changes(_nest(70), _nest(70)) == []


# --------------------------------------------------------------------------------------
# Committed files pass every gate (drift + compatibility + conformance)
# --------------------------------------------------------------------------------------


def test_committed_artifact_has_no_drift() -> None:
    """The committed artifact equals the freshly generated one (the CI drift gate)."""
    assert ARTIFACT_PATH.read_text(encoding="utf-8") == serialize_artifact(build_contract_artifact())


def test_committed_current_version_snapshot_is_present() -> None:
    assert version_snapshot_path(PUBLISHED_CONTRACT_VERSION).exists()
    assert PUBLISHED_CONTRACT_VERSION in frozen_snapshots()


def test_committed_files_pass_all_gates() -> None:
    assert check_publication() == []


def test_drift_detected_when_artifact_stale(tmp_path: Path) -> None:
    stale = tmp_path / "backend-bundle-contract.json"
    stale.write_text("{}\n", encoding="utf-8")
    issues = check_publication(artifact_path=stale, migrations_path=MIGRATIONS_PATH)
    assert any("out of date" in issue.message for issue in issues)


def test_drift_detected_when_artifact_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    issues = check_publication(artifact_path=missing, migrations_path=MIGRATIONS_PATH)
    assert any("missing" in issue.message for issue in issues)
    # A tmp path outside the repo is rendered by name, never as an absolute host path.
    assert all(not issue.path.startswith("/") for issue in issues)


# --------------------------------------------------------------------------------------
# Breaking-change gate (AC2) — against the immutable frozen snapshot
# --------------------------------------------------------------------------------------


def _write_current_snapshot(directory: Path, *, mutate=None) -> Path:
    """Write a frozen snapshot for the current version, optionally mutating the artifact first."""
    artifact = build_contract_artifact()
    if mutate is not None:
        mutate(artifact)
    path = version_snapshot_path(PUBLISHED_CONTRACT_VERSION, directory)
    path.write_text(serialize_artifact(artifact), encoding="utf-8")
    return path


def _migrations_with_current_note(directory: Path) -> Path:
    path = directory / "MIGRATIONS.md"
    path.write_text(f"# migrations\n\n## Contract version {PUBLISHED_CONTRACT_VERSION}\n\nInitial.\n", encoding="utf-8")
    return path


def test_compatible_snapshot_passes(tmp_path: Path) -> None:
    _write_current_snapshot(tmp_path)
    assert _compatibility_issues(build_contract_artifact(), tmp_path, _migrations_with_current_note(tmp_path)) == []


def test_in_place_breaking_change_is_flagged(tmp_path: Path) -> None:
    def _add_retired_field(artifact: dict[str, Any]) -> None:
        # The frozen snapshot has a property the current schema lacks -> a breaking removal.
        artifact["backend_bundle_schema"]["properties"]["retired_field"] = {"type": "string"}

    _write_current_snapshot(tmp_path, mutate=_add_retired_field)
    issues = _compatibility_issues(build_contract_artifact(), tmp_path, _migrations_with_current_note(tmp_path))
    assert len(issues) == 1
    assert "backward-incompatible change to published contract version" in issues[0].message
    assert "retired_field" in issues[0].message


def test_missing_current_snapshot_is_flagged(tmp_path: Path) -> None:
    issues = _compatibility_issues(build_contract_artifact(), tmp_path, _migrations_with_current_note(tmp_path))
    assert len(issues) == 1
    assert "no frozen snapshot" in issues[0].message


def test_missing_migration_note_is_flagged(tmp_path: Path) -> None:
    _write_current_snapshot(tmp_path)
    empty = tmp_path / "MIGRATIONS.md"
    empty.write_text("# migrations\n", encoding="utf-8")
    issues = _compatibility_issues(build_contract_artifact(), tmp_path, empty)
    assert any("migration note" in issue.message for issue in issues)


def test_non_integer_version_is_flagged(tmp_path: Path) -> None:
    generated = {"contract_version": "bad", "backend_bundle_schema": {}}
    issues = _compatibility_issues(generated, tmp_path, _migrations_with_current_note(tmp_path))
    assert any("no frozen snapshot" in issue.message for issue in issues)


def test_missing_migrations_file_is_flagged(tmp_path: Path) -> None:
    _write_current_snapshot(tmp_path)
    issues = _compatibility_issues(build_contract_artifact(), tmp_path, tmp_path / "absent-MIGRATIONS.md")
    assert any("migration note" in issue.message for issue in issues)


def test_frozen_snapshots_missing_directory(tmp_path: Path) -> None:
    assert frozen_snapshots(tmp_path / "does-not-exist") == {}


def test_surface_flags_settings_schema_narrowing() -> None:
    frozen = {
        "backend_bundle_schema": {},
        "backends": {"aws": {"settings_schema": {"type": "object", "properties": {"region": {"type": "string"}}}}},
    }
    generated = {
        "backend_bundle_schema": {},
        "backends": {"aws": {"settings_schema": {"type": "object", "properties": {}}}},
    }
    breaking = _surface_incompatibilities(frozen, generated)
    assert any("aws.settings_schema" in c and "region: property removed" in c for c in breaking)


def test_surface_flags_removed_backend() -> None:
    frozen = {
        "backend_bundle_schema": {},
        "backends": {"aws": {"settings_schema": None}, "gcp": {"settings_schema": None}},
    }
    generated = {"backend_bundle_schema": {}, "backends": {"aws": {"settings_schema": None}}}
    assert any("backends.gcp: published backend removed" in c for c in _surface_incompatibilities(frozen, generated))


def test_surface_flags_settings_schema_removed() -> None:
    frozen = {"backend_bundle_schema": {}, "backends": {"aws": {"settings_schema": {"type": "object"}}}}
    generated = {"backend_bundle_schema": {}, "backends": {"aws": {"settings_schema": None}}}
    assert any("aws.settings_schema: removed" in c for c in _surface_incompatibilities(frozen, generated))


# --------------------------------------------------------------------------------------
# Registry conformance gate (AC3) — records validated against the published schema
# --------------------------------------------------------------------------------------


def test_registered_bundles_validate_against_published_version() -> None:
    assert _registry_conformance_issues(build_contract_artifact()) == []


def test_conformance_flags_unsupported_version() -> None:
    artifact = build_contract_artifact()
    artifact["supported_contract_versions"] = [PUBLISHED_CONTRACT_VERSION + 99]
    issues = _registry_conformance_issues(artifact)
    assert issues and all("not a published supported version" in issue.message for issue in issues)


def test_conformance_flags_extra_property() -> None:
    artifact = build_contract_artifact()
    artifact["backends"]["aws"]["bogus_field"] = "nope"  # additionalProperties: false rejects it
    issues = _registry_conformance_issues(artifact)
    assert any(issue.path == "backends.aws" and "does not validate" in issue.message for issue in issues)


def test_conformance_flags_invalid_enum_value() -> None:
    artifact = build_contract_artifact()
    artifact["backends"]["gcp"]["maturity"] = "not-a-maturity"
    issues = _registry_conformance_issues(artifact)
    assert any(issue.path == "backends.gcp" and "does not validate" in issue.message for issue in issues)


# --------------------------------------------------------------------------------------
# Security parity: the published surface rejects what BackendBundle rejects (finding #2)
# --------------------------------------------------------------------------------------


def _gcp_record() -> dict[str, Any]:
    return copy.deepcopy(build_contract_artifact()["backends"]["gcp"])


def _schema_rejects(record: dict[str, Any]) -> bool:
    validator = jsonschema.Draft202012Validator(published_backend_bundle_schema())
    return bool(list(validator.iter_errors(record)))


def _contract_rejects(record: dict[str, Any]) -> bool:
    candidate = {key: value for key, value in record.items() if key != "settings_schema"}
    try:
        BackendBundle.model_validate(candidate)
    except ValidationError:
        return True
    return False


def _bad_backend_name(record: dict[str, Any]) -> None:
    record["name"] = "Not Valid"


def _bad_tool_name(record: dict[str, Any]) -> None:
    record["required_tools"][0]["name"] = "bad name"


def _argv_shell_metacharacter(record: dict[str, Any]) -> None:
    record["validation_checks"][0]["command"]["argv"] = ["uv", "run", ";evil"]


def _argv_absolute_path(record: dict[str, Any]) -> None:
    record["validation_checks"][0]["command"]["argv"] = ["uv", "/etc/passwd"]


def _argv_empty(record: dict[str, Any]) -> None:
    record["validation_checks"][0]["command"]["argv"] = []


def _owned_files_traversal(record: dict[str, Any]) -> None:
    record["owned_files"]["scripts"] = ["../secret"]


def _secret_value_to_non_secret_destination(record: dict[str, Any]) -> None:
    record["generated_outputs"][0]["sensitivity"] = "secret-value"
    record["generated_outputs"][0]["destination"] = "runtime-env"


def _unsupported_contract_version(record: dict[str, Any]) -> None:
    record["contract_version"] = 99


@pytest.mark.parametrize(
    "mutate",
    [
        _bad_backend_name,
        _bad_tool_name,
        _argv_shell_metacharacter,
        _argv_absolute_path,
        _argv_empty,
        _owned_files_traversal,
        _secret_value_to_non_secret_destination,
        _unsupported_contract_version,
    ],
)
def test_published_surface_rejects_security_violations(mutate) -> None:
    """Every security-sensitive instance BackendBundle rejects is rejected by the published surface."""
    record = _gcp_record()
    mutate(record)
    assert _contract_rejects(record), "the internal contract must reject this bundle"
    assert _schema_rejects(record), "the published JSON schema must reject this bundle"
    assert validate_published_bundle(record), "the portable validator must reject this bundle"


def test_portable_validator_catches_cross_collection_invariants() -> None:
    # A validation check whose executable is not in required_tools is a cross-collection rule
    # JSON Schema cannot express; the portable validator (BackendBundle) must still catch it.
    record = _gcp_record()
    record["required_tools"] = []
    assert _schema_rejects(record) is False
    assert validate_published_bundle(record)


def test_valid_records_pass_the_portable_validator() -> None:
    for name in ("aws", "gcp"):
        assert validate_published_bundle(build_contract_artifact()["backends"][name]) == [], name


# --------------------------------------------------------------------------------------
# CLI: shifter-config contract export / check
# --------------------------------------------------------------------------------------


def test_cli_export_reproduces_committed_artifact(tmp_path: Path) -> None:
    out = tmp_path / "contract.json"
    assert cli.main(["contract", "export", "--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == ARTIFACT_PATH.read_text(encoding="utf-8")


def test_cli_export_default_path_freezes_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_path = tmp_path / "backend-bundle-contract.json"
    snapshot_path = tmp_path / f"backend-bundle-contract.v{PUBLISHED_CONTRACT_VERSION}.json"
    monkeypatch.setattr(cli, "ARTIFACT_PATH", artifact_path)
    monkeypatch.setattr(cli, "version_snapshot_path", lambda version: snapshot_path)

    assert cli.main(["contract", "export"]) == 0
    assert artifact_path.read_text(encoding="utf-8") == snapshot_path.read_text(encoding="utf-8")

    # A second export must NOT overwrite the frozen snapshot (immutability).
    snapshot_path.write_text("FROZEN\n", encoding="utf-8")
    assert cli.main(["contract", "export"]) == 0
    assert snapshot_path.read_text(encoding="utf-8") == "FROZEN\n"


def test_cli_export_reports_write_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    assert cli.main(["contract", "export", "--output", str(blocker / "contract.json")]) == 1


def test_cli_check_passes_on_committed_files(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["contract", "check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_check_reports_failures(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "check_publication", lambda: [ConfigIssue("backends.aws", "boom")])
    assert cli.main(["contract", "check"]) == 1
    assert "failed" in capsys.readouterr().err


def test_cli_contract_without_subcommand_shows_help() -> None:
    assert cli.main(["contract"]) == 2
