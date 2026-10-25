"""Django app hooks for cross-cutting portal configuration."""

from __future__ import annotations

from django.apps import AppConfig


class PortalConfig(AppConfig):
    """Register config-level startup hooks for the portal runtime."""

    name = "config"

    def ready(self) -> None:
        from cms.services import engine_invalidate_sharing_authority
        from config.credential_scope import credential_target_scope, temporary_participant_credential
        from config.health_checks import (
            register_audit_log_degraded_health_check,
            register_channel_layer_redis_health_check,
        )
        from config.model_access_authority import register_model_access_authority_signals
        from config.model_access_sharing import refresh_model_launch_projections
        from config.openfga_authorization import configured_authorization_provider
        from config.organizer_authority import register_organizer_authority_signals
        from config.service_identity import verify_service_credential
        from config.workspace_invitation_auth import register_workspace_invitation_login_signal
        from shared.audit import bind_audit_writer
        from shared.audit_adapter import audit_log_writer
        from shared.authorization import bind_authorization_provider_factory
        from shared.credentials import (
            bind_credential_scope_resolver,
            bind_service_credential_verifier,
            bind_temporary_credential_resolver,
        )
        from shared.model_access.authority_port import bind_authority_invalidator
        from shared.model_access.projection_port import bind_projection_refresher

        # Bind the one concrete audit writer to the neutral port. A missing or
        # conflicting binding is a startup configuration error (#1523).
        bind_audit_writer(audit_log_writer)
        bind_authority_invalidator(engine_invalidate_sharing_authority)
        bind_projection_refresher(refresh_model_launch_projections)
        bind_authorization_provider_factory(configured_authorization_provider)
        bind_service_credential_verifier(verify_service_credential)
        bind_credential_scope_resolver(credential_target_scope)
        bind_temporary_credential_resolver(temporary_participant_credential)
        register_audit_log_degraded_health_check()
        register_channel_layer_redis_health_check()
        register_model_access_authority_signals()
        register_organizer_authority_signals()
        register_workspace_invitation_login_signal()
