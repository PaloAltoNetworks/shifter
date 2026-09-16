"""URL routes for the Administer user-administration API (#1373).

Mounted at ``/api/v1/administer/`` by the composition root. The cross-domain
local-organizer grant is served by ``config.api_administer`` at a sibling path,
registered ahead of this include so its specific route matches first.
"""

from __future__ import annotations

from django.urls import path

from management.api.views import (
    AdminUserDeleteView,
    AdminUserDetailView,
    AdminUserLifecycleView,
    AdminUserListView,
    AdminUserResetPasswordView,
    AdminUserSetActiveView,
)

app_name = "administer"

urlpatterns = [
    path("users/", AdminUserListView.as_view(), name="users-list"),
    path("users/<int:pk>/", AdminUserDetailView.as_view(), name="users-detail"),
    path("users/<int:pk>/set-active/", AdminUserSetActiveView.as_view(), name="users-set-active"),
    path("users/<int:pk>/lifecycle/", AdminUserLifecycleView.as_view(), name="users-lifecycle"),
    path("users/<int:pk>/reset-password/", AdminUserResetPasswordView.as_view(), name="users-reset-password"),
    path("users/<int:pk>/delete/", AdminUserDeleteView.as_view(), name="users-delete"),
]
