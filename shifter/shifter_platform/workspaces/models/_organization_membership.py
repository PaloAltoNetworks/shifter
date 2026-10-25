"""OrganizationMembership model - a user's organization-level role (ADR-048)."""

from django.conf import settings
from django.db import models

from workspaces.roles import OrganizationRole


class OrganizationMembership(models.Model):
    """One user's role in one organization.

    Organization authority is a separately accepted seam (ADR-048), distinct
    from workspace membership. Uniqueness on ``(organization, user)`` is the
    database-level proof that a user holds a single organization role, and the
    role vocabulary is closed (:class:`~workspaces.roles.OrganizationRole`) and
    protected by a database check constraint.

    A row here is the *only* source of organization authority. It is never
    derived from a workspace role, Django staff/groups, model permissions,
    identity-provider claims, API-token scopes, or cloud roles (ADR-046-R8,
    ADR-048). A Django superuser is an orthogonal platform-operator override
    recorded distinctly in audit, not a membership row.
    """

    organization = models.ForeignKey(
        "workspaces.Organization",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="organization_memberships",
    )
    principal_uuid = models.UUIDField(null=True, blank=True)
    role = models.CharField(
        max_length=32,
        choices=OrganizationRole.choices,
        help_text="Closed organization role code; the authority seam lives in workspaces.services.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        db_table = "workspaces_organizationmembership"
        ordering = ["organization_id", "user_id"]
        verbose_name = "Organization membership"
        verbose_name_plural = "Organization memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="uniq_org_membership_per_organization_user",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=OrganizationRole.values) | models.Q(role="", principal_uuid__isnull=False),
                name="organization_membership_role_valid",
            ),
            models.UniqueConstraint(
                fields=["organization", "principal_uuid"], name="uniq_organization_principal_member"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, principal_uuid__isnull=True)
                    | models.Q(user__isnull=True, principal_uuid__isnull=False, role="")
                ),
                name="organization_membership_identity_shape",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return f"{self.role}@org{self.organization_id}:{self.user_id}"
