"""Organization model - the outermost tenancy grouping (ADR-046)."""

import uuid

from django.db import models


class Organization(models.Model):
    """A tenancy grouping that owns workspaces.

    An organization is *only* a grouping of workspaces and their members. It is
    not an OIDC issuer, a cloud account or project, a Django ``auth.Group``, a
    CTF event, an API-token audience, an SPA navigation area, a Terraform
    workspace, or a range network boundary (ADR-046-R1). Binding an
    organization to any of those is a separate, separately reviewed decision.

    The internal integer primary key stays the join key for internal
    orchestration and the existing ``shared.audit`` integer ``entity_id``; the
    immutable ``uuid`` is the only identifier public surfaces may accept or
    emit, so callers cannot enumerate tenants by counting primary keys.
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Immutable public identifier; the only organization ID public surfaces accept.",
    )
    name = models.CharField(max_length=200, help_text="Display name shown to members.")
    description = models.CharField(
        max_length=2000,
        blank=True,
        default="",
        help_text="Optional organization description (PLAT-232). Empty string means unset.",
    )
    support_email = models.EmailField(
        max_length=254,
        blank=True,
        default="",
        help_text="Optional organization support email (PLAT-232). Empty string means unset.",
    )
    support_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Optional organization support URL (PLAT-232). Empty string means unset.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        db_table = "workspaces_organization"
        ordering = ["name", "id"]
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return self.name
