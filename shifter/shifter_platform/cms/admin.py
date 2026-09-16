"""CMS admin configuration."""

from typing import Any

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError as DjangoValidationError

from cms.models import AgentConfig, OperatingSystem, ScenarioMetadata, ScenarioModelNeeds, Subnet


@admin.register(OperatingSystem)
class OperatingSystemAdmin(admin.ModelAdmin):
    """Admin for operating system catalog entries."""

    list_display = ("name", "slug", "extensions")
    search_fields = ("name", "slug")
    ordering = ("name",)


@admin.register(AgentConfig)
class AgentConfigAdmin(admin.ModelAdmin):
    """Admin for user-uploaded agent config assets."""

    list_display = (
        "name",
        "user",
        "os",
        "original_filename",
        "created_at",
        "deleted_at",
    )
    list_filter = ("os", "deleted_at", "created_at")
    search_fields = ("name", "user__email", "original_filename")
    raw_id_fields = ("user",)
    readonly_fields = ("s3_key", "sha256_hash", "file_size_bytes", "created_at")


@admin.register(Subnet)
class SubnetAdmin(admin.ModelAdmin):
    """Admin for provisioned subnet records."""

    list_display = ("name", "request", "status", "created_at", "deleted_at")
    list_filter = ("status", "deleted_at", "created_at")
    search_fields = ("name", "id")
    readonly_fields = ("id", "created_at", "deleted_at")


@admin.register(ScenarioMetadata)
class ScenarioMetadataAdmin(admin.ModelAdmin):
    """Admin for per-scenario metadata overrides."""

    list_display = ("scenario_id", "enabled", "staff_only", "updated_by", "updated_at")
    list_filter = ("enabled", "staff_only")
    search_fields = ("scenario_id",)
    raw_id_fields = ("updated_by",)
    readonly_fields = ("updated_at",)


class ScenarioModelNeedsForm(forms.ModelForm):
    """Admin form that surfaces overlay validation as correctable field errors.

    The model's ``save`` guards persistence with the same validator, but a
    workload-role/key mismatch or an authored-digest mismatch is ordinary
    authoring input, not a server fault — translate the bounded ContractError into
    a form error so the admin redisplays it instead of raising HTTP 500 (PLAT-202).
    """

    class Meta:
        """Bind the form to ScenarioModelNeeds with an explicit field set."""

        model = ScenarioModelNeeds
        fields = ("scenario_id", "authored_package_digest", "needs", "updated_by")

    def clean(self) -> dict[str, Any]:
        """Validate the ``needs`` payload against the authored digest."""
        cleaned: dict[str, Any] = super().clean() or {}
        digest = cleaned.get("authored_package_digest")
        needs = cleaned.get("needs")
        if digest is not None and needs is not None:
            from cms.scenarios.model_needs import validate_scenario_model_needs
            from shared.model_access.catalog import ContractError

            try:
                validate_scenario_model_needs(digest, needs)
            except ContractError as exc:
                raise DjangoValidationError(f"Invalid scenario model needs ({exc.code})") from exc
        return cleaned


@admin.register(ScenarioModelNeeds)
class ScenarioModelNeedsAdmin(admin.ModelAdmin):
    """Staff authoring surface for the per-pack scenario->model-need overlay (PLAT-202).

    The ``needs`` payload is validated by :class:`ScenarioModelNeedsForm` (field
    error) and again by the model on save (persistence guard).
    """

    form = ScenarioModelNeedsForm
    list_display = ("scenario_id", "authored_package_digest", "updated_by", "updated_at")
    search_fields = ("scenario_id",)
    raw_id_fields = ("updated_by",)
    readonly_fields = ("updated_at",)
