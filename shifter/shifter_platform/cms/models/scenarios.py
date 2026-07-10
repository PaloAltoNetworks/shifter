"""Scenario template and metadata-overlay models.

Scenarios are staff-authored range templates stored in the database. The
``ScenarioMetadata`` overlay stores enabled / staff-only state for both
DB-stored Scenarios and YAML default scenarios shipped under
``cms/scenarios/templates/``.

Has no internal CMS dependencies; only depends on ``settings.AUTH_USER_MODEL``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from django.conf import settings
from django.db import models

from shared.db import SoftDeleteManager, SoftDeleteMixin, SoftDeleteQuerySet

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cms.scenarios.schema import AnyScenarioTemplate


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

    def to_template(self) -> AnyScenarioTemplate:
        """Convert to a validated scenario template for hydration.

        Returns:
            ScenarioTemplate or CTFScenarioTemplate built from model fields + definition.
        """
        from pydantic import TypeAdapter

        from cms.scenarios.schema import AnyScenarioTemplate

        payload = {
            "id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "enabled": True,
            **self.definition,
        }
        if "scenario_type" not in payload:
            payload["scenario_type"] = "demo"
        return TypeAdapter(AnyScenarioTemplate).validate_python(payload)

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


class AcesPackageSource(models.Model):
    """Provenance-only source record for an ACES package-backed catalog entry.

    Keyed by ``scenario_id`` (a string, like :class:`ScenarioMetadata`) so it can
    join the unified catalog projection beside YAML defaults and DB customs. It
    stores *references and provenance only* — never raw ACES SDL, imported module
    bodies, generated content, hydrated runtime specs, flags, credentials,
    tokens, or runtime config (enforced by
    :func:`shared.schemas.aces_package_source.validate_package_source`).

    Access (enabled / staff_only) remains governed by :class:`ScenarioMetadata`;
    this model adds no duplicate access flags. Launchability is derived from
    conformance readiness (:attr:`is_launchable`), independent of access.
    """

    class SourceKind(models.TextChoices):
        """How the package is resolved: repo-managed or object storage."""

        REPO = "repo", "Repository-managed"
        OBJECT = "object", "Object storage"

    class ConformanceStatus(models.TextChoices):
        """Conformance readiness of the package for its claimed profile."""

        PENDING = "pending", "Pending"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    scenario_id = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Catalog id for this ACES package-source entry",
    )
    source_kind = models.CharField(
        max_length=16,
        choices=SourceKind.choices,
        default=SourceKind.REPO,
        help_text="Where the package is resolved from (repo-managed or object storage)",
    )
    contract_kind = models.CharField(
        max_length=32,
        help_text="Package contract discriminator (e.g. 'aces')",
    )
    contract_profile = models.CharField(
        max_length=128,
        help_text="Contract profile the package claims (e.g. 'shifter')",
    )
    package_ref = models.CharField(
        max_length=512,
        help_text="Repo-relative path or object-storage key for the package root",
    )
    package_version = models.CharField(
        max_length=128,
        help_text="Immutable package version or ref",
    )
    package_digest = models.CharField(
        max_length=71,
        help_text="Package content digest ('sha256:<64 hex>')",
    )
    lock_ref = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Repo-relative path or object-storage key for the lock artifact",
    )
    lock_digest = models.CharField(
        max_length=71,
        blank=True,
        default="",
        help_text="Lock artifact digest ('sha256:<64 hex>')",
    )
    provenance = models.JSONField(
        default=dict,
        blank=True,
        help_text="Bounded provenance references (repo/commit/tool/report); no secrets or bodies",
    )
    conformance_status = models.CharField(
        max_length=16,
        choices=ConformanceStatus.choices,
        default=ConformanceStatus.PENDING,
        help_text="Conformance readiness for the claimed profile",
    )
    conformance_report_ref = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Reference to a conformance report (not its contents)",
    )
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options: ordering and human-readable names."""

        ordering = ["scenario_id"]
        verbose_name = "ACES Package Source"
        verbose_name_plural = "ACES Package Sources"

    def __str__(self) -> str:
        return f"{self.scenario_id} ({self.contract_kind}/{self.contract_profile})"

    def save(self, *args, **kwargs) -> None:
        """Persist after enforcing the provenance-only contract.

        Raises:
            shared.schemas.aces_package_source.AcesPackageSourceError: if any
                field or the provenance JSON violates the provenance-only shape.
        """
        from shared.schemas.aces_package_source import PackageSourceRecord, validate_package_source

        self.provenance = validate_package_source(
            PackageSourceRecord(
                source_kind=self.source_kind,
                contract_kind=self.contract_kind,
                contract_profile=self.contract_profile,
                package_ref=self.package_ref,
                package_version=self.package_version,
                package_digest=self.package_digest,
                conformance_status=self.conformance_status,
                lock_ref=self.lock_ref,
                lock_digest=self.lock_digest,
                conformance_report_ref=self.conformance_report_ref,
                provenance=self.provenance,
            )
        )
        super().save(*args, **kwargs)

    @property
    def is_conformance_passed(self) -> bool:
        """Whether this package source has passed conformance for its profile.

        This is only ONE input to launchability. The authoritative launchability
        decision (supported source/contract/profile, valid refs/digests,
        no-shadow, and conformance) lives in
        :func:`cms.scenarios.registry._aces_launchable`; do not treat this
        conformance signal as launchability on its own.
        """
        return self.conformance_status == self.ConformanceStatus.PASSED
