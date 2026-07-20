"""Ingestion-time pack validation of foreign input (#1578, ADR-034).

A pack arriving at the uniform content-ingestion path is foreign input: it is
source-agnostic and entitlement-blind, but it must never be ingested broken,
malformed, or non-conformant. These tests pin the static, subprocess-free
validation that :mod:`cms.scenarios.pack_validation` performs by delegating to
the ``aces-scenario-packs`` contract schemas and to ACES SDL parsing. Pack
fixtures come from the shared ``make_pack`` factory (see ``tests/cms/conftest``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from aces_scenario_packs.content_ci import compatibility_example_path

from cms.scenarios.pack_validation import PackValidationError, check_pack, validate_pack
from tests.cms.conftest import conformant_pack_yaml, conformant_provenance


class TestPackValidationHappyPath:
    def test_conformant_pack_has_no_errors(self, make_pack, tmp_path):
        assert check_pack(make_pack(tmp_path / "pack")) == []

    def test_validate_pack_accepts_conformant(self, make_pack, tmp_path):
        validate_pack(make_pack(tmp_path / "pack"))  # must not raise


class TestPackValidationRejectsForeignInput:
    def test_non_directory_is_rejected(self, tmp_path):
        assert check_pack(tmp_path / "missing") != []

    def test_missing_pack_yaml_is_rejected(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack")
        (root / "pack.yaml").unlink()
        assert any("pack.yaml" in e for e in check_pack(root))

    def test_pack_yaml_missing_identity_is_rejected(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack", pack_yaml={"title": "No name"})
        assert any("name" in e for e in check_pack(root))

    def test_pack_identity_must_match_root_directory(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack", name="different-name")
        assert "pack.identity.name-mismatch: pack.yaml:name" in check_pack(root)

    def test_duplicate_yaml_key_is_rejected(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack")
        (root / "pack.yaml").write_text("name: pack\nname: pack\n", encoding="utf-8")
        assert "yaml.duplicate-key: pack.yaml" in check_pack(root)

    def test_symlink_member_is_rejected(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack")
        outside = tmp_path / "outside.md"
        outside.write_text("outside the pack\n", encoding="utf-8")
        concepts = root / "docs" / "concepts.md"
        concepts.unlink()
        concepts.symlink_to(outside)
        assert "filesystem.unsafe-member" in check_pack(root)

    def test_metadata_resource_limit_is_enforced(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack")
        (root / "pack.yaml").write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
        assert "resource.metadata-limit: pack.yaml" in check_pack(root)

    def test_missing_provenance_ledger_is_rejected(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack")
        (root / "docs/provenance-ledger.yaml").unlink()
        assert any("provenance" in e.lower() for e in check_pack(root))

    def test_schema_invalid_provenance_is_rejected(self, make_pack, tmp_path):
        bad = {**conformant_provenance("ingestion-fixture"), "sources": []}  # minItems: 1
        root = make_pack(tmp_path / "pack", provenance=bad)
        assert check_pack(root) != []

    def test_content_safety_not_all_true_is_rejected(self, make_pack, tmp_path):
        prov = conformant_provenance("ingestion-fixture")
        prov["content_safety"]["no_real_malware"] = False
        root = make_pack(tmp_path / "pack", provenance=prov)
        assert any("content_safety" in e for e in check_pack(root))

    def test_provenance_name_mismatch_is_rejected(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack", provenance=conformant_provenance("other-name"))
        assert any("name" in e for e in check_pack(root))

    def test_missing_sdl_is_rejected(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack", sdl=None)
        assert any("sdl" in e.lower() for e in check_pack(root))

    def test_unparseable_sdl_is_rejected(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack", sdl="name: broken\nnodes: not-a-mapping\n")
        assert any("sdl" in e.lower() for e in check_pack(root))

    def test_validate_pack_raises_on_malformed(self, make_pack, tmp_path):
        root = make_pack(tmp_path / "pack", sdl=None)
        with pytest.raises(PackValidationError):
            validate_pack(root)

    def test_error_messages_do_not_echo_pack_body(self, make_pack, tmp_path):
        # A secret-looking value inside the SDL must not be echoed in the bounded
        # error text (ingestion errors are quasi-public; no body/value leakage).
        secret = "SUPERSECRETTOKEN123"
        root = make_pack(tmp_path / "pack", sdl=f"name: x\nnodes: {secret}\n")
        assert secret not in " ".join(check_pack(root))


def _pack_with_compatibility(make_pack, root, *, manifest_rel="pack.compatibility.yaml", manifest=..., write=True):
    """Build a conformant pack that references a compatibility manifest."""
    pack_name = Path(root).name
    pack_yaml = conformant_pack_yaml(pack_name)
    pack_yaml["compatibility_manifest"] = manifest_rel
    built = make_pack(root, name=pack_name, pack_yaml=pack_yaml)
    if write:
        if manifest is ...:
            manifest = yaml.safe_load(Path(compatibility_example_path()).read_text(encoding="utf-8"))
        (built / manifest_rel).write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return built


class TestPackValidationCompatibilityManifest:
    """The optional compatibility-manifest branch of pack validation."""

    def test_valid_compatibility_manifest_passes(self, make_pack, tmp_path):
        # A schema-valid manifest (the packaged worked example) is accepted.
        root = _pack_with_compatibility(make_pack, tmp_path / "pack")
        assert check_pack(root) == []

    def test_missing_compatibility_manifest_file_is_rejected(self, make_pack, tmp_path):
        root = _pack_with_compatibility(make_pack, tmp_path / "pack", write=False)
        assert any("compatibility" in e.lower() for e in check_pack(root))

    def test_schema_invalid_compatibility_manifest_is_rejected(self, make_pack, tmp_path):
        # schema_version has const 1; 2 is a schema violation.
        root = _pack_with_compatibility(make_pack, tmp_path / "pack", manifest={"schema_version": 2})
        assert any("compatibility" in e.lower() for e in check_pack(root))

    def test_compatibility_manifest_escaping_pack_root_is_rejected(self, make_pack, tmp_path):
        root = _pack_with_compatibility(make_pack, tmp_path / "pack", manifest_rel="../outside.yaml", write=False)
        errors = check_pack(root)
        assert "compatibility.pointer.invalid: pack.yaml:compatibility_manifest" in errors
