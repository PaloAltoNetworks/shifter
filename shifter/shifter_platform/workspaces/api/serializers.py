"""Explicit serializers for the workspace membership and organization APIs."""

from rest_framework import serializers

from workspaces.models import (
    EGRESS_POLICY_CHOICES,
    QUOTA_MODE_CHOICES,
    QUOTA_OUTCOME_CHOICES,
    QUOTA_RESOURCE_CHOICES,
)
from workspaces.roles import WorkspaceRole


class OrganizationRefSerializer(serializers.Serializer):
    """Public organization projection (uuid + display name only)."""

    uuid = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


class OrganizationProfileSerializer(serializers.Serializer):
    """Read-only organization profile projection (ADR-048, PLAT-232).

    Emits the public ``uuid`` only; the internal integer primary key never
    appears on the wire.
    """

    uuid = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    support_email = serializers.EmailField(read_only=True)
    support_url = serializers.URLField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class OrganizationProfileUpdateSerializer(serializers.Serializer):
    """Partial-update command for the organization profile (PATCH mask).

    Every field is optional; an absent field is unchanged and an empty string
    clears an optional field. Unknown fields are rejected rather than ignored,
    and ``uuid``/timestamps are never writable here. The serializer owns HTTP
    shape (lengths, primitive formats); ``workspaces.services`` owns authority
    and persistence invariants.
    """

    name = serializers.CharField(max_length=200, allow_blank=False, required=False)
    description = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    support_email = serializers.EmailField(max_length=254, allow_blank=True, required=False)
    support_url = serializers.URLField(max_length=500, allow_blank=True, required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Reject unknown fields so a stale or hostile client cannot smuggle keys."""
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(dict.fromkeys(sorted(unknown), "Unknown field."))
        return attrs


class PrincipalWorkspaceContextSerializer(serializers.Serializer):
    """One workspace the caller belongs to, with role and advisory capabilities.

    ``role`` and ``capabilities`` are display/presentation hints derived from the
    central role-to-operation policy; every resource endpoint still reauthorizes
    the operation it performs (ADR-046-R11).
    """

    organization = OrganizationRefSerializer(read_only=True)
    workspace_uuid = serializers.UUIDField(read_only=True)
    workspace_name = serializers.CharField(read_only=True)
    is_personal = serializers.BooleanField(read_only=True)
    role = serializers.ChoiceField(read_only=True, choices=WorkspaceRole.choices)
    capabilities = serializers.ListField(child=serializers.CharField(), read_only=True)


class WorkspaceMembershipSerializer(serializers.Serializer):
    """Minimum public membership projection."""

    membership_id = serializers.IntegerField(read_only=True)
    workspace_uuid = serializers.UUIDField(read_only=True)
    user_id = serializers.IntegerField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    role = serializers.ChoiceField(read_only=True, choices=WorkspaceRole.choices)
    created_at = serializers.DateTimeField(read_only=True)


class AddWorkspaceMemberSerializer(serializers.Serializer):
    """Add-existing-account command."""

    email = serializers.EmailField(max_length=254)
    role = serializers.ChoiceField(choices=WorkspaceRole.choices)


class ChangeWorkspaceMemberRoleSerializer(serializers.Serializer):
    """Closed role-change command."""

    role = serializers.ChoiceField(choices=WorkspaceRole.choices)


class WorkspaceInvitationSerializer(serializers.Serializer):
    """Public invitation projection; bearer credentials never cross this API."""

    invitation_uuid = serializers.UUIDField(read_only=True)
    workspace_uuid = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    role = serializers.ChoiceField(read_only=True, choices=WorkspaceRole.choices)
    status = serializers.ChoiceField(read_only=True, choices=("pending", "expired", "accepted", "revoked"))
    expires_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class IssueWorkspaceInvitationSerializer(serializers.Serializer):
    """Closed invitation-issuance command."""

    email = serializers.EmailField(max_length=254)
    role = serializers.ChoiceField(choices=WorkspaceRole.choices)


class WorkspaceSerializer(serializers.Serializer):
    """Read-only workspace lifecycle projection (#1940, PLAT-233).

    Emits the public ``uuid`` (of both workspace and owning organization) only;
    internal integer primary keys never appear on the wire.
    """

    uuid = serializers.UUIDField(read_only=True)
    organization_uuid = serializers.UUIDField(read_only=True)
    organization_name = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    is_personal = serializers.BooleanField(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)
    archived_at = serializers.DateTimeField(read_only=True, allow_null=True)
    egress_policy = serializers.ChoiceField(read_only=True, choices=EGRESS_POLICY_CHOICES)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class CreateWorkspaceSerializer(serializers.Serializer):
    """Create-workspace command: an organization UUID and a display name.

    The serializer owns HTTP shape (presence, length, UUID form);
    ``workspaces.services`` owns authority and the name invariants.
    """

    organization_uuid = serializers.UUIDField()
    name = serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True)


class RenameWorkspaceSerializer(serializers.Serializer):
    """Rename-workspace command (PATCH mask; a single writable field)."""

    name = serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True)


class SetWorkspaceEgressPolicySerializer(serializers.Serializer):
    """Set-egress-policy command: one closed choice from the workspace subset (PLAT-238).

    The workspace-selectable vocabulary is the contextual subset of the canonical
    ``installation.range_egress.RangeEgressMode`` (``status-quo`` / ``none``). The
    serializer owns HTTP shape and rejects unknown fields; ``workspaces.services``
    re-validates against the canonical enum and owns authority and persistence.
    """

    egress_policy = serializers.ChoiceField(choices=EGRESS_POLICY_CHOICES)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Reject unknown fields so a stale or hostile client cannot smuggle keys."""
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(dict.fromkeys(sorted(unknown), "Unknown field."))
        return attrs


class WorkspaceQuotaResourceSerializer(serializers.Serializer):
    """Per-resource usage-against-limit projection (PLAT-239).

    ``limit``/``mode`` are ``null`` for an unconfigured resource (unlimited).
    """

    resource = serializers.ChoiceField(read_only=True, choices=QUOTA_RESOURCE_CHOICES)
    usage = serializers.IntegerField(read_only=True)
    limit = serializers.IntegerField(read_only=True, allow_null=True)
    mode = serializers.ChoiceField(read_only=True, choices=QUOTA_MODE_CHOICES, allow_null=True)


class WorkspaceQuotaDecisionSerializer(serializers.Serializer):
    """One recorded quota decision (append-only evidence) projection."""

    resource = serializers.ChoiceField(read_only=True, choices=QUOTA_RESOURCE_CHOICES)
    outcome = serializers.ChoiceField(read_only=True, choices=QUOTA_OUTCOME_CHOICES)
    limit = serializers.IntegerField(read_only=True)
    mode = serializers.ChoiceField(read_only=True, choices=QUOTA_MODE_CHOICES)
    usage_before = serializers.IntegerField(read_only=True)
    requested_delta = serializers.IntegerField(read_only=True)
    reason_code = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class WorkspaceQuotaSerializer(serializers.Serializer):
    """Read-only workspace quota surface: usage per resource + recent decisions (PLAT-239)."""

    workspace_uuid = serializers.UUIDField(read_only=True)
    resources = WorkspaceQuotaResourceSerializer(many=True, read_only=True)
    recent_decisions = WorkspaceQuotaDecisionSerializer(many=True, read_only=True)


class TransferWorkspaceOwnershipSerializer(serializers.Serializer):
    """Transfer-ownership command: the internal id of the new owner account.

    The new owner is identified by the ``user_id`` already exposed on the
    workspace membership roster projection, so no email or profile lookup is
    performed at this boundary.
    """

    user_id = serializers.IntegerField(min_value=1)
