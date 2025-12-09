"""Mission Control URL configuration."""

from django.urls import path

from . import views

app_name = "mission_control"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("agents/", views.agents, name="agents"),
    path("history/", views.history, name="history"),
    path("settings/", views.settings, name="settings"),
    path("help/", views.help_page, name="help"),
]
