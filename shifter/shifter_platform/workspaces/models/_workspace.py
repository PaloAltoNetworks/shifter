"""Workspace model - the tenancy scope ranges are bound to (ADR-046)."""

import uuid

from django.conf import settings
from django.db import models

#: The contextual subset of the canonical range-egress vocabulary
#: (``installation.range_egress.RangeEgressMode``) a workspace administrator may
#: select (ADR-017-R5, PLAT-238). ``status-quo`` inherits the deployment baseline;
#: ``none`` requests ADR-026 zero egress. The other canonical modes (``deny-all``,
#: ``allowlist``) are deployment-baseline-only and are never a workspace selection.
#: The values are the exact ``RangeEgressMode`` strings, kept as literals here so the
#: workspaces domain model does not depend on the installation layer; the launch and
#: provisioner layers (which legitimately import that layer) validate against the
#: canonical enum, and the closed DB check constraint keeps this in lockstep.
EGRESS_POLICY_STATUS_QUO = "status-quo"
EGRESS_POLICY_NONE = "none"
EGRESS_POLICY_CHOICES = (
    (EGRESS_POLICY_STATUS_QUO, "Inherit deployment baseline"),
    (EGRESS_POLICY_NONE, "Zero egress (no outbound NAT path)"),
)
WORKSPACE_EGRESS_POLICY_VALUES = frozenset(value for value, _ in EGRESS_POLICY_CHOICES)


class Workspace(models.Model):
    """A scope inside an organization that holds members and owns range scope.

    ``organization`` is an intra-domain ForeignKey and is required: there is no
    such thing as a workspace outside an organization. Cross-layer references
    to a workspace are the *scalar* ``workspace_id`` columns on
    ``cms.Request``, ``cms.RangeInstance``, and ``engine.Range``; those layers
    must not gain a ForeignKey here (ADR-001-R2, ADR-046-R1).

    ``personal_for_user`` marks the compatibility workspace that #1325 creates
    for each existing and new user. It is nullable and unique, so a user has at
    most one personal workspace while ordinary shared workspaces are unlimited.
    There is deliberately no shared deployment-global "Default" workspace: the
    compatibility default is per user (ADR-046-R4).

    A workspace has no ``owner_user`` field. Ownership is a membership row, so
    there is exactly one place authority is recorded; the last-owner invariant
    is enforced transactionally by ``workspaces.services``.
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Immutable public identifier; the only workspace ID public surfaces accept.",
    )
    organization = models.ForeignKey(
        "workspaces.Organization",
        on_delete=models.CASCADE,
        related_name="workspaces",
        help_text="Owning organization (intra-domain FK; always set).",
    )
    name = models.CharField(max_length=200, help_text="Display name, unique within the organization.")
    personal_for_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="personal_workspace",
        help_text=(
            "Set when this is the user's personal compatibility workspace (#1325). "
            "NULL for ordinary shared workspaces; unique so a user has at most one."
        ),
    )
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        default=None,
        db_index=True,
        help_text=(
            "Set when the workspace is archived; NULL for active workspaces. "
            "A reversible lifecycle marker only -- archival never deletes or "
            "rehomes ranges bound to the workspace (#1940, PLAT-233)."
        ),
    )
    egress_policy = models.CharField(
        max_length=16,
        choices=EGRESS_POLICY_CHOICES,
        default=EGRESS_POLICY_STATUS_QUO,
        help_text=(
            "Workspace network egress selector (PLAT-238). The compatibility default "
            "'status-quo' inherits the deployment baseline; 'none' requests the ADR-026 "
            "zero-egress (no outbound NAT path) posture for newly provisioned ranges. This "
            "is the contextual subset of the canonical installation.range_egress vocabulary; "
            "the workspace never stores CIDRs or provider configuration (ADR-017-R5)."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        db_table = "workspaces_workspace"
        ordering = ["organization_id", "name", "id"]
        verbose_name = "Workspace"
        verbose_name_plural = "Workspaces"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_workspace_name_per_organization",
            ),
            models.CheckConstraint(
                condition=models.Q(egress_policy__in=WORKSPACE_EGRESS_POLICY_VALUES),
                name="workspace_egress_policy_closed_vocabulary",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return self.name
