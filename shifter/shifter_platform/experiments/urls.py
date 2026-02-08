"""URL routing for experiments app."""

from django.urls import path

from experiments import views

app_name = "experiments"

urlpatterns: list = [
    # Experiment management
    path("", views.experiment_list, name="experiment_list"),
    path("create/", views.experiment_create, name="experiment_create"),
    path("<int:experiment_id>/", views.experiment_detail, name="experiment_detail"),
    path("<int:experiment_id>/start/", views.experiment_start, name="experiment_start"),
    path("<int:experiment_id>/cancel/", views.experiment_cancel, name="experiment_cancel"),
    # Script management
    path("scripts/", views.script_list, name="script_list"),
    path("scripts/upload/", views.script_upload, name="script_upload"),
    path("scripts/<int:script_id>/delete/", views.script_delete, name="script_delete"),
    # Downloads
    path("<int:experiment_id>/download/", views.experiment_download, name="experiment_download"),
    path(
        "<int:experiment_id>/runs/<int:run_number>/artifacts/<int:artifact_id>/download/",
        views.artifact_download,
        name="artifact_download",
    ),
    # AJAX
    path(
        "api/scenario/<str:scenario_id>/instances/",
        views.scenario_instances,
        name="scenario_instances",
    ),
]
