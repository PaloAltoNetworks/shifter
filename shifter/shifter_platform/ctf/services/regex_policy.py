"""Safe evaluation policy for organizer-controlled CTF flag regexes (issue #1183).

Organizer-authored regex flags are evaluated on request workers against
participant-submitted values. Standard-library ``re`` offers no execution
bound, so a crafted pattern/input pair can pin a worker (ReDoS, CWE-1333,
CWE-400). Standard ``re`` also cannot be timed out on a worker thread — the
match runs in C holding the GIL, so a watchdog thread cannot interrupt it.

This module is the single seam consumed by both creation-time validation and
runtime verification. It bounds cost with three complementary controls:

- a submitted-value length cap applied *before* any matching,
- a pattern length cap enforced at creation time,
- bounded matching via the third-party ``regex`` engine's per-call ``timeout``.

Runtime matching fails **closed**: an over-length submission, a timeout, or an
engine error is an incorrect match, never a leaked pattern, a 500, or an
unbounded evaluation. Patterns and submitted values are never logged.

Tunables live in ``config/_ctf_regex_settings.py`` and are read lazily so tests
and deployments can override them via Django settings.
"""

from __future__ import annotations

import logging

import regex
from django.conf import settings

logger = logging.getLogger(__name__)

# Defaults mirror config/_ctf_regex_settings.py; used only if a setting is unset
# (e.g. a minimal test settings module that does not import the CTF block).
_DEFAULT_MAX_PATTERN_LENGTH = 255
_DEFAULT_MAX_SUBMISSION_LENGTH = 500
_DEFAULT_MATCH_TIMEOUT_SECONDS = 0.1


class UnsafeRegexError(ValueError):
    """Raised at creation time when a regex flag pattern violates policy."""


def _max_pattern_length() -> int:
    """Configured creation-time cap on the stored regex pattern length."""
    return int(getattr(settings, "CTF_REGEX_FLAG_MAX_PATTERN_LENGTH", _DEFAULT_MAX_PATTERN_LENGTH))


def _submitted_flag_storage_limit() -> int:
    """The persisted ``CTFSubmission.submitted_flag`` column length.

    A submission that verifies as correct must also be storable — otherwise a
    correct answer 500's on insert. Deriving the limit from the model keeps the
    two in lockstep if the column ever changes.
    """
    from ctf.models import CTFSubmission

    limit = CTFSubmission._meta.get_field("submitted_flag").max_length
    return int(limit) if limit is not None else _DEFAULT_MAX_SUBMISSION_LENGTH


def _max_submission_length() -> int:
    """Effective submission-length cap, clamped to the storage limit.

    The configured policy can never exceed what ``CTFSubmission.submitted_flag``
    can persist, so any value that passes verification is always storable
    (codex #1183): a verifiable submission must be a persistable one.
    """
    configured = int(getattr(settings, "CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH", _DEFAULT_MAX_SUBMISSION_LENGTH))
    return min(configured, _submitted_flag_storage_limit())


def _match_timeout_seconds() -> float:
    """Configured per-match wall-clock budget, in seconds."""
    return float(getattr(settings, "CTF_REGEX_FLAG_MATCH_TIMEOUT_SECONDS", _DEFAULT_MATCH_TIMEOUT_SECONDS))


def validate_pattern(pattern: str) -> None:
    """Validate an organizer-supplied regex flag pattern at creation time.

    Raises:
        UnsafeRegexError: if the pattern exceeds the configured length cap or
            fails to compile under the safe engine.
    """
    max_len = _max_pattern_length()
    if len(pattern) > max_len:
        raise UnsafeRegexError(f"Regex pattern exceeds the maximum length of {max_len} characters")
    try:
        regex.compile(pattern)
    except regex.error as exc:
        raise UnsafeRegexError(f"Invalid regex pattern: {exc}") from None


def safe_fullmatch(pattern: str, value: str, *, case_sensitive: bool) -> bool:
    """Return True iff ``value`` fully matches ``pattern`` within the CPU budget.

    Fails closed: an over-length submission, a match timeout, or any engine
    error is treated as a non-match. Patterns and values are never logged.
    """
    if len(value) > _max_submission_length():
        return False

    flags = 0 if case_sensitive else regex.IGNORECASE
    try:
        return bool(regex.fullmatch(pattern, value, flags=flags, timeout=_match_timeout_seconds()))
    except TimeoutError:
        logger.warning("Regex flag verification exceeded its time budget; treating as an incorrect submission")
    except regex.error:
        logger.warning("Regex flag pattern failed to evaluate; treating as an incorrect submission")
    return False
