"""Read-only legacy admin projection; credential mutations use the authorized API."""

from django.contrib import admin
from django.http import HttpRequest
from knox.models import AuthToken

from shared.api_tokens.models import ApiToken

# Knox's stock admin can mint credentials without Shifter's policy check and
# exposes verifier digests. Only the authorized credential API may mutate them.
if admin.site.is_registered(AuthToken):
    admin.site.unregister(AuthToken)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Retain safe metadata visibility without a separate issuance or edit path."""

    list_display = ("name", "display_id", "created_by", "created_at", "expires_at", "revoked_at")
    search_fields = ("name", "token_id")
    list_filter = ("revoked_at", "expires_at")
    fields = (
        "name",
        "display_id",
        "scopes",
        "target_type",
        "target_uuid",
        "created_by",
        "created_at",
        "last_used_at",
        "expires_at",
        "revoked_at",
    )
    readonly_fields = fields
    actions = None

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Forbid minting credentials through Django admin."""
        return False

    def has_change_permission(self, request: HttpRequest, obj: ApiToken | None = None) -> bool:
        """Forbid editing credential metadata through Django admin."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ApiToken | None = None) -> bool:
        """Forbid bypassing the audited revocation lifecycle."""
        return False
