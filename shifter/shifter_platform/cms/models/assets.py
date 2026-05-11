"""User-owned asset models — credentials, file assets, agent configs.

The ``Asset`` hierarchy is purely abstract; concrete subclasses live in this
module (``Credential``, ``AgentConfig``). Asset models are owned by a single
user and support soft delete via ``deleted_at``.

Imports from :mod:`cms.models.catalogs` for the foreign-key targets
(CredentialType, OperatingSystem, AgentType).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import models

from cms.credential_encryption import EncryptedCredentialDataField
from cms.models.catalogs import AgentType, CredentialType, OperatingSystem
from shared.db import ExpiringStateMixin, SoftDeleteManager, SoftDeleteMixin, SoftDeleteQuerySet

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Abstract Asset Bases
# -----------------------------------------------------------------------------


class Asset(SoftDeleteMixin, models.Model):
    """Abstract base for user-owned assets with soft delete.

    Provides common fields and behavior for all asset types:
    - name: User-friendly identifier
    - created_at: Automatic creation timestamp
    - deleted_at: Soft delete timestamp (None = active)

    Subclasses must define a 'user' ForeignKey field.

    Soft-delete semantics:

    * ``Asset.objects`` is a :class:`~shared.db.SoftDeleteManager` and
      pre-filters to non-deleted rows. A plain
      ``Asset.objects.filter(user=user)`` cannot return deleted rows.
    * ``Asset.all_objects`` is the unfiltered manager — use it explicitly
      from admin / restore / audit code that needs to see deleted rows.
    """

    name = models.CharField(max_length=100, help_text="User-friendly name")
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"

    def __str__(self):
        return self.name

    @classmethod
    def active_for_user(cls, user):
        """Return non-deleted assets for a user.

        Thin wrapper around ``cls.objects.filter(user=user)`` — kept as a
        named method for callers that prefer the explicit verb.
        """
        return cls.objects.filter(user=user)


class FileAsset(Asset):
    """Abstract base class for file-backed assets stored in S3.

    Extends Asset with fields for S3 storage:
    - s3_key: Full S3 object key
    - original_filename: Original uploaded filename
    - file_size_bytes: File size for quota tracking
    - sha256_hash: Content hash (optional, for future server-side compute)
    """

    s3_key = models.CharField(max_length=500, help_text="S3 object key")
    original_filename = models.CharField(max_length=255)
    file_size_bytes = models.PositiveBigIntegerField()
    sha256_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        abstract = True

    @property
    def file_size_mb(self):
        """Return file size in megabytes, rounded to 1 decimal."""
        return round(self.file_size_bytes / (1024 * 1024), 1)


class CredentialBase(ExpiringStateMixin, Asset):
    """Abstract base for credential assets with expiration tracking.

    Extends Asset with credential-specific fields:
    - expires_at: Optional expiration timestamp
    - last_verified_at: Last external validation timestamp
    - last_used_at: Last provisioning use timestamp

    The :class:`~shared.db.ExpiringStateMixin` supplies
    ``is_expired`` and ``expires_soon``.
    """

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this credential expires (user sets at creation)",
    )
    last_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time credential was validated against external system",
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time credential was used for provisioning",
    )

    class Meta:
        abstract = True


# -----------------------------------------------------------------------------
# Concrete Asset Models
# -----------------------------------------------------------------------------


class Credential(CredentialBase):
    """User's credential instance.

    Concrete credential model. Inherits the asset shape from
    :class:`CredentialBase` (which extends :class:`Asset`):
    ``name``, ``created_at``, ``deleted_at`` from Asset; ``expires_at``,
    ``last_verified_at``, ``last_used_at`` from CredentialBase. The
    :class:`~shared.db.SoftDeleteMixin` and
    :class:`~shared.db.ExpiringStateMixin` properties (``is_deleted``,
    ``is_expired``, ``expires_soon``) are inherited via the base chain.

    Adds the credential-specific fields:
        user: Owner of this credential.
        credential_type: FK to CredentialType catalog.
        data: Type-specific fields as JSON (validated by spec_class).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    credential_type = models.ForeignKey(
        CredentialType,
        on_delete=models.PROTECT,
        related_name="credentials",
    )
    data = EncryptedCredentialDataField(
        default=dict,
        help_text="Type-specific credential data (validated by spec_class)",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Credential"
        verbose_name_plural = "Credentials"
        # Concrete Meta does not inherit Meta from the abstract base in
        # Django; restate base_manager_name so reverse-FK descriptors and
        # admin introspection stay on the unfiltered manager.
        base_manager_name = "all_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_credential_name_per_user",
            ),
        ]


class AgentConfig(FileAsset):
    """Agent installer uploaded by a user.

    Inherits from FileAsset:
    - name, created_at, deleted_at, is_deleted from Asset
    - s3_key, original_filename, file_size_bytes, sha256_hash, file_size_mb from FileAsset

    AgentConfig-specific:
    - user: Owner of this agent (with related_name="cms_agents")
    - os: Operating system this agent is for
    - agent_type: Type of agent (xdr, xdr_collector, cloud_identity_engine)
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cms_agents",
    )
    os = models.ForeignKey(
        OperatingSystem,
        on_delete=models.PROTECT,
        related_name="cms_agents",
    )
    agent_type = models.CharField(
        max_length=30,
        choices=AgentType.choices,
        default=AgentType.XDR,
        help_text="Type of agent (XDR, XDR Collector, Cloud Identity Engine)",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent Config"
        verbose_name_plural = "Agent Configs"
        # See Credential.Meta.base_manager_name for rationale.
        base_manager_name = "all_objects"

    def __str__(self):
        return f"{self.name} ({self.os.name})"
