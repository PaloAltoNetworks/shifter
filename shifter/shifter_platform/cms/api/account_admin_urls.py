"""Public dormant range-scope administration routing surface."""

from django.urls import path

from cms.api.policy_range_scope import PolicyRangeWorkspaceRebindView, PolicyWorkspaceRangeScopeListView

urlpatterns = [
    path("workspaces/<uuid:workspace_uuid>/range-scoping/", PolicyWorkspaceRangeScopeListView.as_view()),
    path("ranges/<uuid:request_id>/workspace/", PolicyRangeWorkspaceRebindView.as_view()),
]
