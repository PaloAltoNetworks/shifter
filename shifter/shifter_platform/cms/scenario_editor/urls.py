"""URL configuration for Scenario Editor.

Provides template-based UI views for managing scenario templates.
All URLs are under the scenario_editor namespace.
"""

from django.urls import path

from cms.scenario_editor import views

app_name = "scenario_editor"

urlpatterns = [
    path("", views.scenario_list, name="list"),
    path("create/", views.scenario_create_form, name="create"),
    path("create/yaml/", views.scenario_yaml_create, name="create_yaml"),
    path("validate-yaml/", views.validate_yaml_view, name="api_validate_yaml"),
    path("<slug:scenario_id>/", views.scenario_detail_view, name="detail"),
    path("<slug:scenario_id>/edit/", views.scenario_edit_form, name="edit"),
    path("<slug:scenario_id>/editor/", views.scenario_yaml_editor, name="yaml_editor"),
    path("<slug:scenario_id>/delete/", views.scenario_delete_view, name="delete"),
    path("<slug:scenario_id>/clone/", views.scenario_clone_view, name="clone"),
    path("<slug:scenario_id>/toggle-enabled/", views.scenario_toggle_enabled, name="toggle_enabled"),
    path("<slug:scenario_id>/toggle-staff-only/", views.scenario_toggle_staff_only, name="toggle_staff_only"),
    path("<slug:scenario_id>/export/", views.scenario_export_view, name="export"),
]
