"""SPA-owned Mission Control page routes.

All mutations and data access use the canonical ``/api/v1/mission-control/``
API.  Stable route names remain for notification and redirect callers.
"""

from django.urls import path, re_path

from shared.spa_host import platform_spa_host

app_name = "mission_control"

urlpatterns = [
    path("", platform_spa_host, name="dashboard"),
    path("agents/", platform_spa_host, name="agents"),
    path("terminal/", platform_spa_host, name="terminal"),
    path("settings/", platform_spa_host, name="settings"),
    path("help/", platform_spa_host, name="help"),
    path("walkthrough/", platform_spa_host, name="walkthrough"),
    path("ngfw/", platform_spa_host, name="ngfw_list"),
    path("ngfw/setup/", platform_spa_host, name="ngfw_wizard"),
    path("ngfw/<uuid:app_id>/", platform_spa_host, name="ngfw_detail"),
    path("ngfw/<uuid:app_id>/deprovision/", platform_spa_host, name="ngfw_deprovision"),
    path("credentials/", platform_spa_host, name="credentials_list"),
    path("credentials/add/", platform_spa_host, name="credential_add"),
    path("credentials/<int:credential_id>/", platform_spa_host, name="credential_detail"),
    re_path(r"^(?!files/$|api/).*$", platform_spa_host),
]
