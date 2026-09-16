"""Workspaces app configuration."""

from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    """Django app config for the organization/workspace tenancy domain."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "workspaces"
    verbose_name = "Workspaces"

    def ready(self) -> None:
        import workspaces.model_access_signals  # noqa: F401
        from workspaces.invitation_adapter import register_workspace_invitation_acceptor

        register_workspace_invitation_acceptor()
