"""Bounded, non-secret evidence rendering.

The report carries identifiers and provenance only. It deliberately never
contains a session or CSRF cookie, an ID token, a Guacamole URL or token, an SSH
key, a password, a private address, raw terminal output, a raw response body, or
a traceback — every check's ``detail`` is authored text chosen at the call site.

``redact`` is a belt-and-braces filter over operator-supplied free text (an
environment label, a run note), not a licence to pass captured material through.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from range_functional_smoke.profile import RunProfile
from range_functional_smoke.results import REQUIRED_CHECKS, RunResults

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(sessionid|csrftoken|token|password|secret|authorization|id_token)\b\s*[=:]\s*\S+"),
    re.compile(r"(?i)\bBearer\s+\S+"),
    # Private RFC 1918 addresses are excluded from evidence by contract.
    re.compile(r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
)

_REDACTED = "[redacted]"


def redact(text: str) -> str:
    """Replace anything that looks like credential material or a private address."""
    cleaned = str(text)
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub(_REDACTED, cleaned)
    return cleaned


def render(results: RunResults, profile: RunProfile, *, run_id: str) -> str:
    """Render the operator-facing report for one run."""
    host = urlparse(profile.origin).hostname or "?"
    lines = [
        "# Range functional smoke",
        "",
        f"- run: `{run_id}`",
        f"- environment: `{redact(profile.environment)}`",
        f"- target: `{host}`",
        f"- logical target: role `{profile.target_role}`, Guacamole protocol `{profile.protocol.value}`",
        f"- verdict: **{results.verdict().upper()}**",
        "",
        "| check | status | ms | detail |",
        "| --- | --- | --- | --- |",
    ]

    latest = results.by_code()
    for code in sorted(latest, key=lambda item: item.value):
        result = latest[code]
        required = " (required)" if code in REQUIRED_CHECKS else ""
        lines.append(
            f"| `{code.value}`{required} | {result.status.value} | {result.duration_ms} | {redact(result.detail)} |"
        )

    missing = sorted(code.value for code in results.missing())
    if missing:
        lines += ["", f"Required checks that never ran (counted as failures): {', '.join(missing)}."]

    if not results.passed:
        lines += [
            "",
            "A Guacamole bootstrap that succeeded without a connected session is **not** a pass: "
            "it proves only that the server minted a credential.",
        ]
    return "\n".join(lines) + "\n"
