"""Read-only Django-admin boundary prepared for the coordinated policy cutover."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib import admin
from django.core.exceptions import PermissionDenied

from shared.api.principals import authenticated_credential
from shared.authorization import AuthorizationRequest, TargetRef, configured_authorization_provider
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.principal_port import resolve_principal

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet
    from django.forms import ModelForm
    from django.http import HttpRequest
    from rest_framework.request import Request


class PolicyReadOnlyAdmin(admin.ModelAdmin):
    """Canonical API/services own mutations; retained admin inspection uses policy."""

    policy_action = "installation.manage_principals"
    actions = None

    def _credential(self, request: HttpRequest) -> CredentialContext:
        actor = authenticated_credential(cast("Request", request))
        if actor.kind != "session":
            raise PermissionDenied
        resolve_principal(actor.principal)
        return actor

    def _allowed(self, request: HttpRequest, obj: Model | None = None) -> bool:
        actor = self._credential(request)
        return (
            configured_authorization_provider()
            .check(
                AuthorizationRequest(
                    actor.principal,
                    self.policy_action,
                    TargetRef("installation"),
                    ResourceScope("installation"),
                    actor.ceiling,
                )
            )
            .allowed
        )

    def has_view_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        try:
            return self._allowed(request, obj)
        except Exception:
            return False

    def has_module_permission(self, request: HttpRequest) -> bool:
        return self.has_view_permission(request)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Model]:
        if not self.has_view_permission(request):
            raise PermissionDenied
        return super().get_queryset(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: Model, form: ModelForm[Model], change: bool) -> None:
        raise PermissionDenied

    def delete_model(self, request: HttpRequest, obj: Model) -> None:
        raise PermissionDenied

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[Model]) -> None:
        raise PermissionDenied


class PolicyAdminSite(admin.AdminSite):
    """Dormant site admission; registered policy admins authorize every read."""

    def has_permission(self, request: HttpRequest) -> bool:
        try:
            actor = authenticated_credential(cast("Request", request))
            if actor.kind != "session":
                return False
            return resolve_principal(actor.principal) == actor.principal
        except Exception:
            return False
