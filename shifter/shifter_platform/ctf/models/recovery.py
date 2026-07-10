"""CTFRangeRecovery — destroyed-participant-range recovery workflow record.

Split out (rather than folded into ``team.py`` or overloaded onto
``CTFParticipant.range_status``) per the #1018 preflight design note: range
lifecycle status and recovery-operation workflow status are deliberately
kept distinct so neither has to encode the other's states.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from ctf.enums import (
    RecoveryFailureCategory,
    RecoveryPhase,
    RecoveryStrategy,
)

from ._base import CTFBaseModel


class CTFRangeRecovery(CTFBaseModel):
    """Recovery intent and checkpointed progress for one participant range.

    Records a single "recover this participant's destroyed range" operation:
    which replacement strategy was chosen and how far the (idempotent,
    retry-safe) workflow has progressed. The old range is always destroyed
    (no disposition/forensics concept -- owner decision, #1018 revised plan).

    Attributes:
        event: The CTF event the participant belongs to.
        participant: The participant whose range is being recovered.
        old_range_instance_id: The pre-recovery ``RangeInstance.pk``.
        strategy: How the replacement range is obtained
            (:class:`~ctf.enums.RecoveryStrategy`).
        replacement_range_instance_id: The replacement ``RangeInstance.pk``,
            once known.
        replacement_request_id: The CMS provisioning request id for a
            ``rebuild`` replacement, once known.
        phase: Checkpointed workflow progress
            (:class:`~ctf.enums.RecoveryPhase`). Observability only —
            :mod:`ctf.services.range.recovery` resumes retries from recorded
            replacement/teardown state, not from this field, so a stale
            ``failed`` value never blocks re-entry.
        failure_category: Authored failure reason
            (:class:`~ctf.enums.RecoveryFailureCategory`) when ``phase`` is
            ``failed``.
        created_by: Operator who initiated the recovery.
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="range_recoveries",
        help_text="Event the participant belongs to",
    )
    participant = models.ForeignKey(
        "CTFParticipant",
        on_delete=models.CASCADE,
        related_name="range_recoveries",
        help_text="Participant whose range is being recovered",
    )
    old_range_instance_id = models.IntegerField(
        help_text="Pre-recovery RangeInstance.pk",
    )
    strategy = models.CharField(
        max_length=20,
        choices=RecoveryStrategy.choices(),
        help_text="Replacement strategy",
    )
    replacement_range_instance_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Replacement RangeInstance.pk, once known",
    )
    replacement_request_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="CMS provisioning request id for a rebuild replacement",
    )
    phase = models.CharField(
        max_length=24,
        choices=RecoveryPhase.choices(),
        default=RecoveryPhase.INITIATED.value,
        db_index=True,
        help_text="Checkpointed workflow progress",
    )
    # DJ001 is intentionally suppressed (same rationale as
    # ``CTFParticipant.cognito_sub``): failure_category is genuinely absent
    # (not "empty") for every non-failed recovery, so null=True is the correct
    # "no value yet" sentinel rather than an empty-string stand-in.
    failure_category = models.CharField(  # noqa: DJ001
        max_length=32,
        choices=RecoveryFailureCategory.choices(),
        null=True,  # NOSONAR
        blank=True,
        help_text="Authored failure category when phase=failed",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ctf_range_recoveries_created",
        help_text="Operator who initiated the recovery",
    )

    class Meta:
        """Django model metadata."""

        verbose_name = "CTF Range Recovery"
        verbose_name_plural = "CTF Range Recoveries"
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "old_range_instance_id", "strategy"],
                name="ctf_rangerecovery_unique_intent",
            ),
        ]
        indexes = [
            models.Index(fields=["event", "phase"]),
            models.Index(fields=["participant", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Recovery({self.participant_id}, {self.strategy}, {self.phase})"
