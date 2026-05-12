"""Tests for the frozen normalizer inside migration 0002.

The migration intentionally inlines its own `_normalize_key` and validator
copies so the historical behavior cannot drift with a future refactor of
`cms.experiments.s3`. These tests exercise that frozen helper directly so
the migration's actual deploy-time behavior is pinned in CI.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(scope="module")
def migration_module():
    return importlib.import_module("cms.experiments.migrations.0002_normalize_legacy_script_s3_keys")


class TestFrozenNormalizer:
    @pytest.mark.parametrize(
        "legacy_key",
        [
            "scripts/1/abc_my file.py",  # space
            "scripts/1/abc_'quoted'.py",  # quotes
            "scripts/1/abc_$(injection).py",  # command substitution
            "scripts/1/abc_..parent_traversal.py",  # ..
            "scripts/1/abc_back`ticks`.py",  # backticks
            "scripts/1/Ümlaut_file.py",  # unicode
            "/scripts/1/leading_slash.py",  # leading slash
            "scripts/../../etc/passwd",  # traversal
            "scripts/1/" + "x" * 600,  # over length
            "",  # empty
        ],
    )
    def test_normalized_keys_are_valid(self, migration_module, legacy_key):
        new_key = migration_module._normalize_key(legacy_key, asset_pk=42)
        assert migration_module._is_valid_s3_key(new_key), (
            f"normalizer produced an invalid key: {new_key!r} from {legacy_key!r}"
        )

    def test_distinct_inputs_get_distinct_outputs_via_pk_suffix(self, migration_module):
        """The per-asset pk suffix prevents two legacy keys from colliding."""
        a = migration_module._normalize_key("scripts/1/abc_my file.py", asset_pk=1)
        b = migration_module._normalize_key("scripts/1/abc_my file.py", asset_pk=2)
        assert a != b
        assert a.endswith("-pk1")
        assert b.endswith("-pk2")

    def test_already_valid_input_still_gets_suffix(self, migration_module):
        """The frozen normalizer always appends -pk<id>; the migration loop
        skips already-valid keys before calling it."""
        key = migration_module._normalize_key("scripts/1/file.py", asset_pk=99)
        assert key.endswith("-pk99")

    def test_truncation_keeps_under_500(self, migration_module):
        new_key = migration_module._normalize_key("a" * 800, asset_pk=1234)
        assert len(new_key) <= 500
        assert new_key.endswith("-pk1234")


class TestFrozenValidator:
    @pytest.mark.parametrize(
        "key,expected",
        [
            ("scripts/1/abc_file.py", True),
            ("scripts/1/abc.file.py", True),
            ("", False),
            ("/leading-slash", False),
            ("with..traversal", False),
            ("with spaces", False),
            ("with'quote", False),
            ("a" * 600, False),  # > 500
        ],
    )
    def test_validator_matches_execution_contract(self, migration_module, key, expected):
        assert migration_module._is_valid_s3_key(key) == expected
