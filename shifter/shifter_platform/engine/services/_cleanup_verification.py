"""Record and read scoped provider inventory/readback evidence (#2086, ADR-063-R4/R5).

The provisioner inventories owned provider resources after teardown; the Engine
applier records that evidence here. Verified terminal cleanup, retry-binding
pruning, and CTF capacity/linkage release gate on the latest evidence being
``VERIFIED_ABSENT``. A later re-inventory supersedes the current outcome (a
residual discovered later corrects the projection) without rewriting history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

__all__ = [
    "CleanupVerificationView",
    "is_cleanup_verified_absent",
    "latest_cleanup_verification",
    "record_cleanup_verification",
]


@dataclass(frozen=True)
class CleanupVerificationView:
    """Read-only projection of the latest cleanup verification for a request."""

    outcome: str
    scope: dict[str, Any]
    residual_categories: list[dict[str, Any]]
    observed_at: datetime


def latest_cleanup_verification(request_id: str | UUID) -> CleanupVerificationView | None:
    """Return the most recent cleanup verification for a request, or ``None``."""
    from engine.models import RangeCleanupVerification

    row = RangeCleanupVerification.objects.filter(request_id=UUID(str(request_id))).order_by("-created_at").first()
    if row is None:
        return None
    return CleanupVerificationView(
        outcome=str(row.outcome),
        scope=dict(row.scope or {}),
        residual_categories=list(row.residual_categories or []),
        observed_at=row.observed_at,
    )


def is_cleanup_verified_absent(request_id: str | UUID) -> bool:
    """True only when the latest inventory/readback confirmed every owned resource absent."""
    from engine.models import CleanupVerificationOutcome

    view = latest_cleanup_verification(request_id)
    return view is not None and view.outcome == CleanupVerificationOutcome.VERIFIED_ABSENT.value


def record_cleanup_verification(
    *,
    request_id: str | UUID,
    operation_id: str | UUID,
    outcome: str,
    scope: dict[str, Any],
    residual_categories: list[dict[str, Any]] | None,
    observed_at: datetime,
) -> None:
    """Append one scoped provider inventory/readback observation."""
    from engine.models import RangeCleanupVerification

    RangeCleanupVerification.objects.create(
        request_id=UUID(str(request_id)),
        operation_id=UUID(str(operation_id)),
        outcome=outcome,
        scope=scope,
        residual_categories=list(residual_categories or []),
        observed_at=observed_at,
    )
