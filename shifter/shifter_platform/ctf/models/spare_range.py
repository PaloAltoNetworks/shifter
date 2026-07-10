"""CTFSpareRange — prewarmed event spare-range pool (issue #1018).

Formalizes the previously hand-made "fake user owns a spare range" process:
each spare range is owned by a dedicated, auto-created managed system user
(never a :class:`~ctf.models.CTFParticipant`) until it is consumed, at which
point ownership transfers to the recovering participant and the freed
managed user is cleaned up. See :mod:`ctf.services.range.spares`.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from ctf.enums import SpareRangeStatus

from ._base import CTFBaseModel


class CTFSpareRange(CTFBaseModel):
    """A prewarmed range held in reserve for one CTF event's recovery pool.

    Attributes:
        event: The event this spare belongs to (spares are strictly
            event-scoped -- never shared across events).
        owner_user: The dedicated managed system user that owns the
            underlying CMS range while it sits unconsumed in the pool.
            Cleared (``SET_NULL``) once the managed user is deleted after
            consumption, so the historical record survives.
        range_instance_id: The CMS ``RangeInstance.pk``, once resolved.
        request_id: The CMS provisioning request id.
        status: Pool lifecycle status (:class:`~ctf.enums.SpareRangeStatus`).
        consumed_by: The participant this spare was assigned to, if consumed.
        consumed_at: When this spare was consumed.
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="spare_ranges",
        help_text="Event this spare range belongs to",
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ctf_spare_ranges_owned",
        help_text="Managed system user that owns the range while unconsumed",
    )
    range_instance_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="CMS RangeInstance.pk, once known",
    )
    request_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="CMS provisioning request id",
    )
    status = models.CharField(
        max_length=20,
        choices=SpareRangeStatus.choices(),
        default=SpareRangeStatus.PROVISIONING.value,
        db_index=True,
        help_text="Pool lifecycle status",
    )
    consumed_by = models.ForeignKey(
        "CTFParticipant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consumed_spare_ranges",
        help_text="Participant this spare was assigned to, if consumed",
    )
    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this spare was consumed",
    )

    class Meta:
        """Django model metadata."""

        verbose_name = "CTF Spare Range"
        verbose_name_plural = "CTF Spare Ranges"
        indexes = [
            models.Index(fields=["event", "status"]),
        ]

    def __str__(self) -> str:
        return f"SpareRange({self.event_id}, {self.status})"
