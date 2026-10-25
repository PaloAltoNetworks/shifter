"""Canonical /api/v1 CMS API routes."""

from __future__ import annotations

from django.urls import path

from cms.api import (
    artifact_preparation,
    model_source_options,
    model_sources,
    preparation_adapters,
    preparation_workers,
    raes_image_registry,
    range_model_sources,
    range_scope,
    runtime_plugin_packs,
    runtime_plugins,
    tenant_packs,
    views,
    vpn_control,
)

app_name = "cms"

urlpatterns = [
    path(
        "organizations/<uuid:organization_uuid>/model-source-users/",
        model_sources.ModelSourceUsersView.as_view(),
        name="model-source-users",
    ),
    path(
        "organizations/<uuid:organization_uuid>/model-ranges/",
        range_model_sources.OrganizationModelRangesView.as_view(),
        name="organization-model-ranges",
    ),
    path(
        "ranges/<uuid:request_id>/model-sources/",
        range_model_sources.RangeModelSourcesView.as_view(),
        name="range-model-sources",
    ),
    path(
        "ranges/<uuid:request_id>/model-sources/revoke/",
        range_model_sources.RangeModelSourcesRevokeView.as_view(),
        name="range-model-sources-revoke",
    ),
    path("model-source-options/", model_source_options.ModelSourceOptionsView.as_view(), name="model-source-options"),
    path(
        "organizations/<uuid:organization_uuid>/model-sources/",
        model_sources.ModelSourceListCreateView.as_view(),
        name="model-sources",
    ),
    path(
        "organizations/<uuid:organization_uuid>/model-sources/available/",
        model_sources.UsableModelSourceListView.as_view(),
        name="model-sources-available",
    ),
    path(
        "organizations/<uuid:organization_uuid>/model-sources/<uuid:source_id>/",
        model_sources.ModelSourceDetailView.as_view(),
        name="model-source-detail",
    ),
    path(
        "organizations/<uuid:organization_uuid>/model-sources/<uuid:source_id>/retire-credentials/",
        model_sources.ModelSourceCredentialRetirementView.as_view(),
        name="model-source-credential-retirement",
    ),
    path(
        "organizations/<uuid:organization_uuid>/packs/",
        tenant_packs.TenantPackUploadView.as_view(),
        name="tenant-pack-upload",
    ),
    path(
        "organizations/<uuid:organization_uuid>/plugin-packs/",
        runtime_plugin_packs.RuntimePluginPackListView.as_view(),
        name="runtime-plugin-packs",
    ),
    path(
        "organizations/<uuid:organization_uuid>/plugin-packs/<slug:pack_id>/",
        runtime_plugin_packs.RuntimePluginPackDetailView.as_view(),
        name="runtime-plugin-pack-detail",
    ),
    path(
        "organizations/<uuid:organization_uuid>/plugins/",
        runtime_plugins.RuntimePluginListCreateView.as_view(),
        name="runtime-plugins",
    ),
    path(
        "organizations/<uuid:organization_uuid>/plugins/<uuid:plugin_id>/actions/",
        runtime_plugins.RuntimePluginActionView.as_view(),
        name="runtime-plugin-action",
    ),
    path(
        "preparation-adapter-grants/",
        preparation_adapters.PreparationAdapterGrantListView.as_view(),
        name="preparation-adapter-grants",
    ),
    path("vpn-control/sessions/", vpn_control.VpnSessionAuthorizeView.as_view(), name="vpn-control-authorize"),
    path("vpn-control/heartbeat/", vpn_control.VpnSessionHeartbeatView.as_view(), name="vpn-control-heartbeat"),
    path("vpn-control/sessions/end/", vpn_control.VpnSessionEndView.as_view(), name="vpn-control-end"),
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
