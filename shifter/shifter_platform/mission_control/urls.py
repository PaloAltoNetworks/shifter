"""Mission Control URL configuration."""

from django.urls import path

from . import views

app_name = "mission_control"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("agents/", views.agents, name="agents"),
    path("agents/<int:agent_id>/delete/", views.delete_agent, name="delete_agent"),
    path("terminal/", views.terminal, name="terminal"),
    path("settings/", views.settings, name="settings"),
    path("help/", views.help_page, name="help"),
    # Presigned URL upload API
    path("api/upload/initiate/", views.initiate_upload, name="initiate_upload"),
    path("api/upload/complete/", views.complete_upload, name="complete_upload"),
    path("api/upload/cancel/", views.cancel_upload, name="cancel_upload"),
    # Range API
    path("api/range/", views.get_range, name="get_range"),
    path("api/range/launch/", views.launch_range, name="launch_range"),
    path("api/range/cancel/", views.cancel_range, name="cancel_range"),
    path("api/range/destroy/", views.destroy_range, name="destroy_range"),
    path("api/agents/", views.list_agents, name="list_agents"),
    path("api/scenarios/", views.list_scenarios, name="list_scenarios"),
    # NGFW views
    path("ngfw/", views.ngfw_list, name="ngfw_list"),
    path("ngfw/setup/", views.ngfw_wizard, name="ngfw_wizard"),
    path("ngfw/<uuid:app_id>/", views.ngfw_detail, name="ngfw_detail"),
    path("ngfw/<uuid:app_id>/deprovision/", views.ngfw_deprovision, name="ngfw_deprovision"),
    # NGFW API
    path("api/ngfw/", views.api_ngfw_create, name="api_ngfw_create"),
    path("api/ngfw/list/", views.api_ngfw_list, name="api_ngfw_list"),
    path("api/ngfw/<uuid:app_id>/destroy/", views.api_ngfw_destroy, name="api_ngfw_destroy"),
    # Credential views
    path("credentials/", views.credentials_list, name="credentials_list"),
    path("credentials/add/", views.credential_add, name="credential_add"),
    path("credentials/<int:credential_id>/", views.credential_detail, name="credential_detail"),
    # Credential API
    path("api/credentials/", views.api_credential_create, name="api_credential_create"),
    path("api/credentials/<int:credential_id>/delete/", views.api_credential_delete, name="api_credential_delete"),
]
