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
- :func:`safe_log_fingerprint` — process-local nonce that maps each
  distinct input to a random 12-hex token. The returned token is
  drawn from :func:`secrets.token_hex` and has no data dependency on
  the input, which is what makes it a true taint-break (CodeQL's
  ``py/clear-text-logging-sensitive-data`` cannot trace the input
  through the lookup). Crucially, it is **not** a hash, so it does
  not trip ``py/weak-sensitive-data-hashing`` — the rule that vetoes
  SHA-256 for sensitive data because the algorithm is not
  computationally expensive enough for password storage.
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from threading import Lock

_MAX_LEN = 200
_NONE_SENTINEL = "<none>"

# Bounded cache of seen-value -> per-process random nonce. Keeping the
# cache bounded prevents long-lived processes from accumulating mappings
# for every transient identifier ever observed; the LRU eviction order
# is fine for our use case (we only need correlation across log lines
# that arrive in quick succession).
_FINGERPRINT_CACHE_MAX_ENTRIES = 4096
_fingerprint_cache: OrderedDict[str, str] = OrderedDict()
_fingerprint_cache_lock = Lock()


def safe_log_value(value: object, max_len: int = _MAX_LEN) -> str:
    """Return ``value`` rendered safe for inclusion in a log line.

    - ``None`` becomes ``"<none>"``
    - backslashes are doubled so escape markers are unambiguous
    - CR/LF/tab become ``\\r``/``\\n``/``\\t`` literals
    - other non-printable characters become ``\\xNN``
    - output is truncated to ``max_len`` characters (with a ``...`` suffix)
    """
    if value is None:
        return _NONE_SENTINEL
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
    if sanitized == _NONE_SENTINEL:
        return sanitized
    if len(sanitized) <= 8:
        return "***"
    return f"***{sanitized[-4:]}"


def safe_log_fingerprint(value: object) -> str:
    """Return a stable per-process 12-hex nonce for ``value``.

    The returned token:

    - has no data dependency on the input — it is drawn from
      :func:`secrets.token_hex` and only looked up by ``str(value)`` —
      which is what makes it a real CodeQL taint break (the input does
      not flow into the returned value);
    - is **not** a hash, so it does not run afoul of CodeQL's
      ``py/weak-sensitive-data-hashing`` rule (which rejects SHA-256
      for sensitive data, not just MD5/SHA-1, on the basis that it is
      not a computationally expensive password-storage hash);
    - is stable across log lines **within a single process**, so the
      same secret_id / instance_id / hostname renders the same token
      and operators can correlate "which ARN failed at 03:14?" with
      "which ARN was retried at 03:16?" by token match.

    Tokens are NOT stable across processes (a new ECS task picks fresh
    nonces). Operators who need cross-process correlation should grep
    structured context fields (request_id, range_id) instead.
    """
    if value is None:
        return _NONE_SENTINEL
    key = str(value)
    with _fingerprint_cache_lock:
        cached = _fingerprint_cache.get(key)
        if cached is not None:
            # Move-to-end keeps the LRU ordering accurate.
            _fingerprint_cache.move_to_end(key)
            return cached
        if len(_fingerprint_cache) >= _FINGERPRINT_CACHE_MAX_ENTRIES:
            _fingerprint_cache.popitem(last=False)
        nonce = secrets.token_hex(6)
        _fingerprint_cache[key] = nonce
        return nonce
