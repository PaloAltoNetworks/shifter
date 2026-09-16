"""Exact public routes for workspace invitation credential exchange."""

from django.urls import path

from workspaces.public_views import invitation_accept, invitation_stage

urlpatterns = [
    path(
        "workspace-invitations/accept/",
        invitation_accept,
        name="workspace_invitation_accept",
    ),
    path(
        "workspace-invitations/stage/",
        invitation_stage,
        name="workspace_invitation_stage",
    ),
]
