"""Scoped authorization display metadata and durable OpenFGA operations."""

from __future__ import annotations

import uuid

from django.db import models


class AuthorizationScopeMixin(models.Model):
    """SQL-owned scope/display projection; never effective permission state."""

    class ScopeKind(models.TextChoices):
        """Persisted root scope types for authorization display metadata."""

        INSTALLATION = "installation", "Installation"
        ACCOUNT = "account", "Account"

    scope_kind = models.CharField(max_length=16, choices=ScopeKind.choices)
    account_uuid = models.UUIDField(null=True, blank=True)
    organization_uuid = models.UUIDField(null=True, blank=True)
    workspace_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        """Keep shared ancestry fields abstract rather than creating a separate table."""

        abstract = True

    def _scope_label(self) -> str:
        if self.scope_kind == self.ScopeKind.INSTALLATION:
            return "installation"
        return str(self.workspace_uuid or self.organization_uuid or self.account_uuid)

    @staticmethod
    def scope_constraint(name: str) -> models.CheckConstraint:
        """Reject inconsistent installation and account ancestry shapes in SQL."""
        return models.CheckConstraint(
            condition=(
                models.Q(
                    scope_kind="installation",
                    account_uuid__isnull=True,
                    organization_uuid__isnull=True,
                    workspace_uuid__isnull=True,
                )
                | (
                    models.Q(scope_kind="account", account_uuid__isnull=False)
                    & (models.Q(workspace_uuid__isnull=True) | models.Q(organization_uuid__isnull=False))
                )
            ),
            name=name,
        )

    @staticmethod
    def scope_name_constraints(prefix: str) -> list[models.UniqueConstraint]:
        """Treat absent ancestry as equal by indexing each valid scope shape."""
        return [
            models.UniqueConstraint(
                fields=["scope_kind", "name"],
                condition=models.Q(scope_kind="installation"),
                name=f"uniq_{prefix}_install_name",
            ),
            models.UniqueConstraint(
                fields=["scope_kind", "account_uuid", "name"],
                condition=models.Q(scope_kind="account", organization_uuid__isnull=True),
                name=f"uniq_{prefix}_account_name",
            ),
            models.UniqueConstraint(
                fields=["scope_kind", "account_uuid", "organization_uuid", "name"],
                condition=models.Q(scope_kind="account", organization_uuid__isnull=False, workspace_uuid__isnull=True),
                name=f"uniq_{prefix}_org_name",
            ),
            models.UniqueConstraint(
                fields=["scope_kind", "account_uuid", "organization_uuid", "workspace_uuid", "name"],
                condition=models.Q(scope_kind="account", workspace_uuid__isnull=False),
                name=f"uniq_{prefix}_workspace_name",
            ),
        ]


class AuthorizationGroup(AuthorizationScopeMixin):
    """Scoped group identity and display metadata; membership lives in OpenFGA."""

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    predefined_code = models.CharField(max_length=80, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Enforce valid ancestry and scope-local group name uniqueness."""

        db_table = "workspaces_authorization_group"
        constraints = [
            AuthorizationScopeMixin.scope_constraint("authz_group_scope_shape"),
            *AuthorizationScopeMixin.scope_name_constraints("authz_group"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self._scope_label()})"


class AuthorizationPolicy(AuthorizationScopeMixin):
    """Custom/predefined policy identity and display metadata only."""

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    predefined_code = models.CharField(max_length=80, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Enforce valid ancestry and scope-local policy name uniqueness."""

        db_table = "workspaces_authorization_policy"
        constraints = [
            AuthorizationScopeMixin.scope_constraint("authz_policy_scope_shape"),
            *AuthorizationScopeMixin.scope_name_constraints("authz_policy"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self._scope_label()})"


class AuthorizationMutationFence(models.Model):
    """Stable serialization key shared by grant, revoke and reconciliation."""

    key = models.CharField(max_length=64, primary_key=True)
    generation = models.PositiveBigIntegerField(default=0)
    blocked_operation_id = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Store the stable per-relationship serialization record."""

        db_table = "workspaces_authorization_mutation_fence"

    def __str__(self) -> str:
        return self.key


class AuthorizationOperation(models.Model):
    """Durable intent/outcome for one external OpenFGA relationship change."""

    class State(models.TextChoices):
        """Durable lifecycle outcomes for authorization mutations and reconciliation."""

        REQUESTED = "requested", "Requested"
        CONFIRMED = "confirmed", "Confirmed"
        DENIED = "denied", "Denied"
        UNRESOLVED = "unresolved", "Unresolved"

    class RelationshipKind(models.TextChoices):
        """Closed relationship forms supported by operation reconstruction."""

        ACTION = "action", "Action assignment"
        GROUP_MEMBERSHIP = "group_member", "Group membership"
        ROLE_ASSIGNMENT = "role_assign", "Role assignment"
        PREDEFINED_ROLE = "predefined", "Predefined role assignment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_namespace = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)
    fence_key = models.CharField(max_length=64, db_index=True)
    generation = models.PositiveBigIntegerField()
    state = models.CharField(max_length=16, choices=State.choices, db_index=True)
    actor_uuid = models.UUIDField()
    actor_kind = models.CharField(max_length=16)
    audit_actor_type = models.CharField(max_length=16, blank=True, default="")
    audit_actor_id = models.PositiveBigIntegerField(null=True, blank=True)
    audit_actor_principal_uuid = models.UUIDField(null=True, blank=True)
    audit_source_ip = models.GenericIPAddressField(null=True, blank=True)
    audit_user_agent = models.CharField(max_length=500, blank=True, default="")
    audit_request_id = models.CharField(max_length=128, blank=True, default="")
    relationship_kind = models.CharField(
        max_length=16,
        choices=RelationshipKind.choices,
        default=RelationshipKind.ACTION,
    )
    subject_kind = models.CharField(max_length=16)
    subject_uuid = models.UUIDField()
    action = models.CharField(max_length=120)
    effect = models.CharField(max_length=16)
    target_kind = models.CharField(max_length=16)
    target_uuid = models.UUIDField(null=True, blank=True)
    scope_kind = models.CharField(max_length=16)
    account_uuid = models.UUIDField(null=True, blank=True)
    organization_uuid = models.UUIDField(null=True, blank=True)
    workspace_uuid = models.UUIDField(null=True, blank=True)
    model_id = models.CharField(max_length=64)
    provider_store_id = models.CharField(max_length=64, blank=True, default="")
    credential_digest = models.CharField(max_length=64)
    outcome_reason = models.CharField(max_length=64, blank=True, default="")
    reconcile_lease_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Enforce idempotency and uniqueness of accepted fence generations."""

        db_table = "workspaces_authorization_operation"
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_namespace", "idempotency_key"],
                name="uniq_authz_idempotency_namespace_key",
            ),
            models.UniqueConstraint(
                fields=["fence_key", "generation"],
                condition=models.Q(state__in=["requested", "confirmed", "unresolved"]),
                name="uniq_authz_fence_generation",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action}:{self.id} ({self.state})"
