"""Log-injection sanitization helper.

SonarCloud S5145 / CWE-117 flags log statements that emit user-controlled
strings verbatim, because an attacker who can inject newlines or carriage
returns into the string can forge log entries. The standard mitigation is
to escape control characters before they reach the log formatter.

Usage::

    from shared.log_sanitize import safe_log
    logger.info("scenario_id=%s", safe_log(scenario_id))

``safe_log`` is intentionally a no-op on non-string values (ints, UUIDs,
Django model instances, exceptions) because those cannot carry line
terminators in a meaningful way — they pass through unchanged so the
logger's default repr/str conversion still happens.
"""

from __future__ import annotations


def safe_log(value: object) -> object:
    """Return *value* with CR/LF escaped when it is a string.

    Non-string values are returned as-is so the caller's format spec
    (``%s``, ``%d``, ``%r``, ...) still behaves normally.
    """
    if isinstance(value, str):
        return value.replace("\r", "\\r").replace("\n", "\\n")
    return value
