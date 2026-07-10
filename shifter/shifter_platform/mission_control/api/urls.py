"""Canonical /api/v1 Mission Control routes."""

from __future__ import annotations

from django.urls import path

from mission_control.api import views

app_name = "mission_control"

urlpatterns = [
    path("range/", views.CurrentRangeView.as_view(), name="range-current"),
    path("range/launch/", views.LaunchRangeView.as_view(), name="range-launch"),
    path("range/cancel/", views.CancelRangeView.as_view(), name="range-cancel"),
    path("range/destroy/", views.DestroyRangeView.as_view(), name="range-destroy"),
    path("range/pause/", views.PauseRangeView.as_view(), name="range-pause"),
    path("range/resume/", views.ResumeRangeView.as_view(), name="range-resume"),
    path(
        "range/<uuid:request_id>/aces/operation-status/",
        views.AcesOperationStatusListView.as_view(),
        name="aces-operation-status",
    ),
    path(
        "range/<uuid:request_id>/aces/operation-receipts/",
        views.AcesOperationReceiptListView.as_view(),
        name="aces-operation-receipts",
    ),
    path(
        "range/<uuid:request_id>/aces/snapshots/",
        views.AcesRuntimeSnapshotListView.as_view(),
        name="aces-runtime-snapshots",
    ),
    path(
        "range/<uuid:request_id>/aces/participant-implementations/",
        views.AcesParticipantImplementationListView.as_view(),
        name="aces-participant-implementations",
    ),
    path(
        "range/<uuid:request_id>/aces/participant-runtimes/",
        views.AcesParticipantRuntimeListView.as_view(),
        name="aces-participant-runtimes",
    ),
    path("agents/", views.AgentListView.as_view(), name="agents-list"),
    path("scenarios/", views.ScenarioListView.as_view(), name="scenarios-list"),
    path("upload/initiate/", views.UploadInitiateView.as_view(), name="upload-initiate"),
    path("upload/complete/", views.UploadCompleteView.as_view(), name="upload-complete"),
    path("upload/cancel/", views.UploadCancelView.as_view(), name="upload-cancel"),
    path("guacamole/rdp-url/", views.GuacamoleRDPURLView.as_view(), name="guacamole-rdp-url"),
    path("guacamole/ssh-url/", views.GuacamoleRangeSSHURLView.as_view(), name="guacamole-ssh-url"),
    path(
        "guacamole/bootstrap/<uuid:request_id>/",
        views.GuacamoleBootstrapStatusView.as_view(),
        name="guacamole-bootstrap-status",
    ),
    path(
        "guacamole/bootstrap/<uuid:request_id>/open/",
        views.GuacamoleBootstrapOpenView.as_view(),
        name="guacamole-bootstrap-open",
    ),
    path("ngfw/", views.NGFWCreateView.as_view(), name="ngfw-create"),
    path("ngfw/list/", views.NGFWListView.as_view(), name="ngfw-list"),
    path("ngfw/<uuid:app_id>/destroy/", views.NGFWDestroyView.as_view(), name="ngfw-destroy"),
    path("ngfw/<uuid:app_id>/ssh-url/", views.GuacamoleNGFWSSHURLView.as_view(), name="ngfw-ssh-url"),
    path("credentials/", views.CredentialCreateView.as_view(), name="credential-create"),
    path("credentials/<int:credential_id>/delete/", views.CredentialDeleteView.as_view(), name="credential-delete"),
]
