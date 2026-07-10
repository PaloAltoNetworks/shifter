"""The retired APIKey admin is read-only (PLAT-106 / #1124).

The `rr_live_` credential is retired: keys can no longer be created, edited, or
revoked anywhere, including Django admin. The admin remains registered only so
the archival rows referenced by `Comment.author_apikey` and `AuditLog` stay
viewable.
"""

from __future__ import annotations

from django.contrib import admin

from risk_register.admin import APIKeyAdmin
from risk_register.models import APIKey


def test_apikey_admin_is_read_only() -> None:
    model_admin = APIKeyAdmin(APIKey, admin.site)
    archival_key = APIKey()

    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_change_permission(None, archival_key) is False
    assert model_admin.has_delete_permission(None) is False
    assert model_admin.has_delete_permission(None, archival_key) is False
