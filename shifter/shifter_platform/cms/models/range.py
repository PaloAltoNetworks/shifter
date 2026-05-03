"""Range-instance tracking models.

``RangeInstance`` records the engine-side range that was hydrated for a
:class:`~cms.models.provisioning.Request` and may carry a reference to the
:class:`~cms.models.assets.AgentConfig` that was deployed inside it. This is
the leaf of the CMS model dependency graph.
"""

from __future__ import annotations

import logging

from django.db import models

from cms.models.assets import AgentConfig
from cms.models.lifecycle import apply_terminal_soft_delete
from shared.db import SoftDeleteManager, SoftDeleteMixin, SoftDeleteQuerySet

logger = logging.getLogger(__name__)


class RangeInstance(SoftDeleteMixin, models.Model):
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

    # ``objects`` is a SoftDeleteManager: every queryset pre-filters to
    # non-deleted rows. ``all_objects`` is the unfiltered manager, for
    # admin / restore / audit code that needs to see deleted rows.
    objects = SoftDeleteManager()
    all_objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        verbose_name = "Range Instance"
        verbose_name_plural = "Range Instances"
        base_manager_name = "all_objects"

    def __str__(self):
        return f"Range {self.range_id}: {self.scenario_id}"

    def save(self, *args, **kwargs):
        """Save with terminal-status soft-delete invariant enforcement.

        Delegates the invariant to
        :func:`~cms.models.lifecycle.apply_terminal_soft_delete` and emits a
        debug log when the helper applies the soft-delete.
        """
        if apply_terminal_soft_delete(self, kwargs):
            logger.debug(
                "RangeInstance %s: auto-setting deleted_at due to terminal status %s",
                self.range_id,
                self.status,
            )
        super().save(*args, **kwargs)
