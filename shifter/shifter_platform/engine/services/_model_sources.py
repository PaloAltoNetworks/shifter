"""Tenant source administration with immutable credentials and explicit use grants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from shared.audit import AuditActorType, AuditEvent, audit_log
from shared.model_access import ContractError, ModelAccessCatalog
from shared.model_access.reservation import AuthorityRevision
from shared.model_access.sources import ModelSourceConfiguration, ModelSourceUseScope

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.models import ModelSource, ModelSourceRevision


REVISION_CONFLICT = "source.revision_conflict"


SOURCE_UNAVAILABLE = "source.unavailable"


@dataclass(frozen=True)
class ModelSourceView:
    """Metadata-only source readback; never a provider key or storage reference."""

    id: UUID
    organization_uuid: UUID
    revision: int
    enabled: bool
    state: str
    configuration: dict[str, Any]
    has_credential: bool


def _authorize(actor: User, organization_uuid: UUID) -> None:
    """Lock and recheck current tenant administration authority."""
    from django.contrib.auth.models import User

    from workspaces.services import OrganizationAuthorizationError, get_organization_profile

    with transaction.atomic():
        current = User.objects.select_for_update().filter(pk=actor.pk, is_active=True).first()
        if current is None:
            raise OrganizationAuthorizationError("Organization access denied")
        get_organization_profile(current, organization_uuid, lock=True)


def _configuration(value: object, *, enabled: bool = True) -> ModelSourceConfiguration:
    """Validate source policy and require live pricing for enabled revisions."""
    try:
        result = ModelSourceConfiguration.model_validate(value)
        if enabled and result.price_valid_until <= timezone.now():
            raise ValueError
        return result
    except ValueError:
        raise ContractError("source.invalid_configuration") from None


def _credential(config: ModelSourceConfiguration, value: object) -> str | None:
    """Validate transient input before any durable effect; errors contain no input."""
    import json

    if value is None:
        return None
    if config.authentication != "stored-credential" or not isinstance(value, dict):
        raise ContractError("source.invalid_credential")
    if config.provider in {"anthropic-v1", "openai-v1", "openrouter-v1"}:
        key = value.get("api_key")
        if (
            set(value) != {"api_key"}
            or not isinstance(key, str)
            or not 1 <= len(key) <= 8192
            or any(ord(c) < 33 or ord(c) > 126 for c in key)
        ):
            raise ContractError("source.invalid_credential")
    else:
        # Cloud credentials are admitted through the same closed resolver contract.
        from shared.model_access.source_credentials import validate_source_credential

        validate_source_credential(config, value)
    return json.dumps(value, separators=(",", ":"))


def _audit(actor: User, source: ModelSource, action: str) -> None:
    """Record source metadata changes without credential material."""
    audit_log(
        AuditEvent(
            entity_type="config",
            entity_id=0,
            entity_ref=str(source.id),
            action=action,
            actor_type=AuditActorType.USER,
            actor_id=actor.pk,
            new_state={"model_source_revision": source.revision, "enabled": source.enabled},
        ),
        strict=True,
    )


def _view(source: ModelSource, revision: ModelSourceRevision) -> ModelSourceView:
    """Project only safe metadata from a source and its immutable revision."""
    return ModelSourceView(
        source.id,
        source.organization_uuid,
        source.revision,
        source.enabled,
        revision.state if source.enabled else "disabled",
        revision.configuration,
        revision.credential_version is not None,
    )


def _store_credential(
    actor: User, source: ModelSource, revision: ModelSourceRevision, payload: str | None
) -> ModelSourceView:
    """Cloud I/O occurs after the pending revision commits, outside row locks."""
    from engine.models import ModelSource, ModelSourceRevision
    from workspaces.services import OrganizationAuthorizationError

    if payload is not None:
        from shared.cloud import get_secrets_store
        from shared.cloud.exceptions import CloudSecretsError

        if revision.credential_version is None:
            raise ContractError("source.credential_unavailable")
        try:
            reference = get_secrets_store().create_owned_secret(source.id, revision.credential_version, payload)
        except CloudSecretsError:
            ModelSourceRevision.objects.filter(pk=revision.pk, state="pending").update(state="failed")
            raise ContractError("source.credential_unavailable") from None
        revision.credential_reference = reference
    with transaction.atomic():
        failure: OrganizationAuthorizationError | ContractError | None = None
        try:
            _authorize(actor, source.organization_uuid)
        except OrganizationAuthorizationError as exc:
            failure = exc
        current = ModelSource.objects.select_for_update().get(pk=source.pk)
        try:
            if current.revision != revision.revision:
                raise ContractError(REVISION_CONFLICT)
        except ContractError as exc:
            failure = exc
        if failure is not None:
            ModelSourceRevision.objects.filter(pk=revision.pk).update(
                state="failed", credential_reference=revision.credential_reference
            )
        else:
            revision.state = "ready"
            revision.save(update_fields=["state", "credential_reference"])
            from engine.models import SharingAuthorityFence

            SharingAuthorityFence.objects.filter(
                authority_owner="engine",
                authority_reference=f"model-source:{source.id}",
                authority_revision=source.revision,
            ).update(state="allowed" if current.enabled else "revoked")
    # Raise after commit: failed publication must remain discoverable for cleanup.
    if failure is not None:
        raise failure
    return _view(current, revision)


def create_model_source(
    actor: User, organization_uuid: UUID, configuration: object, *, credential: object = None
) -> ModelSourceView:
    """Reserve tenant registry space, then publish a validated initial revision."""
    from engine.models import ModelSource, ModelSourceRevision

    _authorize(actor, organization_uuid)
    config = _configuration(configuration)
    payload = _credential(config, credential)
    if config.authentication == "stored-credential" and payload is None:
        raise ContractError("source.credential_required")
    with transaction.atomic():
        from engine.models import ModelSourceRegistry

        ModelSourceRegistry.objects.get_or_create(organization_uuid=organization_uuid)
        ModelSourceRegistry.objects.select_for_update().get(organization_uuid=organization_uuid)
        _authorize(actor, organization_uuid)
        if ModelSource.objects.filter(organization_uuid=organization_uuid).count() >= 128:
            raise ContractError("source.limit_reached")
        source = ModelSource.objects.create(organization_uuid=organization_uuid, created_by=actor)
        revision = ModelSourceRevision.objects.create(
            source=source,
            revision=1,
            configuration=config.model_dump(mode="json"),
            credential_version=uuid4() if payload else None,
        )
        _audit(actor, source, "create")
    return _store_credential(actor, source, revision, payload)


def update_model_source(
    actor: User,
    organization_uuid: UUID,
    source_id: UUID,
    *,
    expected_revision: int,
    configuration: object,
    credential: object = None,
    enabled: bool = True,
) -> ModelSourceView:
    """Fence old grants and publish a new immutable revision through explicit CAS."""
    from engine.models import ModelSource, ModelSourceRevision

    _authorize(actor, organization_uuid)
    config = _configuration(configuration, enabled=enabled)
    payload = _credential(config, credential)
    with transaction.atomic():
        _authorize(actor, organization_uuid)
        source = (
            ModelSource.objects.select_for_update().filter(pk=source_id, organization_uuid=organization_uuid).first()
        )
        if source is None:
            raise ContractError(SOURCE_UNAVAILABLE)
        if type(expected_revision) is not int or source.revision != expected_revision:
            raise ContractError(REVISION_CONFLICT)
        prior = ModelSourceRevision.objects.get(source=source, revision=source.revision)
        old_config = ModelSourceConfiguration.model_validate(prior.configuration)
        if (
            payload is None
            and config.authentication == "stored-credential"
            and (not prior.credential_reference or config.provider != old_config.provider)
        ):
            raise ContractError("source.credential_required")
        source.revision += 1
        source.enabled = enabled
        _invalidate_source_fences(source)
        source.save(update_fields=["revision", "enabled", "updated_at"])
        revision = ModelSourceRevision.objects.create(
            source=source,
            revision=source.revision,
            configuration=config.model_dump(mode="json"),
            credential_version=uuid4() if payload else prior.credential_version,
            credential_reference="" if payload else prior.credential_reference,
        )
        _audit(actor, source, "update")
    return _store_credential(actor, source, revision, payload)


def _invalidate_source_fences(source: ModelSource) -> None:
    """Serialize with request grant locks; retain every unresolved posting."""
    from engine.models import SharingAuthorityFence

    from ._model_allocation_lifecycle import revoke_model_authorities

    fences = list(
        SharingAuthorityFence.objects.select_for_update()
        .filter(authority_owner="engine", authority_reference=f"model-source:{source.id}")
        .order_by("deployment_id", "pk")
    )
    revoke_model_authorities([item.pk for item in fences])
    for fence in fences:
        fence.authority_revision = source.revision
        fence.state = "unknown"
        fence.save(update_fields=["authority_revision", "state", "updated_at"])


def list_model_sources(actor: User, organization_uuid: UUID) -> tuple[ModelSourceView, ...]:
    """List source metadata after checking tenant administration authority."""
    _authorize(actor, organization_uuid)
    return _list_sources(organization_uuid)


def _list_sources(organization_uuid: UUID) -> tuple[ModelSourceView, ...]:
    """Read the bounded registry at each source's published revision."""
    from django.db.models import F

    from engine.models import ModelSourceRevision

    return tuple(
        _view(revision.source, revision)
        for revision in ModelSourceRevision.objects.select_related("source")
        .filter(source__organization_uuid=organization_uuid, revision=F("source__revision"))
        .order_by("source_id")[:128]
    )


def project_authorized_model_sources(scope: ModelSourceUseScope) -> tuple[ModelSourceView, ...]:
    """Read candidates after CMS has resolved current tenant membership."""
    return tuple(
        replace(source, configuration={**source.configuration, "allowed_user_ids": []})
        for source in _list_sources(scope.organization_uuid)
        if source.state == "ready"
        and source.enabled
        and ModelSourceConfiguration.model_validate(source.configuration).price_valid_until > timezone.now()
        and (
            source.configuration["allow_organization_members"]
            or scope.actor_id in source.configuration["allowed_user_ids"]
        )
    )


def _assert_source_use(
    scope: ModelSourceUseScope, source: ModelSource, revision: ModelSourceRevision, config: ModelSourceConfiguration
) -> None:
    """Require enabled, ready, unexpired policy with an explicit source-use grant."""
    if (
        not source.enabled
        or revision.state != "ready"
        or config.price_valid_until <= timezone.now()
        or not (config.allow_organization_members or scope.actor_id in config.allowed_user_ids)
    ):
        raise ContractError("source.use_denied")


def compile_authorized_model_sources(
    scope: ModelSourceUseScope, selection: object, *, catalog: ModelAccessCatalog
) -> tuple[ModelAccessCatalog, tuple[AuthorityRevision, ...]]:
    """Authorize exact source revisions and capture fences for atomic admission."""
    from engine.models import ModelSource, ModelSourceRevision, SharingAuthorityFence
    from shared.model_access import OwnedReference
    from shared.model_access.reservation import AuthorityRevision
    from shared.model_access.source_catalog import compile_source_catalog
    from shared.model_access.sources import ModelSourceSelection

    selection = ModelSourceSelection.model_validate(selection)
    if not selection.aliases:
        return catalog, ()
    ids = sorted({choice.source_id for alias in selection.aliases for choice in alias.sources})
    with transaction.atomic():
        rows = list(
            ModelSource.objects.select_for_update()
            .filter(pk__in=ids, organization_uuid=scope.organization_uuid)
            .order_by("pk")
        )
        if len(rows) != len(ids):
            raise ContractError(SOURCE_UNAVAILABLE)
        sources, fences = {}, []
        for row in rows:
            revision = ModelSourceRevision.objects.get(source=row, revision=row.revision)
            config = ModelSourceConfiguration.model_validate(revision.configuration)
            _assert_source_use(scope, row, revision, config)
            source_ref = OwnedReference(owner="engine", reference=f"model-source:{row.id}")
            fence, _ = SharingAuthorityFence.objects.get_or_create(
                deployment_id=catalog.deployment_id,
                authority_owner=source_ref.owner,
                authority_reference=source_ref.reference,
                defaults={"authority_revision": row.revision, "state": "allowed"},
            )
            if fence.authority_revision != row.revision or fence.state != "allowed":
                raise ContractError(REVISION_CONFLICT)
            fences.append(AuthorityRevision(authority_ref=source_ref, authority_revision=row.revision))
            sources[row.id] = (row.revision, config)
        compiled = compile_source_catalog(catalog, selection, sources)
        return compiled, tuple(fences)


def retire_unused_model_source_credentials(actor: User, organization_uuid: UUID, source_id: UUID) -> int:
    """Retire only obsolete owned versions with no live or unresolved allocation.

    Publication fences prevent new use of these versions. A grace period covers
    ambiguous in-flight secret creation. Retired rows with no retired_at record
    are durable retry obligations; provider deletion is idempotent and outside
    the transaction. Disabled current credentials remain available for re-enable.
    """
    from datetime import timedelta

    from django.db.models import Q

    from engine.models import ModelAllocation, ModelSource, ModelSourceRevision
    from shared.cloud import get_secrets_store
    from shared.cloud.exceptions import CloudSecretsError

    with transaction.atomic():
        _authorize(actor, organization_uuid)
        source = (
            ModelSource.objects.select_for_update().filter(pk=source_id, organization_uuid=organization_uuid).first()
        )
        if source is None:
            raise ContractError(SOURCE_UNAVAILABLE)
        current = ModelSourceRevision.objects.get(source=source, revision=source.revision)
        # Deliberately conservative across all aliases/revisions in a frozen
        # catalog: a source that still has live work never loses old key material.
        if (
            ModelAllocation.objects.filter(snapshot__icontains=str(source.id))
            .filter(Q(grant__state__in=["pending", "active"]) | Q(unresolved_liabilities__gt=0))
            .exists()
        ):
            return 0
        candidates = ModelSourceRevision.objects.filter(
            source=source,
            credential_version__isnull=False,
            created_at__lt=timezone.now() - timedelta(minutes=10),
            retired_at__isnull=True,
        ).exclude(credential_version=current.credential_version)
        versions = tuple(
            candidates.order_by("credential_version").values_list("credential_version", flat=True).distinct()
        )
        candidates.update(state="retired")
        if versions:
            _audit(actor, source, "update")
    retired = 0
    for version in versions:
        if version is None:
            raise ContractError("source.credential_cleanup_pending")
        try:
            get_secrets_store().retire_owned_secret(source.id, version)
        except CloudSecretsError:
            raise ContractError("source.credential_cleanup_pending") from None
        ModelSourceRevision.objects.filter(source=source, credential_version=version, state="retired").update(
            retired_at=timezone.now()
        )
        retired += 1
    return retired
