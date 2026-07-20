"""Safety tests for organizer-controlled CTF regex flags (issue #1183).

Regex flags are authored by organizers and evaluated on request workers
against participant-submitted values. Without an execution bound a crafted
pattern/input pair can pin a worker (ReDoS, CWE-1333). These tests pin the
policy: bounded matching that fails closed, a submitted-value length cap
applied before matching, and creation-time rejection of over-long patterns.

The catastrophic-pattern cases run under the helper's own timeout, so no
test performs unbounded matching.
"""

from __future__ import annotations

import time

import pytest
from django.test import override_settings

from ctf.exceptions import CTFValidationError
from ctf.services.challenge import _flag_hash_for_payload
from ctf.services.regex_policy import UnsafeRegexError, safe_fullmatch, validate_pattern

# A pattern the backtracking engine genuinely blows up on (verified: without a
# timeout this does not terminate in reasonable time). Paired with an input that
# forces the pathological path.
_CATASTROPHIC_PATTERN = r"(a|a)*$"
_CATASTROPHIC_INPUT = "a" * 60 + "!"


class TestSafeFullmatch:
    def test_matches_benign_pattern(self):
        assert safe_fullmatch(r"flag\{.*\}", "flag{abc}", case_sensitive=True) is True

    def test_no_match_benign_pattern(self):
        assert safe_fullmatch(r"flag\{.*\}", "nope", case_sensitive=True) is False

    def test_case_insensitive(self):
        assert safe_fullmatch(r"flag", "FLAG", case_sensitive=False) is True

    def test_case_sensitive_rejects_wrong_case(self):
        assert safe_fullmatch(r"flag", "FLAG", case_sensitive=True) is False

    def test_invalid_pattern_fails_closed(self):
        # Unbalanced group: engine error must be swallowed as a non-match.
        assert safe_fullmatch(r"flag([", "flag", case_sensitive=True) is False

    @override_settings(CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH=16)
    def test_over_length_submission_is_rejected_before_matching(self):
        # A submission longer than the cap is a non-match and must not be
        # handed to the engine at all.
        assert safe_fullmatch(r".*", "x" * 17, case_sensitive=True) is False

    @override_settings(CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH=16)
    def test_submission_at_cap_still_evaluated(self):
        assert safe_fullmatch(r"x*", "x" * 16, case_sensitive=True) is True

    @override_settings(CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH=10_000)
    def test_effective_cap_never_exceeds_submitted_flag_storage_limit(self):
        # Codex #1183: a submission-length policy above the CTFSubmission
        # .submitted_flag column limit would let an over-long value verify as
        # correct yet fail to persist. The effective cap is clamped to the
        # storage limit regardless of the configured (higher) value.
        from ctf.models import CTFSubmission

        storage_limit = CTFSubmission._meta.get_field("submitted_flag").max_length
        assert safe_fullmatch(r"x*", "x" * storage_limit, case_sensitive=True) is True
        assert safe_fullmatch(r"x*", "x" * (storage_limit + 1), case_sensitive=True) is False

    @override_settings(CTF_REGEX_FLAG_MATCH_TIMEOUT_SECONDS=0.1)
    def test_catastrophic_pattern_is_bounded_and_fails_closed(self):
        start = time.monotonic()
        result = safe_fullmatch(_CATASTROPHIC_PATTERN, _CATASTROPHIC_INPUT, case_sensitive=True)
        elapsed = time.monotonic() - start
        assert result is False
        # Bounded: must return well within a small multiple of the timeout,
        # never hang the worker.
        assert elapsed < 2.0

    def test_timeout_fails_closed(self, monkeypatch):
        def _raise_timeout(*args, **kwargs):
            raise TimeoutError

        monkeypatch.setattr("ctf.services.regex_policy.regex.fullmatch", _raise_timeout)
        assert safe_fullmatch(r"flag", "flag", case_sensitive=True) is False


class TestValidatePattern:
    def test_accepts_normal_pattern(self):
        # Does not raise.
        validate_pattern(r"flag\{[a-f0-9]{32}\}")

    def test_rejects_invalid_syntax(self):
        with pytest.raises(UnsafeRegexError):
            validate_pattern(r"flag([")

    @override_settings(CTF_REGEX_FLAG_MAX_PATTERN_LENGTH=10)
    def test_rejects_over_length_pattern(self):
        with pytest.raises(UnsafeRegexError):
            validate_pattern("a" * 11)

    @override_settings(CTF_REGEX_FLAG_MAX_PATTERN_LENGTH=10)
    def test_accepts_pattern_at_cap(self):
        validate_pattern("a" * 10)


class TestCreationTimeRejection:
    """`_flag_hash_for_payload` is the single creation-time chokepoint used by
    both add_flag and update_flag; it must reject unsafe regex patterns."""

    @override_settings(CTF_REGEX_FLAG_MAX_PATTERN_LENGTH=10)
    def test_over_length_regex_pattern_rejected(self):
        with pytest.raises(CTFValidationError):
            _flag_hash_for_payload(
                "regex",
                {"flag": "a" * 11},
                case_sensitive=True,
                validator_config=None,
            )

    def test_invalid_regex_pattern_rejected(self):
        with pytest.raises(CTFValidationError):
            _flag_hash_for_payload(
                "regex",
                {"flag": "flag(["},
                case_sensitive=True,
                validator_config=None,
            )

    def test_valid_regex_pattern_stored_verbatim(self):
        stored = _flag_hash_for_payload(
            "regex",
            {"flag": r"flag\{.*\}"},
            case_sensitive=True,
            validator_config=None,
        )
        assert stored == r"flag\{.*\}"
