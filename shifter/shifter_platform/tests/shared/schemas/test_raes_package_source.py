"""Tests for the shared RAES package-source validation contract."""

import pytest

from shared.schemas.raes_package_source import (
    PackageSourceRecord,
    RaesPackageSourceError,
    validate_package_source,
)

VALID = {
    "source_kind": "repo",
    "contract_kind": "raes",
    "contract_profile": "shifter",
    "package_ref": "scenario-dev/polaris/content-packages/polaris",
    "package_version": "1.0.0",
    "package_digest": "sha256:" + "a" * 64,
    "lock_ref": "scenario-dev/polaris/content-packages/polaris.lock",
    "lock_digest": "sha256:" + "b" * 64,
    "conformance_status": "passed",
    "conformance_report_ref": "reports/polaris-conformance.json",
    "provenance": {
        "repo": "Brad-Edwards/shifter",
        "commit": "abc123",
        "tool": "raes",
        "tool_version": "0.1",
    },
}


def _record(**overrides):
    return PackageSourceRecord(**{**VALID, **overrides})


def _assert_invalid(record, match=None):
    with pytest.raises(RaesPackageSourceError, match=match):
        validate_package_source(record)


class TestValidatePackageSource:
    def test_valid_payload_passes(self):
        assert validate_package_source(_record()) == VALID["provenance"]

    def test_minimal_valid_payload(self):
        result = validate_package_source(
            PackageSourceRecord(
                source_kind="repo",
                contract_kind="raes",
                contract_profile="shifter",
                package_ref="pkg",
                package_version="1",
                package_digest="sha256:" + "c" * 64,
                conformance_status="pending",
            )
        )
        assert result == {}

    @pytest.mark.parametrize(
        "digest",
        ["", "abc", "sha1:" + "a" * 40, "sha256:" + "A" * 64, "sha256:" + "a" * 63],
    )
    def test_bad_package_digest_rejected(self, digest):
        _assert_invalid(_record(package_digest=digest))

    def test_bad_lock_digest_rejected(self):
        _assert_invalid(_record(lock_digest="not-a-digest"))

    def test_multiline_ref_rejected(self):
        _assert_invalid(_record(package_ref="line1\nSDL body line2"), match="single-line")

    def test_unknown_source_kind_rejected(self):
        _assert_invalid(_record(source_kind="ftp"))

    def test_unknown_contract_kind_rejected(self):
        _assert_invalid(_record(contract_kind="polaris"))

    def test_unknown_conformance_status_rejected(self):
        _assert_invalid(_record(conformance_status="great"))

    def test_empty_contract_profile_rejected(self):
        _assert_invalid(_record(contract_profile="   "))

    @pytest.mark.parametrize(
        "key",
        ["sdl", "module_body", "generated", "credential", "token", "runtime_config", "flag"],
    )
    def test_forbidden_provenance_key_rejected(self, key):
        _assert_invalid(_record(provenance={key: "x"}), match="not an allowed")

    def test_nested_provenance_value_rejected(self):
        _assert_invalid(_record(provenance={"notes": {"nested": "blob"}}), match="scalar")

    def test_multiline_provenance_value_rejected(self):
        _assert_invalid(_record(provenance={"notes": "line1\nline2"}), match="single-line")

    def test_per_value_length_rejected(self):
        # 600 chars: over the 512 per-value cap, but the whole payload stays
        # under the 4096-byte cap so this isolates the _validate_scalar check.
        _assert_invalid(_record(provenance={"notes": "x" * 600}), match="512 characters")

    def test_total_provenance_size_rejected(self):
        # Many allowed-length values whose combined size exceeds the 4096-byte
        # cap while each value stays within the 512 per-value limit.
        _assert_invalid(_record(provenance={"notes": ["x" * 500 for _ in range(30)]}), match="4096 bytes")

    def test_provenance_list_length_rejected(self):
        _assert_invalid(_record(provenance={"notes": ["a"] * 33}), match="items")

    def test_non_dict_provenance_rejected(self):
        _assert_invalid(_record(provenance=["repo", "commit"]), match="JSON object")

    def test_none_provenance_normalizes_to_empty(self):
        assert validate_package_source(_record(provenance=None)) == {}

    def test_scalar_list_provenance_allowed(self):
        result = validate_package_source(_record(provenance={"notes": ["a", "b", 1, True]}))
        assert result == {"notes": ["a", "b", 1, True]}
