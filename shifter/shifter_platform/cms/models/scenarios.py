"""Scenario template and metadata-overlay models.

Scenarios are staff-authored range templates stored in the database. The
``ScenarioMetadata`` overlay stores enabled / staff-only state for both
DB-stored Scenarios and YAML default scenarios shipped under
``cms/scenarios/templates/``.

Has no internal CMS dependencies; only depends on ``settings.AUTH_USER_MODEL``.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from django.conf import settings
from django.db import models

from shared.db import SoftDeleteManager, SoftDeleteMixin, SoftDeleteQuerySet

logger = logging.getLogger(__name__)


class Scenario(SoftDeleteMixin, models.Model):
    """Staff-created scenario template stored in the database.

    Default scenarios ship as YAML in cms/scenarios/templates/ and are
    not stored here. This model is for custom scenarios created by staff
    through the scenario editor.

    The definition field holds the structural parts of the scenario
    (instances, subnets, ngfw flag) as JSON. It is validated against
    ScenarioTemplate on save.

    Attributes:
        id: UUID primary key.
        scenario_id: URL-safe unique identifier (e.g., 'my-custom-lab').
        name: Human-readable display name.
        description: User-facing description.
        definition: JSON with instances, subnets, ngfw fields.
        created_by: Staff user who created this scenario.
        updated_by: Staff user who last updated this scenario.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
        deleted_at: Soft delete timestamp (None = active).
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    scenario_id = models.SlugField(
        max_length=100,
        help_text="URL-safe unique identifier (e.g., 'my-custom-lab')",
    )
    name = models.CharField(max_length=200, help_text="Display name")
    description = models.TextField(help_text="User-facing description")
    definition = models.JSONField(
        help_text="Scenario structure: instances, subnets, ngfw flag",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_scenarios",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_scenarios",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name = "Scenario"
        verbose_name_plural = "Scenarios"
        default_manager_name = "all_objects"
        base_manager_name = "all_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["scenario_id"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_scenario_id",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.scenario_id})"

    def save(self, *args, **kwargs):
        """Save with definition validation."""
        if not self.is_deleted:
            self.validate_definition()
        super().save(*args, **kwargs)

    def to_template(self):
        """Convert to a ScenarioTemplate for validation and hydration.

        Returns:
            ScenarioTemplate instance built from model fields + definition.
        """
        from cms.scenarios.schema import ScenarioTemplate

        return ScenarioTemplate(
            id=self.scenario_id,
            name=self.name,
            description=self.description,
            enabled=True,
            ngfw=self.definition.get("ngfw", False),
            instances=self.definition.get("instances", []),
            subnets=self.definition.get("subnets", []),
        )

    def validate_definition(self):
        """Validate definition against ScenarioTemplate schema.

        Raises:
            pydantic.ValidationError: If definition is invalid.
        """
        self.to_template()


class ScenarioMetadata(models.Model):
    """Staff-configurable overlay for any scenario (default or custom).

    Stores enabled/disabled state and access restrictions. If no metadata
    row exists for a scenario, defaults apply (enabled=True, staff_only=False).

    This model uses scenario_id (string) rather than a FK so it can
    reference both YAML-based defaults and database-stored custom scenarios.

    Attributes:
        scenario_id: Matches the id field of a YAML or DB scenario.
        enabled: Whether the scenario appears in scenario listings.
        staff_only: If True, only staff users can see/use this scenario.
        updated_by: Staff user who last changed this metadata.
        updated_at: Last modification timestamp.
    """

    scenario_id = models.CharField(
        max_length=100,
        unique=True,
        help_text="Scenario ID (matches YAML or DB scenario id)",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Whether this scenario is available for use",
    )
    staff_only = models.BooleanField(
        default=False,
        help_text="If True, only staff users can see/use this scenario",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scenario_id"]
        verbose_name = "Scenario Metadata"
        verbose_name_plural = "Scenario Metadata"

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        access = "staff-only" if self.staff_only else "all users"
        return f"{self.scenario_id}: {status}, {access}"
