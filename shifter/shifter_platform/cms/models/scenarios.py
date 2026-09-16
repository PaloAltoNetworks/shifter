"""RAES package-source and catalog metadata-overlay models."""

from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.db import models


class ScenarioMetadata(models.Model):
    """Staff-configurable overlay for a RAES catalog scenario.

    Stores enabled/disabled state and access restrictions. If no metadata
    row exists for a scenario, defaults apply (enabled=True, staff_only=False).

    This model uses scenario_id (string) rather than a FK so it can
    reference the stable RAES package-source identifier.

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
        help_text="Stable RAES package-source scenario ID",
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
        """Model options: ordering and human-readable names."""

        ordering = ["scenario_id"]
        verbose_name = "Scenario Metadata"
        verbose_name_plural = "Scenario Metadata"

    def __str__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        access = "staff-only" if self.staff_only else "all users"
        return f"{self.scenario_id}: {status}, {access}"


class RaesPackageSource(models.Model):
    """Provenance-only source record for an RAES package-backed catalog entry.

    Keyed by ``scenario_id`` (a string, like :class:`ScenarioMetadata`) so it can
    join the unified catalog projection beside YAML defaults and DB customs. It
    stores *references and provenance only* — never raw RAES SDL, imported module
    bodies, generated content, hydrated runtime specs, flags, credentials,
    tokens, or runtime config (enforced by
    :func:`shared.schemas.raes_package_source.validate_package_source`).

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
        help_text="Catalog id for this RAES package-source entry",
    )
    source_kind = models.CharField(
        max_length=16,
        choices=SourceKind.choices,
        default=SourceKind.REPO,
        help_text="Where the package is resolved from (repo-managed or object storage)",
    )
    contract_kind = models.CharField(
        max_length=32,
        help_text="Package contract discriminator (e.g. 'raes')",
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
        verbose_name = "RAES Package Source"
        verbose_name_plural = "RAES Package Sources"

    def __str__(self) -> str:
        return f"{self.scenario_id} ({self.contract_kind}/{self.contract_profile})"

    def save(self, *args, **kwargs) -> None:
        """Persist after enforcing the provenance-only contract.

        Raises:
            shared.schemas.raes_package_source.RaesPackageSourceError: if any
                field or the provenance JSON violates the provenance-only shape.
        """
        from shared.schemas.raes_package_source import PackageSourceRecord, validate_package_source

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
        :func:`cms.scenarios.registry._raes_launchable`; do not treat this
        conformance signal as launchability on its own.
        """
        return self.conformance_status == self.ConformanceStatus.PASSED


class ScenarioModelNeeds(models.Model):
    """Staff-authored per-pack scenario→model-need binding (PLAT-202).

    Shifter-owned, digest-bound overlay that rides the runtime pack lifecycle
    (tenant/staff managed), keyed by ``scenario_id`` like :class:`ScenarioMetadata`.
    It is deliberately NOT on :class:`RaesPackageSource` (which is provenance-only)
    and NOT in the deploy-time mounted model-access catalog: a newly registered
    model-requiring pack must be admissible without an operator catalog redeploy,
    so the need follows the pack, while the catalog keeps owning the deployment
    policy (profiles/shards/sharing) the need references.

    ``needs`` maps ``workload_role`` to a :class:`shared.model_access.ScenarioNeed`
    payload. ``authored_package_digest`` is the pack content digest the needs were
    authored against; admission verifies the registered pack's current digest
    against it so a re-registered pack cannot inherit a stale binding.
    """

    scenario_id = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Catalog id of the RAES package these model needs bind to",
    )
    authored_package_digest = models.CharField(
        max_length=71,
        help_text="Pack content digest the needs were authored against ('sha256:<64 hex>')",
    )
    needs = models.JSONField(
        help_text="Map of workload_role to a shared.model_access.ScenarioNeed payload",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options: ordering and human-readable names."""

        ordering = ["scenario_id"]
        verbose_name = "Scenario Model Needs"
        verbose_name_plural = "Scenario Model Needs"

    def __str__(self) -> str:
        return f"{self.scenario_id}: {len(self.needs or {})} workload need(s)"

    def save(self, *args, **kwargs) -> None:
        """Persist after validating the ``{workload_role: ScenarioNeed}`` payload.

        Raises:
            shared.model_access.catalog.ContractError: if any entry is malformed,
                its key does not match its ``workload_role``, or its
                ``scenario_digest`` does not equal ``authored_package_digest``.
        """
        from cms.scenarios.model_needs import validate_scenario_model_needs

        self.needs = validate_scenario_model_needs(self.authored_package_digest, self.needs)
        super().save(*args, **kwargs)
