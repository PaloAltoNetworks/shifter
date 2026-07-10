"""Range ownership reassignment (CTF spare-range recovery, issue #1018)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction

from cms.exceptions import CMSError
from cms.models import RangeInstance

from ._common import _validate_caller_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def _engine_reassign_range_owner_call(request_id: Any, new_user: User) -> bool:  # NOSONAR
    """Late-bound call so test patches of cms.services.engine_reassign_range_owner apply."""
    from cms import services as _cs

    result: bool = _cs.engine_reassign_range_owner(request_id, new_user)
    return result


def reassign_range_owner(range_instance_pk: int, new_user: User) -> None:
    """Reassign an existing ``RangeInstance``'s ownership to ``new_user``.

    Updates the CMS ``RangeInstance.user_id`` and the owning CMS ``Request.user``,
    then dispatches to the engine service facade so the authoritative
    ``engine.Range.user`` (and its own ``engine.Request.user``) move too --
    terminal/Guacamole resolution (``Range.resolve_active_for_instance`` /
    ``Range.get_active_for_user``) is keyed strictly on ``Range.user``, so both
    sides must move together for the new owner to gain access and the old
    owner to lose it.

    This is CMS/engine authority: callers (e.g.
    ``ctf.services.range.recovery`` via ``ctf.bridges.cms_reassign_range_owner``)
    must route through this function rather than writing ``RangeInstance`` or
    engine rows directly.

    Idempotent: reassigning to the range's current owner is a no-op. The
    whole operation is transactional -- an engine-side rejection rolls back
    the CMS-side field updates too.

    Args:
        range_instance_pk: PK of the RangeInstance to reassign.
        new_user: The user who should become the new owner.

    Raises:
        TypeError: If ``new_user`` is None/invalid, or ``range_instance_pk``
            is not an int.
        ValueError: If ``range_instance_pk`` is negative or ``new_user`` is
            unsaved.
        CMSError: If the range is not found, has no associated request, or
            the engine has no corresponding range for that request.
    """
    _validate_caller_user(new_user, "reassign_range_owner")

    if range_instance_pk is None:
        logger.error("reassign_range_owner called with None range_instance_pk")
        raise TypeError("range_instance_pk cannot be None")

    if not isinstance(range_instance_pk, int):
        logger.error(
            "reassign_range_owner called with invalid range_instance_pk type: %s",
            type(range_instance_pk).__name__,
        )
        msg = f"range_instance_pk must be an int, got {type(range_instance_pk).__name__}"
        raise TypeError(msg)

    if range_instance_pk < 0:
        logger.error("reassign_range_owner called with negative range_instance_pk=%s", range_instance_pk)
        raise ValueError("range_instance_pk must be non-negative")

    try:
        instance = RangeInstance.objects.get(pk=range_instance_pk)
    except RangeInstance.DoesNotExist:
        logger.warning("reassign_range_owner: range not found for range_instance_pk=%s", range_instance_pk)
        raise CMSError(f"Range {range_instance_pk} not found") from None

    if instance.request is None:
        raise CMSError(f"Range {range_instance_pk} has no associated request")

    if instance.user_id == new_user.id:
        logger.info(
            "reassign_range_owner: range_instance_pk=%s already owned by user_id=%s, no-op",
            range_instance_pk,
            new_user.id,
        )
        return

    request_id = instance.request.request_id

    with transaction.atomic():
        instance.user_id = new_user.id
        instance.save(update_fields=["user_id"])

        instance.request.user = new_user
        instance.request.save(update_fields=["user"])

        accepted = _engine_reassign_range_owner_call(request_id, new_user)
        if not accepted:
            logger.warning(
                "reassign_range_owner: no engine range for request_id=%s (range_instance_pk=%s)",
                request_id,
                range_instance_pk,
            )
            raise CMSError(f"Range {range_instance_pk} has no engine range for request {request_id}")

    logger.info(
        "reassign_range_owner: range_instance_pk=%s reassigned to user_id=%s",
        range_instance_pk,
        new_user.id,
    )
