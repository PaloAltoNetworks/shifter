"""Stable customer accounts and explicit membership facts (ADR-066)."""

import uuid

from django.db import models


class Account(models.Model):
    """Customer root. Individuals own resources directly, without subdivisions."""

    class Kind(models.TextChoices):
        """Closed customer-account classifications."""

        INDIVIDUAL = "individual", "Individual"
        TEAM = "team", "Team"
        ENTERPRISE = "enterprise", "Enterprise"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=200)
    # A scalar principal identity keeps the workspaces domain independent of
    # management persistence. S1 does not treat this fact as an authority grant.
    individual_principal_uuid = models.UUIDField(null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Database metadata and account-shape constraints."""

        db_table = "workspaces_account"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=("individual", "team", "enterprise")),
                name="account_kind_closed",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="individual", individual_principal_uuid__isnull=False)
                    | models.Q(kind__in=("team", "enterprise"), individual_principal_uuid__isnull=True)
                ),
                name="account_individual_principal_shape",
            ),
        ]

    def __str__(self) -> str:
        return f"account:{self.uuid}"


class AccountMembership(models.Model):
    """Explicit principal membership; the row itself conveys no policy grant."""

    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="memberships")
    principal_uuid = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Database metadata and unique membership constraints."""

        db_table = "workspaces_accountmembership"
        constraints = [
            models.UniqueConstraint(fields=["account", "principal_uuid"], name="uniq_account_principal_membership"),
        ]

    def __str__(self) -> str:
        return f"account-membership:{self.pk}"
