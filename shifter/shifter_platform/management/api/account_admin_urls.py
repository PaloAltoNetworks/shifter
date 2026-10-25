"""Public dormant identity/credential administration routing surface."""

from django.urls import include, path

from management.api import policy_views as identity
from management.api.credential_views import AdminPersonalCredentialListView, AdminPersonalCredentialRevokeView
from shared.api.audit import PolicyAuditLogViewSet

urlpatterns = [
    path("administer/users/", identity.PolicyAdminUserListView.as_view()),
    path("administer/users/<int:pk>/", identity.PolicyAdminUserDetailView.as_view()),
    path("administer/users/<int:pk>/lifecycle/", identity.PolicyAdminUserLifecycleView.as_view()),
    path("administer/users/<int:pk>/set-active/", identity.PolicyAdminUserSetActiveView.as_view()),
    path("administer/users/<int:pk>/delete/", identity.PolicyAdminUserDeleteView.as_view()),
    path("administer/users/<int:pk>/reset-password/", identity.PolicyAdminUserResetPasswordView.as_view()),
    path(
        "administer/principals/<uuid:principal_uuid>/personal-credentials/", AdminPersonalCredentialListView.as_view()
    ),
    path("administer/credentials/personal/<uuid:credential_uuid>/revoke/", AdminPersonalCredentialRevokeView.as_view()),
    path("credentials/", include("management.api.credential_urls")),
    path("audit/", PolicyAuditLogViewSet.as_view({"get": "list"})),
    path("audit/<int:pk>/", PolicyAuditLogViewSet.as_view({"get": "retrieve"})),
]
