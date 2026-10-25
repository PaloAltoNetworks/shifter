"""Dormant read-only management registrations. S8 replaces live registrations."""

from shared.admin_policy import PolicyReadOnlyAdmin


class PolicyUserProfileAdmin(PolicyReadOnlyAdmin):
    """Lifecycle mutations remain reachable through the canonical policy API/UI."""

    fields = ("user", "must_change_password", "deleted_at", "anonymized_at", "suspended_at")
    readonly_fields = fields
    list_display = ("user", "deleted_at", "suspended_at")


class PolicyUserAdmin(PolicyReadOnlyAdmin):
    """Inspect supported user metadata without exposing hashes or editing authority."""

    fields = ("username", "email", "first_name", "last_name", "is_active", "date_joined")
    readonly_fields = fields


class PolicyActivityLogAdmin(PolicyReadOnlyAdmin):
    """Historical activity remains installation-wide and immutable."""

    policy_action = "installation.read_audit"
    fields = ("action", "user", "timestamp", "metadata")
    readonly_fields = fields
