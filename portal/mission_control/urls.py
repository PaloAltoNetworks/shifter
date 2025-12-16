"""Mission Control URL configuration."""

from django.urls import path

from . import views

app_name = "mission_control"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("agents/", views.agents, name="agents"),
    path("agents/upload/", views.upload_agent, name="upload_agent"),
    path("agents/<int:agent_id>/delete/", views.delete_agent, name="delete_agent"),
    path("history/", views.history, name="history"),
    path("terminal/", views.terminal, name="terminal"),
    path("settings/", views.settings, name="settings"),
    path("help/", views.help_page, name="help"),
    # Presigned URL upload API
    path("api/upload/initiate/", views.initiate_upload, name="initiate_upload"),
    path("api/upload/complete/", views.complete_upload, name="complete_upload"),
    path("api/upload/cancel/", views.cancel_upload, name="cancel_upload"),
    # Range API
    path("api/range/status/", views.get_range_status, name="range_status"),
    path("api/range/launch/", views.launch_range, name="launch_range"),
    path("api/range/cancel/", views.cancel_range, name="cancel_range"),
    path("api/range/destroy/", views.destroy_range, name="destroy_range"),
    path("api/agents/", views.list_agents_for_launch, name="list_agents"),
]
