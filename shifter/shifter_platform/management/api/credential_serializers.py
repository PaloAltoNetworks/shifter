"""Closed credential commands and safe metadata projections."""

from rest_framework import serializers

from shared.api.closed_serializer import ClosedSerializer
from shared.api_tokens.scopes import AUTHORIZATION_ACTION_SCOPES, KNOWN_SCOPES


class CredentialPageQuerySerializer(ClosedSerializer):
    """Validate bounded offset pagination for credential collections."""

    offset = serializers.IntegerField(default=0, min_value=0, max_value=100000)
    limit = serializers.IntegerField(default=50, min_value=1, max_value=200)


class PersonalCredentialSerializer(serializers.Serializer):
    """Project non-secret personal credential lifecycle metadata."""

    credential_uuid = serializers.UUIDField()
    name = serializers.CharField()
    scopes = serializers.ListField(child=serializers.CharField())
    expires_at = serializers.DateTimeField(allow_null=True)
    revoked_at = serializers.DateTimeField(allow_null=True)
    last_used_at = serializers.DateTimeField(allow_null=True)
    requires_reissue = serializers.BooleanField()
    target_type = serializers.CharField(allow_blank=True)
    target_uuid = serializers.UUIDField(allow_null=True)


class IssuedPersonalCredentialSerializer(PersonalCredentialSerializer):
    """Return a newly issued proof exactly once with its safe metadata."""

    token = serializers.CharField(help_text="Shown once. Never returned by list or detail operations.")


class PersonalCredentialPageSerializer(serializers.Serializer):
    """Project one bounded page of personal credential metadata."""

    count = serializers.IntegerField()
    next_offset = serializers.IntegerField(allow_null=True)
    results = PersonalCredentialSerializer(many=True)


class IssuePersonalCredentialSerializer(ClosedSerializer):
    """Validate a closed personal credential issue or rotation command."""

    name = serializers.CharField(max_length=100)
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(AUTHORIZATION_ACTION_SCOPES.values())),
        min_length=1,
        max_length=100,
    )
    expires_at = serializers.DateTimeField()
    target_type = serializers.ChoiceField(
        choices=["installation", "account", "organization", "workspace", "event", "range"]
    )
    target_uuid = serializers.UUIDField(required=False, allow_null=True)


class ServiceCredentialSerializer(serializers.Serializer):
    """Project non-secret native service admission metadata."""

    credential_uuid = serializers.UUIDField()
    principal_uuid = serializers.UUIDField()
    name = serializers.CharField()
    subject = serializers.CharField()
    audience = serializers.URLField()
    scopes = serializers.ListField(child=serializers.CharField())
    is_active = serializers.BooleanField()
    admission_active = serializers.BooleanField()
    principal_active = serializers.BooleanField()
    responsible_user_id = serializers.IntegerField(allow_null=True)


class CreateServiceCredentialSerializer(ClosedSerializer):
    """Validate a closed native service admission command."""

    name = serializers.CharField(max_length=200)
    subject = serializers.RegexField(r"^[0-9]{10,32}$")
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(KNOWN_SCOPES)), min_length=1, max_length=100
    )
    principal_uuid = serializers.UUIDField(required=False, allow_null=True)


class ServiceCredentialPageSerializer(serializers.Serializer):
    """Project one bounded page of native service admissions."""

    count = serializers.IntegerField()
    next_offset = serializers.IntegerField(allow_null=True)
    results = ServiceCredentialSerializer(many=True)


class ServicePrincipalUpdateSerializer(ClosedSerializer):
    """Validate lifecycle and responsible-contact changes for a service."""

    is_active = serializers.BooleanField()
    responsible_user_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class EmptyCredentialCommandSerializer(ClosedSerializer):
    """Commands with no client-controlled actor or lifecycle fields."""
