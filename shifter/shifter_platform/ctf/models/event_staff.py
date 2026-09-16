"""Delegated event-staff assignments split from the core event model."""

from django.conf import settings
from django.db import models

from ctf.enums import EventStaffRole

from ._base import CTFBaseModel
from .event import CTFEvent


class CTFEventStaff(CTFBaseModel):
    """A delegated staff assignment on one event (CTF-607, #1922).

    Grants a second organizer-tier user a role-scoped slice of event
    management. The event owner retains every capability and authority-topology
    operations remain owner-only.
    """

    event = models.ForeignKey(
        CTFEvent,
        on_delete=models.CASCADE,
        related_name="staff",
        help_text="Event this staff assignment is scoped to",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ctf_staff_roles",
        help_text="Platform user holding the staff role",
    )
    role = models.CharField(
        max_length=16,
        choices=EventStaffRole.choices(),
        help_text=(
            "Delegated role: moderator (participants, announcements), judge "
            "(submissions, awards), or co_organizer (all operational capabilities)"
        ),
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_event_staff"
        ordering = ["created_at"]
        verbose_name = "CTF Event Staff"
        verbose_name_plural = "CTF Event Staff"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "user"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_ctf_event_staff_user",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=[role.value for role in EventStaffRole]),
                name="ctf_event_staff_role_valid",
            ),
        ]

    def __str__(self) -> str:
        """Return the assignment as user@event with role."""
        return f"{self.user_id}@{self.event_id}: {self.role}"
