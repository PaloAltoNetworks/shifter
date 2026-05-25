"""Tests for :mod:`shared.log_sanitize`.

Covers the sanitizer used at every CodeQL ``py/log-injection`` call site so
regressions in escape handling, control-character replacement, or truncation
get caught here rather than at scanner time.
"""

from __future__ import annotations

import logging

import pytest

from shared.log_sanitize import safe_log, safe_log_value


class TestSafeLogValue:
    def test_none_renders_placeholder(self) -> None:
        assert safe_log_value(None) == "<none>"

    def test_plain_string_passthrough(self) -> None:
        assert safe_log_value("user@example.com") == "user@example.com"

    def test_newline_is_escaped(self) -> None:
        assert safe_log_value("foo\nbar") == "foo\\nbar"

    def test_carriage_return_is_escaped(self) -> None:
        assert safe_log_value("foo\rbar") == "foo\\rbar"

    def test_tab_is_escaped(self) -> None:
        assert safe_log_value("col1\tcol2") == "col1\\tcol2"

    def test_combined_crlf_is_escaped(self) -> None:
        injected = "ok\r\nFAKE 2026-05-24 ERROR forged"
        out = safe_log_value(injected)
        assert "\n" not in out
        assert "\r" not in out
        assert "\\r\\n" in out

    def test_backslash_is_doubled(self) -> None:
        # The backslash must be doubled BEFORE the CR/LF substitution; otherwise
        # a literal "\\n" in user input becomes indistinguishable from a real
        # newline that's been escaped.
        assert safe_log_value("a\\b") == "a\\\\b"

    def test_control_char_becomes_hex(self) -> None:
        # ANSI ESC (0x1b) could be used to inject terminal escape sequences.
        assert safe_log_value("hi\x1b[31mred") == "hi\\x1b[31mred"

    def test_null_byte_becomes_hex(self) -> None:
        assert safe_log_value("a\x00b") == "a\\x00b"

    def test_unicode_printable_passthrough(self) -> None:
        assert safe_log_value("café") == "café"

    def test_truncation_appends_ellipsis(self) -> None:
        out = safe_log_value("x" * 1000, max_len=20)
        assert len(out) == 20
        assert out.endswith("...")
        assert out == "x" * 17 + "..."

    def test_short_string_not_truncated(self) -> None:
        out = safe_log_value("short", max_len=20)
        assert out == "short"

    def test_non_string_is_coerced(self) -> None:
        assert safe_log_value(42) == "42"
        assert safe_log_value(True) == "True"

    def test_object_is_coerced_via_str(self) -> None:
        class _Thing:
            def __str__(self) -> str:
                return "thing\nbad"

        assert safe_log_value(_Thing()) == "thing\\nbad"

    def test_returned_value_is_str(self) -> None:
        # CodeQL's taint tracker needs a fresh str — make sure we always
        # return one regardless of input type.
        assert isinstance(safe_log_value(None), str)
        assert isinstance(safe_log_value(123), str)
        assert isinstance(safe_log_value("hi"), str)

    def test_used_in_logger_call_produces_safe_line(self, caplog: pytest.LogCaptureFixture) -> None:
        # Integration-style check: the value emitted by the formatter must
        # not contain raw newlines from the attacker-controlled input.
        logger = logging.getLogger("shared.log_sanitize.test")
        with caplog.at_level(logging.INFO, logger=logger.name):
            logger.info("hello %s", safe_log_value("foo\nbar"))
        assert len(caplog.records) == 1
        formatted = caplog.records[0].getMessage()
        assert formatted == "hello foo\\nbar"
        assert "\n" not in formatted


class TestSafeLog:
    """The legacy helper is kept for backward compat — keep it tested too."""

    def test_escapes_newline_in_string(self) -> None:
        assert safe_log("foo\nbar") == "foo\\nbar"

    def test_escapes_carriage_return_in_string(self) -> None:
        assert safe_log("foo\rbar") == "foo\\rbar"

    def test_passes_through_non_string(self) -> None:
        assert safe_log(42) == 42
        assert safe_log(None) is None
