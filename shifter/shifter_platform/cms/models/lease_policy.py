"""Runtime Mission Control lease-policy persistence (#2169)."""

from __future__ import annotations

from django.db import models

from shared.mission_control_lease import MAX_LEASE_DAYS


class _MissionControlLeasePolicyFields(models.Model):
    """Typed ORM adapter for the canonical shared lease-policy contract."""

    initial_days = models.PositiveIntegerField()
    extension_days = models.PositiveIntegerField()
    maximum_days = models.PositiveIntegerField()
    extensions_enabled = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Keep shared policy fields abstract."""

        abstract = True


class MissionControlTenantLeasePolicyRevision(models.Model):
    """Durable tenant-scope revision fence retained while fallback is active."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Configure the singleton tenant revision fence."""

        verbose_name = "Mission Control tenant lease revision"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="ck_mc_tenant_lease_rev_singleton"),
            models.CheckConstraint(condition=models.Q(revision__gt=0), name="ck_mc_tenant_lease_rev_positive"),
        ]

    def __str__(self) -> str:
        return f"Mission Control tenant lease policy revision {self.revision}"


class MissionControlGroupLeasePolicyRevision(models.Model):
    """Durable group-scope revision fence retained while the group inherits."""

    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="mission_control_lease_policy_revision",
    )
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Configure one durable revision fence per group."""

        verbose_name = "Mission Control group lease revision"
        constraints = [
            models.CheckConstraint(condition=models.Q(revision__gt=0), name="ck_mc_group_lease_rev_positive"),
        ]

    def __str__(self) -> str:
        return f"Mission Control lease policy revision {self.revision} for group {self.group_id}"


class MissionControlTenantLeasePolicy(_MissionControlLeasePolicyFields):
    """Optional singleton replacing the deployment fallback while present."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    class Meta:
        """Constrain the singleton tenant policy at the database boundary."""

        verbose_name = "Mission Control tenant lease policy"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="ck_mc_tenant_lease_singleton"),
            models.CheckConstraint(condition=models.Q(initial_days__gt=0), name="ck_mc_tenant_lease_initial_positive"),
            models.CheckConstraint(
                condition=models.Q(extension_days__gt=0), name="ck_mc_tenant_lease_extension_positive"
            ),
            models.CheckConstraint(condition=models.Q(maximum_days__gt=0), name="ck_mc_tenant_lease_maximum_positive"),
            models.CheckConstraint(condition=models.Q(revision__gt=0), name="ck_mc_tenant_lease_revision_positive"),
            models.CheckConstraint(
                condition=models.Q(initial_days__lte=MAX_LEASE_DAYS),
                name="ck_mc_tenant_lease_initial_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(extension_days__lte=MAX_LEASE_DAYS),
                name="ck_mc_tenant_lease_extension_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(maximum_days__lte=MAX_LEASE_DAYS),
                name="ck_mc_tenant_lease_maximum_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(initial_days__lte=models.F("maximum_days")),
                name="ck_mc_tenant_lease_initial_maximum",
            ),
        ]

    def __str__(self) -> str:
        return "Mission Control tenant lease policy"


class MissionControlGroupLeasePolicy(_MissionControlLeasePolicyFields):
    """Complete lease policy attached to one administrator-controlled RBAC group."""

    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="mission_control_lease_policy",
    )

    class Meta:
        """Constrain each complete group policy at the database boundary."""

        verbose_name = "Mission Control group lease policy"
        constraints = [
            models.CheckConstraint(condition=models.Q(initial_days__gt=0), name="ck_mc_group_lease_initial_positive"),
            models.CheckConstraint(
                condition=models.Q(extension_days__gt=0), name="ck_mc_group_lease_extension_positive"
            ),
            models.CheckConstraint(condition=models.Q(maximum_days__gt=0), name="ck_mc_group_lease_maximum_positive"),
            models.CheckConstraint(condition=models.Q(revision__gt=0), name="ck_mc_group_lease_revision_positive"),
            models.CheckConstraint(
                condition=models.Q(initial_days__lte=MAX_LEASE_DAYS),
                name="ck_mc_group_lease_initial_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(extension_days__lte=MAX_LEASE_DAYS),
                name="ck_mc_group_lease_extension_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(maximum_days__lte=MAX_LEASE_DAYS),
                name="ck_mc_group_lease_maximum_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(initial_days__lte=models.F("maximum_days")),
                name="ck_mc_group_lease_initial_maximum",
            ),
        ]

    def __str__(self) -> str:
        return f"Mission Control lease policy for group {self.group_id}"
