"""Catalog and reference-data models.

System-defined types (CredentialType, InstanceType, AppType) plus the
operating-system reference table and the agent-type enum. These have no
internal dependencies on other CMS submodules and sit at the leaf of the
import graph: assets, provisioning, and range submodules import from here.
"""

from __future__ import annotations

import logging

from django.db import models

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Abstract Base Models
# -----------------------------------------------------------------------------


class CatalogBase(models.Model):
    """Abstract base for catalog entities (system-defined types).

    Catalog entities are reference data that define available types,
    not user-owned instances. Examples: CredentialType, ScenarioType.

    The ``spec_class`` field declares the dotted path to the Pydantic spec
    class used to validate per-row payloads; it is owned by the abstract
    base because every concrete catalog needs it (and ``get_spec_class`` /
    ``validate_data`` here read it).

    Attributes:
        name: Human-readable name for display.
        slug: URL-safe identifier for lookups.
        created_at: When this catalog entry was created.
        spec_class: Dotted path to the Pydantic spec class for validation.
    """

    name = models.CharField(max_length=100, help_text="Display name")
    slug = models.SlugField(max_length=50, unique=True, help_text="URL-safe identifier")
    created_at = models.DateTimeField(auto_now_add=True)
    spec_class = models.CharField(
        max_length=255,
        help_text="Dotted path to Pydantic spec class",
    )

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    def get_spec_class(self):
        """Load and return the Pydantic spec class.

        Requires subclass to define a `spec_class` CharField.

        Returns:
            The Pydantic model class for validating data.

        Raises:
            AttributeError: If subclass doesn't define spec_class.
            ImportError: If the spec_class path is invalid.
        """
        from importlib import import_module

        module_path, class_name = self.spec_class.rsplit(".", 1)
        module = import_module(module_path)
        return getattr(module, class_name)

    def validate_data(self, data: dict) -> dict:
        """Validate data against this type's spec.

        Args:
            data: Raw data to validate.

        Returns:
            Validated and normalized data dict.

        Raises:
            pydantic.ValidationError: If data doesn't match the spec.
        """
        spec_class = self.get_spec_class()
        validated = spec_class.model_validate(data)
        return validated.model_dump()


# -----------------------------------------------------------------------------
# Reference Models
# -----------------------------------------------------------------------------


def normalize_file_extension(extension: str) -> str:
    """Lowercase ``extension`` and prefix it with a leading dot if missing.

    Pure function — no I/O. Lets callers (and tests) normalise extensions
    without touching the database.
    """
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    return ext


class OperatingSystemQuerySet(models.QuerySet["OperatingSystem"]):
    """Custom queryset for :class:`OperatingSystem` lookups."""

    def for_extension(self, extension: str) -> OperatingSystem | None:
        """Return the first OperatingSystem whose ``extensions`` list contains ``extension``.

        Accepts the extension with or without a leading dot; case is normalised
        via :func:`normalize_file_extension`. Returns ``None`` when no row matches.
        """
        normalized = normalize_file_extension(extension)
        for os in self:
            if normalized in os.extensions:
                return os
        return None


class OperatingSystem(models.Model):
    """Reference table for supported operating systems.

    Used for categorizing file assets by their target platform.
    """

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    extensions = models.JSONField(default=list, help_text="File extensions that map to this OS (e.g., ['.msi'])")

    objects = OperatingSystemQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name = "Operating System"
        verbose_name_plural = "Operating Systems"

    def __str__(self):
        return self.name

    @classmethod
    def get_for_extension(cls, extension: str):
        """Find the OS that matches a given file extension.

        Thin wrapper around :meth:`OperatingSystemQuerySet.for_extension`,
        kept for callers that previously used the classmethod entry point.

        Args:
            extension: File extension with or without leading dot (e.g., '.msi' or 'msi')

        Returns:
            OperatingSystem instance if found, None otherwise
        """
        return cls.objects.for_extension(extension)


# -----------------------------------------------------------------------------
# Type Catalogs
# -----------------------------------------------------------------------------


class CredentialType(CatalogBase):
    """Catalog of credential types.

    Type Object pattern: types are data rows, not code enums. Each row
    defines a credential type; ``spec_class`` (inherited from
    :class:`CatalogBase`) points at the Pydantic spec for per-credential
    data validation, e.g. ``'shared.schemas.SCMCredentialSpec'``.
    """

    class Meta:
        verbose_name = "Credential Type"
        verbose_name_plural = "Credential Types"


class InstanceType(CatalogBase):
    """Catalog of instance types (container, vm, etc).

    Type Object pattern: types are data rows, not code enums. ``spec_class``
    (inherited from :class:`CatalogBase`) points at the Pydantic spec for
    per-instance data validation.
    """

    class Meta:
        verbose_name = "Instance Type"
        verbose_name_plural = "Instance Types"


class AppType(CatalogBase):
    """Catalog of app types (os, ngfw, agent, other).

    Type Object pattern: types are data rows, not code enums. ``spec_class``
    (inherited from :class:`CatalogBase`) points at the Pydantic spec for
    per-app data validation.
    """

    class Meta:
        verbose_name = "App Type"
        verbose_name_plural = "App Types"


# -----------------------------------------------------------------------------
# Agent Type Enum
# -----------------------------------------------------------------------------


class AgentType(models.TextChoices):
    """Types of agents that can be uploaded."""

    XDR = "xdr", "XDR/XSIAM Agent"
    XDR_COLLECTOR = "xdr_collector", "XDR Collector"
    CLOUD_IDENTITY_ENGINE = "cloud_identity_engine", "Cloud Identity Engine"
