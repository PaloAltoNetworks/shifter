"""CTF decoupling bridge: fire range_status_changed signal for CTF receivers."""

from __future__ import annotations

import logging

from cms.signals import range_status_changed

logger = logging.getLogger(__name__)


def notify_ctf_range_status(
    range_instance_id: int,
    new_status: str,
    previous_status: str,
    cleanup_verified: bool = False,
) -> None:
    """Fire the CMS range_status_changed signal.

    Any layer that depends on CMS (e.g. CTF) can register receivers
    for this signal to react to range status changes.

    ``cleanup_verified`` (#2086, ADR-063-R4/R5) reports whether durable scoped
    provider inventory/readback evidence confirms every owned resource is gone. A
    terminal ``DESTROYED`` status without that evidence is not proof of absence, so
    CTF receivers must retain capacity and linkage until it is True.
    """
    try:
        range_status_changed.send(
            sender=None,
            range_instance_id=range_instance_id,
            new_status=new_status,
            previous_status=previous_status,
            cleanup_verified=cleanup_verified,
        )
    except Exception:
        logger.exception(
            "Failed to send range status change signal: range_instance_id=%s status=%s",
            range_instance_id,
            new_status,
        )
