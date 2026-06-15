"""Tests for log_redact.safe_log_value, safe_log_id, and safe_log_fingerprint."""

from __future__ import annotations

import log_redact
from log_redact import safe_log_fingerprint, safe_log_id, safe_log_value


class TestSafeLogValue:
    def test_none_becomes_marker(self):
        assert safe_log_value(None) == "<none>"

    def test_plain_string_passes_through(self):
        assert safe_log_value("ngfw-mgmt-10.0.0.1") == "ngfw-mgmt-10.0.0.1"

    def test_int_renders_as_str(self):
        assert safe_log_value(42) == "42"

    def test_crlf_escaped(self):
        assert safe_log_value("a\r\nb") == "a\\r\\nb"

    def test_tab_escaped(self):
        assert safe_log_value("col1\tcol2") == "col1\\tcol2"

    def test_backslash_doubled(self):
        assert safe_log_value("C:\\Users\\admin") == "C:\\\\Users\\\\admin"

    def test_control_char_hex_marker(self):
        assert "\\x1b" in safe_log_value("ANSI\x1b[31mred\x1b[0m")

    def test_truncation_with_suffix(self):
        result = safe_log_value("x" * 300, max_len=50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_no_truncation_at_boundary(self):
        # exactly at the boundary, no ellipsis added
        assert safe_log_value("y" * 10, max_len=10) == "y" * 10


class TestSafeLogId:
    def test_none_returns_none_marker(self):
        assert safe_log_id(None) == "<none>"

    def test_short_string_fully_masked(self):
        assert safe_log_id("abc") == "***"

    def test_exactly_eight_chars_fully_masked(self):
        assert safe_log_id("12345678") == "***"

    def test_long_string_shows_last_four(self):
        assert safe_log_id("arn:aws:secretsmanager:us-east-2:123456789012:secret:foo-AbCdEf") == "***CdEf"

    def test_unicode_passes_through(self):
        # safe_log_value handles printable unicode; safe_log_id slices the tail
        result = safe_log_id("alpha-beta-gamma")
        assert result == "***amma"


class TestSafeLogFingerprint:
    def setup_method(self):
        # Each test starts from a clean cache so cross-test nonce assignments
        # don't leak in.
        log_redact._fingerprint_cache.clear()

    def test_none_returns_none_marker(self):
        assert safe_log_fingerprint(None) == "<none>"

    def test_returns_twelve_hex_chars(self):
        result = safe_log_fingerprint("any-value")
        assert len(result) == 12
        assert all(c in "0123456789abcdef" for c in result)

    def test_stable_within_process(self):
        first = safe_log_fingerprint("abc")
        second = safe_log_fingerprint("abc")
        assert first == second

    def test_distinct_inputs_distinct_outputs(self):
        assert safe_log_fingerprint("abc") != safe_log_fingerprint("def")

    def test_integer_input_uses_string_form(self):
        # Cached under str(value), so int 42 and str "42" alias.
        assert safe_log_fingerprint(42) == safe_log_fingerprint("42")

    def test_does_not_leak_input_substring(self):
        secret = "supersecretpasswordvalue"
        result = safe_log_fingerprint(secret)
        assert secret not in result
        assert "password" not in result

    def test_not_derived_from_input(self):
        # New process state -> same input maps to a different random token
        # than the previous process would have produced. The token must be
        # *purely* random, not derived from the input value.
        log_redact._fingerprint_cache.clear()
        first_run = safe_log_fingerprint("arn:aws:secret:foo")
        log_redact._fingerprint_cache.clear()
        second_run = safe_log_fingerprint("arn:aws:secret:foo")
        # Two independent random tokens for the same input across cache
        # resets — collision odds are 1 in 2^48.
        assert first_run != second_run

    def test_cache_evicts_oldest_at_capacity(self):
        log_redact._fingerprint_cache.clear()
        original_limit = log_redact._FINGERPRINT_CACHE_MAX_ENTRIES
        log_redact._FINGERPRINT_CACHE_MAX_ENTRIES = 3
        try:
            a = safe_log_fingerprint("a")  # cache: {a}
            safe_log_fingerprint("b")  # cache: {a, b}
            safe_log_fingerprint("c")  # cache: {a, b, c}
            safe_log_fingerprint("d")  # evicts "a", cache: {b, c, d}
            new_a = safe_log_fingerprint("a")  # evicts "b", cache: {c, d, a}
            assert new_a != a  # fresh nonce after eviction
            assert "b" not in log_redact._fingerprint_cache
            assert {"c", "d", "a"} == set(log_redact._fingerprint_cache.keys())
        finally:
            log_redact._FINGERPRINT_CACHE_MAX_ENTRIES = original_limit
            log_redact._fingerprint_cache.clear()
