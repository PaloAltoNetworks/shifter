"""Canonical /api/v1 CMS API routes."""

from __future__ import annotations

from django.urls import path

from cms.api import views

app_name = "cms"

urlpatterns = [
    path("catalog/", views.CatalogListView.as_view(), name="catalog-list"),
    path("catalog/<slug:scenario_id>/", views.CatalogDetailView.as_view(), name="catalog-detail"),
    path("scenario-editor/validate-yaml/", views.YAMLValidateView.as_view(), name="scenario-editor-validate-yaml"),
    path(
        "scenario-editor/scenarios/from-yaml/",
        views.YAMLScenarioCreateView.as_view(),
        name="scenario-editor-scenario-create-yaml",
    ),
]
