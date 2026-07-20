"""Helpers to sanitize user-controlled values before they hit log output.

SonarCloud S5145 / CWE-117 and CodeQL ``py/log-injection`` flag log statements
that emit user-controlled strings verbatim, because an attacker who can inject
newlines or carriage returns into the string can forge log entries — or smuggle
ANSI escape sequences / control characters if logs are rendered in a terminal.

This module exposes four helpers, in order of taint-break strength:

* :func:`safe_log` — a minimal CR/LF escaper preserved for backward
  compatibility with existing call sites that already rely on it.
* :func:`safe_log_value` — the canonical sanitizer for ``py/log-injection``
  sites. It escapes CR/LF/tab, replaces other non-printable characters with
  ``\\xNN`` markers, and truncates to a sane upper bound. Returned value is
  always a ``str``, which is what CodeQL's taint tracker recognises as the
  break in the ``py/log-injection`` dataflow. It does **not** break
  ``py/clear-text-logging-sensitive-data`` (that rule tracks values by source
  identifier, not by transformation).
* :func:`safe_log_id` — last-4-character mask (``"***<last4>"``) for opaque
  identifiers where even the readable form should not land in logs.
* :func:`safe_log_fingerprint` — a process-local random nonce that maps each
  distinct input to a 12-hex token with **no data dependency** on the input.
  That is what makes it a true ``py/clear-text-logging-sensitive-data``
  taint-break, and because it is **not** a hash it does not trip
  ``py/weak-sensitive-data-hashing``. Use it when a value CodeQL classifies as
  sensitive must still be correlatable across log lines within a process.

This mirrors the Shifter Engine provisioner's ``log_redact`` module so both
layers share one logging-redaction vocabulary.

Usage::

    from shared.log_sanitize import safe_log_value, safe_log_fingerprint
    logger.info("scenario_id=%s", safe_log_value(scenario_id))
    logger.info("host=%s", safe_log_fingerprint(internal_host))
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from threading import Lock

_MAX_LEN = 200
_NONE_SENTINEL = "<none>"

# Bounded cache of seen-value -> per-process random nonce. Keeping it bounded
# stops long-lived processes from accumulating a mapping for every transient
# identifier ever observed; LRU eviction is fine because we only need
# correlation across log lines that arrive in quick succession.
_FINGERPRINT_CACHE_MAX_ENTRIES = 4096
_fingerprint_cache: OrderedDict[str, str] = OrderedDict()
_fingerprint_cache_lock = Lock()


def safe_log(value: object) -> object:
    """Return *value* with CR/LF escaped when it is a string.

    Backward-compatible minimal sanitizer. Non-string values are returned
    as-is so the caller's format spec (``%s``, ``%d``, ``%r``, ...) still
    behaves normally. New call sites should prefer :func:`safe_log_value`
    because CodeQL's ``py/log-injection`` rule only recognises the
    full-strength sanitizer as breaking the taint flow.
    """
    if isinstance(value, str):
        return value.replace("\r", "\\r").replace("\n", "\\n")
    return value


def safe_log_value(value: object, max_len: int = _MAX_LEN) -> str:
    """Return ``value`` rendered safe for inclusion in a log line.

    - ``None`` becomes ``"<none>"``
    - backslashes are doubled so escape markers are unambiguous
    - CR/LF/tab become ``\\r``/``\\n``/``\\t`` literals
    - other non-printable characters become ``\\xNN``
    - output is truncated to ``max_len`` characters (with a ``...`` suffix)
    """
    if value is None:
        return "<none>"
    text = str(value)
    text = text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    cleaned_chars: list[str] = []
    for char in text:
        if char.isprintable() or char == " ":
            cleaned_chars.append(char)
        else:
            cleaned_chars.append(f"\\x{ord(char):02x}")
    cleaned = "".join(cleaned_chars)
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 3] + "..."
    return cleaned


def safe_log_id(value: object) -> str:
    """Return ``"***<last4>"`` for opaque secret IDs / ARNs / tokens.

    Useful when the operator only needs the trailing characters for
    correlation and the full identifier is sensitive enough that even the
    readable form should not land in logs. Carries the same CodeQL caveat as
    :func:`safe_log_value`: it does not break the
    ``py/clear-text-logging-sensitive-data`` dataflow (use
    :func:`safe_log_fingerprint` for that).
    """
    sanitized = safe_log_value(value, max_len=_MAX_LEN)
    if sanitized == _NONE_SENTINEL:
        return sanitized
    if len(sanitized) <= 8:
        return "***"
    return f"***{sanitized[-4:]}"


def safe_log_fingerprint(value: object) -> str:
    """Return a stable per-process 12-hex nonce for ``value``.

    The returned token has no data dependency on the input — it is drawn from
    :func:`secrets.token_hex` and only looked up by ``str(value)`` — which is
    what makes it a real CodeQL ``py/clear-text-logging-sensitive-data``
    taint-break. It is **not** a hash, so it does not trip
    ``py/weak-sensitive-data-hashing``. The token is stable across log lines
    within a single process (so the same identifier renders the same token and
    operators can correlate), but NOT across processes.
    """
    if value is None:
        return _NONE_SENTINEL
    key = str(value)
    with _fingerprint_cache_lock:
        cached = _fingerprint_cache.get(key)
        if cached is not None:
            _fingerprint_cache.move_to_end(key)
            return cached
        if len(_fingerprint_cache) >= _FINGERPRINT_CACHE_MAX_ENTRIES:
            _fingerprint_cache.popitem(last=False)
        nonce = secrets.token_hex(6)
        _fingerprint_cache[key] = nonce
        return nonce
