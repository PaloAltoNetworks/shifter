"""Tenant-admin plugin installation without operator grants or package imports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from shifter_adapter_sdk.runtime import PluginManifest

from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.exceptions import ValidationError

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.models import RuntimePluginInstallation


@dataclass(frozen=True)
class RuntimePluginView:
    """Tenant-private installation detail, excluding credentials and worker logs."""

    id: UUID
    organization_uuid: UUID
    manifest: dict[str, Any]
    manifest_digest: str
    state: str
    failure_code: str
    has_registry_credentials: bool


@dataclass(frozen=True)
class RuntimePluginPage:
    """A bounded tenant installation page with its continuation cursor."""

    results: tuple[RuntimePluginView, ...]
    next_cursor: str | None


def _authorize(user: User, organization_uuid: UUID) -> UUID:
    """Require active organization administration before reading or mutating plugins."""
    from workspaces.services import OrganizationAuthorizationError, get_organization_profile

    if not (user and user.is_authenticated and user.is_active):
        raise OrganizationAuthorizationError("Organization access denied")
    return get_organization_profile(user, organization_uuid).uuid


def _credentials(payload: object) -> str:
    """Serialize only bounded username and password fields for encrypted storage."""
    if payload is None:
        return ""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"username", "password"}
        or any(not isinstance(value, str) or not 1 <= len(value) <= 8192 for value in payload.values())
    ):
        raise ValidationError("Registry credentials require a username and password or access token")
    return json.dumps(payload, separators=(",", ":"))


def install_runtime_plugin(
    user: User,
    organization_uuid: UUID,
    payload: object,
    *,
    registry_credentials: object = None,
    audit: RequestAudit | None = None,
) -> RuntimePluginView:
    """Register a tenant's own executable and queue an isolated compatibility probe.

    No allowlist or operator grant is required. Acceptance is deliberately
    ``checking``; only a successful, current isolated probe can make it ready.
    """
    from engine.models import RuntimePluginInstallation

    organization_uuid = _authorize(user, organization_uuid)
    try:
        manifest = PluginManifest.model_validate(payload)
    except ValueError:
        raise ValidationError("The plugin package uses an invalid or unsupported manifest") from None
    credentials = _credentials(registry_credentials)
    with transaction.atomic():
        row, created = RuntimePluginInstallation.objects.get_or_create(
            organization_uuid=organization_uuid,
            plugin_id=manifest.plugin_id,
            version=manifest.version,
            defaults={
                "manifest": manifest.model_dump(mode="json"),
                "manifest_digest": manifest.digest,
                "registry_credentials": credentials,
                "installed_by": user,
                "probe_expires_at": timezone.now() + timedelta(minutes=10),
            },
        )
        if row.manifest_digest != manifest.digest:
            raise ValidationError("An installed version cannot change its executable identity; use a new version")
        if not created and credentials and credentials != row.registry_credentials:
            raise ValidationError("Use Retry installation to update registry credentials")
        if created:
            _audit(user, row, AuditAction.CREATE, audit)
        return _view(row)


def list_runtime_plugins(user: User, organization_uuid: UUID, *, cursor: str | None = None) -> RuntimePluginPage:
    """Page through installations owned by the authorized organization."""
    from engine.models import RuntimePluginInstallation

    organization_uuid = _authorize(user, organization_uuid)
    query = RuntimePluginInstallation.objects.filter(organization_uuid=organization_uuid)
    if cursor is not None:
        try:
            after = UUID(cursor)
        except (ValueError, TypeError, AttributeError):
            raise ValidationError("Invalid plugin page cursor") from None
        created_at = query.filter(pk=after).values_list("created_at", flat=True).first()
        if created_at is None:
            raise ValidationError("Invalid plugin page cursor")
        query = query.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=after))
    rows = list(query.order_by("-created_at", "-id")[:51])
    return RuntimePluginPage(
        results=tuple(_view(row) for row in rows[:50]),
        next_cursor=str(rows[49].pk) if len(rows) > 50 else None,
    )


def change_runtime_plugin(
    user: User,
    organization_uuid: UUID,
    plugin_id: UUID,
    action: str,
    *,
    registry_credentials: object = None,
    audit: RequestAudit | None = None,
) -> RuntimePluginView:
    """Retain executable identity through disable, retry and irreversible retirement."""
    from engine.models import RuntimePluginInstallation

    organization_uuid = _authorize(user, organization_uuid)
    if action not in {"disable", "retire", "retry", "enable"}:
        raise ValidationError("The plugin action is invalid")
    credentials = _credentials(registry_credentials)
    if credentials and action != "retry":
        raise ValidationError("Registry credentials may only be changed when retrying installation")
    with transaction.atomic():
        row = (
            RuntimePluginInstallation.objects.select_for_update()
            .filter(
                pk=plugin_id,
                organization_uuid=organization_uuid,
            )
            .first()
        )
        if row is None:
            raise ValidationError("The plugin is unavailable")
        if row.state == "retired":
            if action != "retire":
                raise ValidationError("A retired plugin version cannot be reactivated")
            return _view(row)
        previous = row.state
        _apply_action(row, action, credentials)
        row.save()
        _audit(user, row, AuditAction.UPDATE, audit, previous=previous)
        return _view(row)


def _apply_action(row: RuntimePluginInstallation, action: str, credentials: str) -> None:
    """Validate the state transition and reset probe identity before rechecking."""
    if action in {"retry", "enable"}:
        if action == "retry" and row.state != "failed":
            raise ValidationError("Only failed installations may be retried")
        if action == "enable" and row.state != "disabled":
            raise ValidationError("Only disabled installations may be enabled")
        row.state = "checking"
        row.probe_id = uuid4()
        row.probe_expires_at = timezone.now() + timedelta(minutes=10)
        row.verified_at = None
        row.failure_code = ""
        if credentials:
            row.registry_credentials = credentials
    else:
        row.state = "disabled" if action == "disable" else "retired"


def _view(row: RuntimePluginInstallation) -> RuntimePluginView:
    """Project installation status without returning stored registry credentials."""
    return RuntimePluginView(
        row.id,
        row.organization_uuid,
        row.manifest,
        row.manifest_digest,
        row.state,
        row.failure_code,
        bool(row.registry_credentials),
    )


def _audit(
    user: User,
    row: RuntimePluginInstallation,
    action: str,
    audit: RequestAudit | None,
    *,
    previous: str = "",
) -> None:
    """Record actor attribution and bounded installation state changes."""
    attribution = audit or RequestAudit()
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.RUNTIME_PLUGIN,
            entity_id=0,
            entity_ref=str(row.id),
            action=action,
            actor_type=attribution.actor_type or AuditActorType.USER,
            actor_id=attribution.actor_id if attribution.actor_type else user.id,
            request_id=attribution.request_id,
            source_ip=attribution.source_ip,
            user_agent=attribution.user_agent,
            previous_state={"state": previous} if previous else {},
            new_state={
                "state": row.state,
                "manifest_digest": row.manifest_digest,
                "organization_uuid": str(row.organization_uuid),
            },
        ),
        strict=True,
    )
