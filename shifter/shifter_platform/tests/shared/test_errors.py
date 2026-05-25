"""Tests for :mod:`shared.errors`.

These cover the sanitization that breaks CodeQL's
``py/stack-trace-exposure`` taint flow when views return a curated error
message instead of ``str(exc)``.
"""

from __future__ import annotations

from shared.errors import UserFacingError, safe_user_message


class TestUserFacingError:
    def test_plain_message_round_trips(self) -> None:
        err = UserFacingError("No active range found")
        assert err.user_message == "No active range found"
        assert err.http_status == 400

    def test_custom_http_status(self) -> None:
        err = UserFacingError("nope", http_status=404)
        assert err.http_status == 404

    def test_newlines_stripped(self) -> None:
        err = UserFacingError("a\nb")
        assert err.user_message == "a b"

    def test_carriage_returns_stripped(self) -> None:
        err = UserFacingError("a\rb")
        assert err.user_message == "a b"

    def test_crlf_combined_stripped(self) -> None:
        err = UserFacingError("ok\r\nForged log entry")
        assert "\n" not in err.user_message
        assert "\r" not in err.user_message

    def test_empty_message_falls_back_to_default(self) -> None:
        err = UserFacingError("")
        assert err.user_message == "An error occurred"

    def test_whitespace_only_message_falls_back(self) -> None:
        err = UserFacingError("   \n  \r ")
        assert err.user_message == "An error occurred"

    def test_message_truncated_at_500(self) -> None:
        err = UserFacingError("x" * 1000)
        assert len(err.user_message) == 500

    def test_message_preserved_under_limit(self) -> None:
        msg = "x" * 100
        err = UserFacingError(msg)
        assert err.user_message == msg

    def test_str_returns_sanitized_message(self) -> None:
        err = UserFacingError("hi\nthere")
        # super().__init__(clean) means str(err) == sanitized form.
        assert str(err) == "hi there"

    def test_is_exception(self) -> None:
        err = UserFacingError("nope")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        try:
            raise UserFacingError("boom")
        except UserFacingError as e:
            assert e.user_message == "boom"


class TestSafeUserMessage:
    def test_plain_message_round_trips(self) -> None:
        assert safe_user_message("hello") == "hello"

    def test_newline_stripped(self) -> None:
        assert safe_user_message("a\nb") == "a b"

    def test_none_falls_back_to_default(self) -> None:
        assert safe_user_message(None) == "An error occurred"

    def test_coerces_non_string(self) -> None:
        assert safe_user_message(42) == "42"
