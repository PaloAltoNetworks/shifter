"""Log-value sanitizer for the Shifter Engine provisioner package.

Three helpers are provided, in order of taint-break strength:

- :func:`safe_log_value` — character-substituting sanitizer (CR/LF/non-
  printable escaping, length cap). Defends against log-injection
  (S5145 / CWE-117) and against pathological control chars but does
  NOT break CodeQL's ``py/clear-text-logging-sensitive-data`` data
  flow because that rule tracks values by source identifier, not by
  transformation.
- :func:`safe_log_id` — last-4-character mask (``"***<last4>"``).
  Useful when even the readable form should not land in logs; same
  CodeQL caveat as ``safe_log_value``.
- :func:`safe_log_fingerprint` — SHA-256 of the value, truncated to
  12 hex chars. One-way hashing is a recognised CodeQL sanitizer:
  the rule sees the dataflow terminate at the digest. Use this when
  CodeQL flags a logger argument as sensitive but you still want a
  stable per-value token for cross-line correlation.
"""

from __future__ import annotations

import hashlib

_MAX_LEN = 200


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
    correlation and the full identifier is sensitive enough that even
    the readable form should not land in logs.
    """
    sanitized = safe_log_value(value, max_len=_MAX_LEN)
    if sanitized in ("<none>",):
        return sanitized
    if len(sanitized) <= 8:
        return "***"
    return f"***{sanitized[-4:]}"


def safe_log_fingerprint(value: object) -> str:
    """Return ``"<12-hex-of-sha256>"`` as a CodeQL-recognised sanitizer.

    The truncated SHA-256 digest:

    - terminates the ``py/clear-text-logging-sensitive-data`` dataflow
      (hashing is on CodeQL's sanitizer list), so the wrapped value can
      flow into a ``logger.*`` argument without the rule firing;
    - is stable across log lines for the same input, so operators can
      still correlate "which ARN failed at 03:14?" with "which ARN was
      retried at 03:16?" — just by fingerprint match rather than by
      eyeballing the full identifier;
    - never reverses to the original value, which is the property the
      rule actually cares about.

    Operators who need to map a fingerprint back to a specific ARN /
    instance ID can recompute it offline:
    ``python -c "import hashlib; print(hashlib.sha256(b'<value>').hexdigest()[:12])"``
    """
    if value is None:
        return "<none>"
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]
