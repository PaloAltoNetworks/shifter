"""Range resume entrypoints (by range_id and by request_id).

Thin wrappers over the shared, parameterized ``_range_lifecycle`` helper. The
public function names live here so the ``cms.services`` facade re-exports are
unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._range_lifecycle import RESUME_OP, run_by_instance_pk, run_by_request_id

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def resume_range(user: User, range_instance_pk: int) -> None:
    """Resume a paused range.

    Fetches RangeInstance, verifies ownership, updates CMS status to RESUMING,
    then delegates to engine.services.resume_range.

    Args:
        user: User requesting resume
        range_instance_pk: PK of the RangeInstance to resume

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or range_instance_pk is invalid type
        ValueError: If user has no ID (unsaved) or range_instance_pk is invalid
        CMSError: If range not found, not owned by user, or not in resumable state
    """
    run_by_instance_pk(user, range_instance_pk, RESUME_OP)


def resume_range_by_request_id(user: User, request_id: str) -> None:
    """Resume a paused range by request_id.

    Fetches RangeInstance by request_id, verifies ownership, then delegates
    to engine.services.resume_range.

    Args:
        user: User requesting resume
        request_id: UUID string of the request

    Returns:
        None

    Raises:
        TypeError: If user is None or invalid type
        CMSError: If range not found, not owned by user, or not in resumable state
    """
    run_by_request_id(user, request_id, RESUME_OP)
