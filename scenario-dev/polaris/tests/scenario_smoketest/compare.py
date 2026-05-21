"""Produced-vs-configured value comparison with flag redaction.

Existing per-asset smoketests hardcode and print flag values. This harness
must not: the default report names a challenge and a match/mismatch verdict,
and any value that does appear is reduced to a short stable digest. A failed
comparison must not leak either the produced or the configured value.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


def redact(value: str | None) -> str:
    """Reduce a flag/answer value to a short, stable, non-reversible token."""
    if value is None:
        return "<none>"
    if value == "":
        return "<empty>"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


@dataclass(frozen=True)
class Comparison:
    """Outcome of comparing a produced value against the expected value."""

    status: str  # "pass" | "fail"
    detail: str


def compare(produced: str | None, expected: str | None, kind: str) -> Comparison:
    """Compare a produced value against the expected value for ``kind``.

    ``kind`` is ``"flag"`` (compare against the CTFd-configured static flag)
    or ``"answer"`` (compare against the canonical submit-answer recorded by
    the adapter). Detail strings carry only redacted digests, never raw values.
    """
    if kind not in ("flag", "answer"):
        raise ValueError(f"unknown comparison kind: {kind!r}")

    if produced is None:
        return Comparison("fail", "adapter produced no value from the hint path")

    if expected is None:
        if kind == "flag":
            return Comparison(
                "fail", "no configured static flag on the board to compare against"
            )
        return Comparison("fail", "adapter declares no expected answer")

    if produced == expected:
        return Comparison("pass", f"match ({redact(produced)})")

    return Comparison(
        "fail",
        f"mismatch: produced {redact(produced)} != expected {redact(expected)}",
    )
