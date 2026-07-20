"""Serializers for the Administer user-administration API (#1373).

Read serializers expose the minimum identity data an administrator needs and are
deliberately *not* ``ModelSerializer``s: no writable model field, no
mass-assignment. Identity-binding facts (provider subject/issuer, provider group
claims) are never serialized. Command serializers accept only explicit, typed
writable fields.
"""

from __future__ import annotations

from django.contrib.auth.models import User
from rest_framework import serializers

from management import admin_services, services
from management.models import UserProfile
from shared.auth import CTF_ORGANIZER_GROUP


class AdminUserListItemSerializer(serializers.Serializer):
    """Read-only summary of a user for the Administer list.

    Roles, account type, and origin are surfaced read-only; identity-binding
    fields are intentionally absent.
    """

    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    display_name = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)
    is_staff = serializers.BooleanField(read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    user_type = serializers.SerializerMethodField()
    account_origin = serializers.SerializerMethodField()
    is_ctf_organizer = serializers.SerializerMethodField()
    is_deleted = serializers.SerializerMethodField()
    date_joined = serializers.DateTimeField(read_only=True)
    last_login = serializers.DateTimeField(read_only=True, allow_null=True)

    def get_display_name(self, user: User) -> str:
        return user.get_full_name() or user.email or user.get_username()

    def get_user_type(self, user: User) -> str:
        profile = services.safe_user_profile(user)
        return profile.user_type if profile else "standard"

    def get_account_origin(self, user: User) -> str:
        return admin_services.classify_account_origin(services.safe_user_profile(user))

    def get_is_ctf_organizer(self, user: User) -> bool:
        # Mirrors shared.auth.is_ctf_organizer semantics (organizer privilege is
        # active-gated) while reading the prefetched group cache to avoid N+1.
        return bool(user.is_active) and any(group.name == CTF_ORGANIZER_GROUP for group in user.groups.all())

    def get_is_deleted(self, user: User) -> bool:
        profile = services.safe_user_profile(user)
        return bool(profile and profile.is_deleted)


class AdminUserDetailSerializer(AdminUserListItemSerializer):
    """Read-only detail view: list fields plus role provenance and group names.

    ``groups`` are Django role group names (e.g. "CTF Organizer"), never the
    provider group claims captured on the profile.
    """

    organizer_grant_source = serializers.SerializerMethodField()
    must_change_password = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

    def get_organizer_grant_source(self, user: User) -> str:
        profile = services.safe_user_profile(user)
        return profile.organizer_grant_source if profile else ""

    def get_must_change_password(self, user: User) -> bool:
        profile = services.safe_user_profile(user)
        return bool(profile and profile.must_change_password)

    def get_groups(self, user: User) -> list[str]:
        return sorted(group.name for group in user.groups.all())


class AdminUserListQuerySerializer(serializers.Serializer):
    """Typed, bounded query parameters for the user list.

    Backs OpenAPI generation and validates/bounds the request before it reaches
    the domain query (defence in depth alongside the service-level bounds).
    """

    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=admin_services.ADMIN_USER_SEARCH_MAX_LEN,
    )
    user_type = serializers.ChoiceField(
        required=False,
        allow_blank=True,
        choices=[choice[0] for choice in UserProfile.USER_TYPE_CHOICES],
    )
    is_active = serializers.BooleanField(required=False, allow_null=True)
    account_origin = serializers.ChoiceField(
        required=False,
        allow_blank=True,
        choices=list(admin_services.ADMIN_ACCOUNT_ORIGINS),
    )
    include_deleted = serializers.BooleanField(required=False, default=False)


class SetActiveRequestSerializer(serializers.Serializer):
    """Explicit request body for the activate/deactivate operation."""

    is_active = serializers.BooleanField()
