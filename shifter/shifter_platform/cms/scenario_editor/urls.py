"""URL configuration for Scenario Editor.

Provides both template-based UI views and REST API endpoints.
All URLs are under the scenario_editor namespace.
"""

from django.urls import path

from cms.scenario_editor import api_views, views

app_name = "scenario_editor"

urlpatterns = [
    # API endpoints (must be before slug-based routes to avoid "api" being
    # captured as a scenario_id)
    path("api/", api_views.scenario_list, name="api_list"),
    path("api/create/", api_views.scenario_create, name="api_create"),
    path("api/validate/", api_views.scenario_validate, name="api_validate"),
    path("api/validate-yaml/", api_views.scenario_validate_yaml, name="api_validate_yaml"),
    path("api/import-yaml/", api_views.scenario_import_yaml, name="api_import_yaml"),
    path("api/<slug:scenario_id>/", api_views.scenario_detail, name="api_detail"),
    path("api/<slug:scenario_id>/update/", api_views.scenario_update, name="api_update"),
    path("api/<slug:scenario_id>/delete/", api_views.scenario_delete, name="api_delete"),
    path("api/<slug:scenario_id>/metadata/", api_views.scenario_metadata, name="api_metadata"),
    path("api/<slug:scenario_id>/clone/", api_views.scenario_clone, name="api_clone"),
    path("api/<slug:scenario_id>/export-yaml/", api_views.scenario_export_yaml, name="api_export_yaml"),
    # Template-based UI views
    path("", views.scenario_list, name="list"),
    path("create/", views.scenario_create_form, name="create"),
    path("create/yaml/", views.scenario_yaml_create, name="create_yaml"),
    path("<slug:scenario_id>/", views.scenario_detail_view, name="detail"),
    path("<slug:scenario_id>/edit/", views.scenario_edit_form, name="edit"),
    path("<slug:scenario_id>/editor/", views.scenario_yaml_editor, name="yaml_editor"),
    path("<slug:scenario_id>/delete/", views.scenario_delete_view, name="delete"),
    path("<slug:scenario_id>/clone/", views.scenario_clone_view, name="clone"),
    path("<slug:scenario_id>/toggle-enabled/", views.scenario_toggle_enabled, name="toggle_enabled"),
    path("<slug:scenario_id>/toggle-staff-only/", views.scenario_toggle_staff_only, name="toggle_staff_only"),
    path("<slug:scenario_id>/export/", views.scenario_export_view, name="export"),
]
