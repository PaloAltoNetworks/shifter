"""SPA-owned Scenario Catalog page routes (#1371 / #1311)."""

from __future__ import annotations

from django.urls import path, re_path

from shared.spa_host import platform_spa_host

app_name = "scenario_editor"

urlpatterns = [
    path("", platform_spa_host, name="list"),
    path("<slug:scenario_id>/", platform_spa_host, name="detail"),
    re_path(r"^.*$", platform_spa_host),
]
