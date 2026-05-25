"""Helpers to sanitize user-controlled values before they hit log output.

SonarCloud S5145 / CWE-117 and CodeQL ``py/log-injection`` flag log statements
that emit user-controlled strings verbatim, because an attacker who can inject
newlines or carriage returns into the string can forge log entries — or smuggle
ANSI escape sequences / control characters if logs are rendered in a terminal.

This module exposes two helpers:

* :func:`safe_log` — a minimal CR/LF escaper preserved for backward
  compatibility with existing call sites that already rely on it.
* :func:`safe_log_value` — the canonical sanitizer for sites that CodeQL
  flags. It escapes CR/LF/tab, replaces other non-printable characters with
  ``\\xNN`` markers, and truncates to a sane upper bound. Returned value is
  always a ``str``, which is what CodeQL's taint tracker recognises as the
  break in the dataflow.

Usage::

    from shared.log_sanitize import safe_log_value
    logger.info("scenario_id=%s", safe_log_value(scenario_id))
"""

from __future__ import annotations

_MAX_LEN = 200


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
