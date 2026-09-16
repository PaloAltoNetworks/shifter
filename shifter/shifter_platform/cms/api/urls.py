"""Canonical /api/v1 CMS API routes."""

from __future__ import annotations

from django.urls import path

from cms.api import (
    artifact_preparation,
    preparation_adapters,
    preparation_workers,
    raes_image_registry,
    range_scope,
    views,
)

app_name = "cms"

urlpatterns = [
    path(
        "artifact-preparation/workers/<uuid:operation_id>/",
        preparation_workers.PreparationWorkerView.as_view(),
        name="artifact-preparation-worker",
    ),
    path("artifact-preparation/", artifact_preparation.PreparationRequestView.as_view(), name="artifact-preparation"),
    path(
        "artifact-preparation/<uuid:operation_id>/",
        artifact_preparation.PreparationDetailView.as_view(),
        name="artifact-preparation-detail",
    ),
    path(
        "artifact-preparation/<uuid:operation_id>/cancel/",
        artifact_preparation.PreparationCancelView.as_view(),
        name="artifact-preparation-cancel",
    ),
    path(
        "artifact-preparation/<uuid:operation_id>/retry/",
        artifact_preparation.PreparationRetryView.as_view(),
        name="artifact-preparation-retry",
    ),
    path(
        "preparation-adapters/",
        preparation_adapters.PreparationAdapterListCreateView.as_view(),
        name="preparation-adapters",
    ),
    path(
        "preparation-adapters/<uuid:adapter_id>/state/",
        preparation_adapters.PreparationAdapterStateView.as_view(),
        name="preparation-adapter-state",
    ),
    path("catalog/", views.CatalogListView.as_view(), name="catalog-list"),
    # Range-to-workspace scope administration (PLAT-237, #1944): list ranges
    # scoped to a workspace, and reassign a range's workspace scope. Staff-session
    # + workspace owner/admin authority; public UUIDs only.
    path(
        "workspaces/<uuid:workspace_uuid>/range-scoping/",
        range_scope.WorkspaceRangeScopeListView.as_view(),
        name="workspace-range-scope-list",
    ),
    path(
        "ranges/<uuid:request_id>/workspace/",
        range_scope.RangeWorkspaceRebindView.as_view(),
        name="range-workspace-rebind",
    ),
    # Must precede the ``catalog/<slug:scenario_id>/`` detail route: "packs" is a
    # valid slug and the detail route would otherwise shadow this collection.
    path("catalog/packs/", views.PackRegisterView.as_view(), name="catalog-pack-register"),
    path("catalog/<slug:scenario_id>/", views.CatalogDetailView.as_view(), name="catalog-detail"),
    # Canonical RAES image registry management surface (#1566).
    path(
        "raes-image-mappings/",
        raes_image_registry.RaesImageMappingListCreateView.as_view(),
        name="raes-image-mappings",
    ),
    path(
        "raes-image-mappings/disable/",
        raes_image_registry.RaesImageMappingDisableView.as_view(),
        name="raes-image-mappings-disable",
    ),
    path(
        "scenarios/<slug:scenario_id>/metadata/",
        views.ScenarioMetadataView.as_view(),
        name="scenario-metadata",
    ),
    path(
        "scenarios/<slug:scenario_id>/realizability/",
        views.ScenarioRealizabilityView.as_view(),
        name="scenario-realizability",
    ),
    path(
        "scenarios/<slug:scenario_id>/",
        views.ScenarioResourceView.as_view(),
        name="scenario-detail",
    ),
]
