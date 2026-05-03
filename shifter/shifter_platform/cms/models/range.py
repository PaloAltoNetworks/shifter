"""Range-instance tracking models.

``RangeInstance`` records the engine-side range that was hydrated for a
:class:`~cms.models.provisioning.Request` and may carry a reference to the
:class:`~cms.models.assets.AgentConfig` that was deployed inside it. This is
the leaf of the CMS model dependency graph.
"""

from __future__ import annotations

import logging

from django.db import models
from django.utils import timezone

from cms.models.assets import AgentConfig
from shared.enums import TERMINAL_STATUSES

logger = logging.getLogger(__name__)


class ActiveRangeInstanceManager(models.Manager):
    """Manager that filters out soft-deleted RangeInstances."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class RangeInstance(models.Model):
    """Tracks hydrated scenario configs sent to engine.

    After GH issue #446:
    - agent is now FK to AgentConfig (nullable, SET_NULL on delete)
    - range_id remains IntegerField (CMS doesn't own Range model)
    - user_id remains IntegerField (CMS doesn't own User model)

    After GH issue #452:
    - status tracks CMS's view of range lifecycle (from pub/sub events)
    - deleted_at enables soft deletion for history preservation

    After GH issue #416:
    - request FK links to CMS Request (new pattern)
    - range_id is now nullable for new Request-based ranges

    Invariant: Terminal statuses (DESTROYED, FAILED) automatically set deleted_at.
    This is enforced in save() to prevent orphaned terminal records.

    Attributes:
        request: CMS Request that spawned this range (new pattern, nullable).
        range_id: ID of the Range created by engine (legacy, nullable for new ranges).
        scenario_id: Template name used (e.g., 'basic', 'ad_attack_lab')
        user_id: ID of the user who requested creation (IntegerField, not FK)
        agent: AgentConfig used, if any (FK, nullable)
        status: Current lifecycle status (pending, provisioning, ready, etc.)
        range_spec: Hydrated RangeSpec JSON (instance specs, scenario details)
        created_at: When this record was created
        deleted_at: When this record was soft-deleted (null if active)
    """

    request = models.ForeignKey(
        "Request",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="range_instances",
        help_text="CMS Request that spawned this range (new pattern)",
    )
    range_id = models.IntegerField(unique=True, null=True, blank=True)
    scenario_id = models.CharField(max_length=50)
    user_id = models.IntegerField()
    agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="range_instances",
    )
    status = models.CharField(max_length=20, default="pending")
    range_spec = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Managers
    objects = models.Manager()
    active = ActiveRangeInstanceManager()

    class Meta:
        verbose_name = "Range Instance"
        verbose_name_plural = "Range Instances"

    def __str__(self):
        return f"Range {self.range_id}: {self.scenario_id}"

    def save(self, *args, **kwargs):
        """Save with terminal status invariant enforcement.

        When status is set to a terminal value (DESTROYED, FAILED),
        deleted_at is automatically set if not already set.

        If update_fields is specified and we set deleted_at, we add it
        to update_fields to ensure it's persisted.
        """
        # Enforce invariant: terminal status → soft delete
        terminal_values = {s.value for s in TERMINAL_STATUSES}
        if self.status in terminal_values and self.deleted_at is None:
            self.deleted_at = timezone.now()
            logger.debug(
                "RangeInstance %s: auto-setting deleted_at due to terminal status %s",
                self.range_id,
                self.status,
            )

            # If update_fields is specified, add deleted_at to ensure it's saved
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "deleted_at" not in update_fields:
                kwargs["update_fields"] = [*list(update_fields), "deleted_at"]

        super().save(*args, **kwargs)
