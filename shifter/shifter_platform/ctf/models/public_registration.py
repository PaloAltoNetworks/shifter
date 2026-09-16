"""Pending public registration intake owned by the CTF domain (#2157)."""

from __future__ import annotations

from django.db import models

from ctf.enums import PublicRegistrationDisposition

from ._base import CTFBaseModel


class CTFPublicRegistrationRequest(CTFBaseModel):
    """Minimal untrusted intake awaiting an organizer disposition.

    This row deliberately is not a participant, invitation, user, workspace
    membership, seat, or provisioning request.
    """

    event = models.ForeignKey(
        "ctf.CTFEvent",
        on_delete=models.CASCADE,
        related_name="public_registration_requests",
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(max_length=254)
    disposition = models.CharField(
        max_length=16,
        choices=PublicRegistrationDisposition.choices(),
        default=PublicRegistrationDisposition.PENDING.value,
        db_index=True,
    )
    dispositioned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Bound duplicate intake and organizer queue scans in the database."""

        db_table = "ctf_public_registration_request"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["event", "disposition", "created_at"],
                name="ctf_pubreg_queue_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                models.F("event"),
                models.functions.Lower("email"),
                condition=models.Q(deleted_at__isnull=True),
                name="ctf_pubreg_live_event_email_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(disposition__in=[status.value for status in PublicRegistrationDisposition]),
                name="ctf_pubreg_disposition_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        disposition=PublicRegistrationDisposition.PENDING.value,
                        dispositioned_at__isnull=True,
                    )
                    | models.Q(
                        disposition__in=[
                            PublicRegistrationDisposition.APPROVED.value,
                            PublicRegistrationDisposition.REJECTED.value,
                        ],
                        dispositioned_at__isnull=False,
                    )
                ),
                name="ctf_pubreg_disposition_time",
            ),
        ]

    def clean(self) -> None:
        """Normalize the only two public-input fields before validation/save."""
        self.name = self.name.strip()
        self.email = self.email.strip().lower()

    def __str__(self) -> str:
        """Return a PII-free operator representation."""
        return f"{self.id}@{self.event_id}:{self.disposition}"
