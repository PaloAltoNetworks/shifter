"""Shared DRF base for the scoped model-access management surface (M09, #2126).

Session/CSRF and scoped-token parity is provided by composing
``shared.api_tokens.permissions.require_scope`` into each view's
``permission_classes``: browser sessions use the existing session path;
programmatic requests are bearer-first and must carry the exact ``model-access:*``
scope for the method, which ``require_scope`` also publishes into OpenAPI. Owner-
domain authority (operator, event, workspace, range) is always re-checked in the
owning service on every request and idempotent retry — a scope is never object
authority (management-preflight-2126.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rest_framework import permissions
from rest_framework.views import APIView

from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import active_actor_user
from shared.api.strict_json import ClosedJSONParser

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from rest_framework.request import Request


class ModelAccessAPIView(APIView):
    """Base view for the M09 management surface.

    Subclasses set ``permission_classes`` to a list composing
    :class:`IsAuthenticatedSessionOrApiToken`, a ``require_scope(...)`` gate for
    the surface's exact scope, and any audience permission. The ``/api/v1`` prefix
    is applied at the URL mount, so no versioning class is set.
    """

    versioning_class = None
    parser_classes: ClassVar = [ClosedJSONParser]
    permission_classes: ClassVar[list[type[permissions.BasePermission]]] = [IsAuthenticatedSessionOrApiToken]

    def actor(self, request: Request) -> User | None:
        """Return the active session or token-owner actor, or ``None``."""
        return active_actor_user(request)
