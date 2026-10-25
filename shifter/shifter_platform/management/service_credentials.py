"""Authorized management of native service admission; no cloud keys or IAM writes."""

from uuid import UUID

from django.conf import settings
from django.db import transaction

from shared.api_tokens.scopes import credential_ceiling, validate_scopes
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.authorization import AuthorizationRequest, TargetRef, configured_authorization_provider
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope

from .models import Principal, ProviderBinding, ServiceCredentialAdmission
from .principals import bind_principal_provider_identity, create_service_principal, resolve_principal


class _Unchanged:
    """Sentinel type distinguishing an omitted contact from an explicit null."""


_UNCHANGED = _Unchanged()
_CREDENTIAL_ADMINISTRATION_DENIED = "Credential administration denied"


def _authorize(actor: CredentialContext) -> None:
    """Require a currently authorized non-personal management credential."""
    resolve_principal(actor.principal)
    if actor.kind in {"personal", "temporary"}:
        raise ValueError(_CREDENTIAL_ADMINISTRATION_DENIED)
    request = AuthorizationRequest(
        actor.principal,
        "installation.manage_service_credentials",
        TargetRef("installation"),
        ResourceScope("installation"),
        actor.ceiling,
    )
    if not configured_authorization_provider().check(request).allowed:
        raise ValueError(_CREDENTIAL_ADMINISTRATION_DENIED)


def _view(admission: ServiceCredentialAdmission) -> dict[str, object]:
    """Project safe service-admission metadata without any proof material."""
    return {
        "credential_uuid": admission.uuid,
        "principal_uuid": admission.binding.principal.uuid,
        "name": admission.binding.principal.name,
        "subject": admission.binding.subject,
        "audience": admission.audience,
        "scopes": admission.scopes,
        "is_active": admission.is_active and admission.binding.principal.is_active,
        "admission_active": admission.is_active,
        "principal_active": admission.binding.principal.is_active,
        "responsible_user_id": admission.binding.principal.responsible_user_id,
    }


def create_service_credential(
    actor: CredentialContext, *, name: str, subject: str, scopes: list[str], principal_uuid: UUID | None = None
) -> dict[str, object]:
    """Create an independent identity and immutable native admission, without grants."""
    _authorize(actor)
    normalized = validate_scopes(scopes)
    audience = getattr(settings, "GCP_SERVICE_TOKEN_AUDIENCE", "")
    if (
        not audience.startswith("https://")
        or not subject.isascii()
        or not subject.isdecimal()
        or not 10 <= len(subject) <= 32
        or any(not credential_ceiling([scope]).actions for scope in normalized)
    ):
        raise ValueError("Invalid service admission")
    with transaction.atomic():
        creator = Principal.objects.select_for_update().get(uuid=actor.principal.uuid, is_active=True)
        if principal_uuid is None:
            principal = create_service_principal(name, created_by=creator.user, actor=actor.principal)
        else:
            from shared.identity_scope import PrincipalRef

            principal = resolve_principal(PrincipalRef(principal_uuid, "service"))
        bind_principal_provider_identity(principal, "https://accounts.google.com", subject, actor=actor.principal)
        binding = ProviderBinding.objects.get(
            principal__uuid=principal.uuid, issuer="https://accounts.google.com", subject=subject
        )
        admission = ServiceCredentialAdmission.objects.create(binding=binding, audience=audience, scopes=normalized)
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.PRINCIPAL,
                entity_id=binding.principal_id,
                action=AuditAction.UPDATE,
                entity_ref=str(principal.uuid),
                new_state={"credential_uuid": str(admission.uuid), "admission": "created"},
                context="service_credential",
                **principal_actor_fields(actor.principal),
            ),
            strict=True,
        )
    return _view(admission)


def update_service_principal(
    actor: CredentialContext,
    principal_uuid: UUID,
    *,
    is_active: bool,
    responsible_user_id: int | None | _Unchanged = _UNCHANGED,
) -> None:
    """Administer independent lifecycle/contact without transferring identity."""
    from django.contrib.auth.models import User

    _authorize(actor)
    contact_changed = not isinstance(responsible_user_id, _Unchanged)
    contact = None
    if isinstance(responsible_user_id, int):
        contact = User.objects.filter(pk=responsible_user_id, is_active=True, profile__deleted_at__isnull=True).first()
        if contact is None:
            raise ValueError("Service contact unavailable")
    with transaction.atomic():
        principal = Principal.objects.select_for_update().filter(uuid=principal_uuid, kind="service").first()
        if principal is None:
            raise ValueError("Service principal unavailable")
        principal.is_active = is_active
        if contact_changed:
            principal.responsible_user = contact
        principal.save(update_fields=["is_active", "responsible_user", "updated_at"])
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.PRINCIPAL,
                entity_id=principal.pk,
                entity_ref=str(principal.uuid),
                action=AuditAction.UPDATE,
                new_state={
                    "is_active": is_active,
                    "contact_changed": contact_changed,
                },
                context="service_credential",
                **principal_actor_fields(actor.principal),
            ),
            strict=True,
        )


def list_service_credentials(actor: CredentialContext, *, offset: int = 0, limit: int = 50) -> dict[str, object]:
    """List bounded safe admission metadata after live authorization."""
    _authorize(actor)
    from .credential_pagination import credential_page

    return credential_page(
        ServiceCredentialAdmission.objects.select_related("binding__principal").order_by("pk"),
        offset=offset,
        limit=limit,
        project=_view,
    )


def disable_service_credential(actor: CredentialContext, credential_uuid: UUID) -> None:
    """Disable admission without erasing the immutable provider identity."""
    _authorize(actor)
    with transaction.atomic():
        admission = ServiceCredentialAdmission.objects.select_for_update().filter(uuid=credential_uuid).first()
        if admission is None:
            raise ValueError(_CREDENTIAL_ADMINISTRATION_DENIED)
        if admission.is_active:
            admission.is_active = False
            admission.save(update_fields=["is_active"])
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.PRINCIPAL,
                    entity_id=admission.binding.principal_id,
                    action=AuditAction.UPDATE,
                    entity_ref=str(admission.binding.principal.uuid),
                    new_state={"credential_uuid": str(admission.uuid), "admission": "disabled"},
                    context="service_credential",
                    **principal_actor_fields(actor.principal),
                ),
                strict=True,
            )
