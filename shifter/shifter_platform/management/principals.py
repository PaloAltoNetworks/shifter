"""Management-owned principal lifecycle and fail-closed provider binding."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet

from shared.api_tokens.scopes import credential_ceiling, validate_scopes
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef
from shared.verified_identity import VerifiedIdentity

from .models import Principal, PrincipalConflictError, ProviderBinding, ServiceCredentialAdmission, UserProfile

if TYPE_CHECKING:
    from django.contrib.auth.models import User


_PRINCIPAL_UNAVAILABLE = "Principal unavailable"
_PROVIDER_IDENTITY_UNAVAILABLE = "Provider identity unavailable"


def _audit(
    entity_type: str, entity_id: int, action: str, state: dict[str, object], *, actor: PrincipalRef | None = None
) -> None:
    """Write a strict identity-lifecycle audit event."""
    actor_fields = principal_actor_fields(actor) if actor is not None else None
    event = AuditEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        new_state=state,
        context="principal_identity",
        actor_type=actor_fields["actor_type"] if actor_fields is not None else "system",
        actor_id=actor_fields["actor_id"] if actor_fields is not None else None,
        actor_principal_uuid=actor_fields["actor_principal_uuid"] if actor_fields is not None else None,
    )
    audit_log(event, strict=True)


def _principal_ref(principal: Principal) -> PrincipalRef:
    """Translate a persisted principal to its closed public reference."""
    if principal.kind == Principal.Kind.HUMAN:
        return PrincipalRef(uuid=principal.uuid, kind="human")
    if principal.kind == Principal.Kind.SERVICE:
        return PrincipalRef(uuid=principal.uuid, kind="service")
    raise PrincipalConflictError("Principal identity conflict")


def ensure_human_principal(user: User) -> PrincipalRef:
    """Create one durable principal for a Django user, without any grant."""
    if user is None or user.pk is None:
        raise PrincipalConflictError("A persisted user is required")
    with transaction.atomic():
        principal, created = Principal.objects.get_or_create(user=user, defaults={"kind": Principal.Kind.HUMAN})
        if principal.kind != Principal.Kind.HUMAN:
            raise PrincipalConflictError("Principal identity conflict")
        if created:
            _audit(AuditEntityType.PRINCIPAL, principal.pk, AuditAction.CREATE, {"kind": principal.kind})
        return _principal_ref(principal)


def principal_identity_for_user(user: User) -> PrincipalRef:
    """Read stable human ownership identity without authenticating that user."""
    principal = Principal.objects.filter(user_id=user.pk, kind=Principal.Kind.HUMAN).first()
    if principal is None:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    return _principal_ref(principal)


def principal_for_user(user: User) -> PrincipalRef:
    """Resolve a pre-existing human identity without creating one on a read."""
    if user is None or user.pk is None:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    principal = _active_principals().filter(user=user, kind=Principal.Kind.HUMAN).first()
    if principal is None:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    return _principal_ref(principal)


def delete_managed_pool_user(user: User, *, domain: str) -> None:
    """Remove an uncredentialed, inactive pool placeholder and its principal.

    This is deliberately not a general account-deletion path: real human
    principals remain protected even when their Django account is inactive.
    """
    from django.contrib.auth.models import User as DjangoUser

    if domain not in {"ctf-spare.invalid", "warm-pool.invalid"} or user.pk is None:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    with transaction.atomic():
        account = DjangoUser.objects.select_for_update().get(pk=user.pk)
        marker = account.email.partition("@")
        if (
            account.is_active
            or account.has_usable_password()
            or marker[2] != domain
            or account.username != f"{'ctf-spare' if domain == 'ctf-spare.invalid' else 'warm'}-{marker[0]}"
        ):
            raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
        principal = Principal.objects.select_for_update().get(user=account, kind=Principal.Kind.HUMAN)
        if principal.provider_bindings.exists():
            raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
        from shared.api_tokens.models import ApiToken

        if ApiToken.objects.filter(principal_uuid=principal.uuid).exists():
            raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
        _audit(AuditEntityType.PRINCIPAL, principal.pk, AuditAction.DELETE, {"managed_pool": domain})
        principal.delete()
        account.delete()


def _active_principals() -> QuerySet[Principal]:
    """Limit resolution to active services and active human user accounts."""
    return Principal.objects.filter(is_active=True).filter(
        Q(kind=Principal.Kind.SERVICE)
        | Q(kind=Principal.Kind.HUMAN, user__is_active=True, user__profile__deleted_at__isnull=True)
    )


def resolve_principal(principal_ref: PrincipalRef) -> PrincipalRef:
    """Re-resolve an active durable principal without exposing its persistence row."""
    if not isinstance(principal_ref, PrincipalRef):
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    principal = (
        _active_principals()
        .filter(
            uuid=principal_ref.uuid,
            kind=principal_ref.kind,
            is_active=True,
        )
        .first()
    )
    if principal is None:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    return _principal_ref(principal)


def resolve_verified_principal(identity: VerifiedIdentity) -> PrincipalRef:
    """Match a freshly verified provider identity to one active human principal."""
    principal = (
        _active_principals()
        .filter(
            kind=Principal.Kind.HUMAN,
            provider_bindings__issuer=identity.issuer,
            provider_bindings__subject=identity.subject,
        )
        .first()
    )
    if principal is None:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    return _principal_ref(principal)


def resolve_principal_uuid(principal_uuid: UUID) -> PrincipalRef:
    """Resolve one active principal by its globally unique public UUID."""
    principal = _active_principals().filter(uuid=principal_uuid).first()
    if principal is None:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    return _principal_ref(principal)


def resolve_service_credential(*, issuer: str, subject: str, audience: str) -> CredentialContext:
    """Resolve only an exact, explicitly admitted, active native service tuple."""
    admission = (
        ServiceCredentialAdmission.objects.select_related("binding__principal")
        .filter(
            binding__issuer=issuer,
            binding__subject=subject,
            binding__principal__kind=Principal.Kind.SERVICE,
            binding__principal__is_active=True,
            audience=audience,
            is_active=True,
        )
        .first()
    )
    if admission is None:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    try:
        scopes = validate_scopes(admission.scopes)
        return CredentialContext(
            principal=_principal_ref(admission.binding.principal),
            kind="service",
            credential_uuid=admission.uuid,
            ceiling=credential_ceiling(scopes),
            scopes=frozenset(scopes),
        )
    except ValueError as exc:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE) from exc


def create_service_principal(
    name: str,
    *,
    created_by: User | None = None,
    responsible_user: User | None = None,
    actor: PrincipalRef | None = None,
) -> PrincipalRef:
    """Create an independent service identity; contacts convey no authority."""
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise PrincipalConflictError("Invalid service principal")
    if any(user is not None and user.pk is None for user in (created_by, responsible_user)):
        raise PrincipalConflictError("Contact must be persisted")
    with transaction.atomic():
        principal = Principal.objects.create(
            kind=Principal.Kind.SERVICE,
            name=name.strip(),
            created_by=created_by,
            responsible_user=responsible_user,
        )
        _audit(AuditEntityType.PRINCIPAL, principal.pk, AuditAction.CREATE, {"kind": principal.kind}, actor=actor)
        return _principal_ref(principal)


def set_service_contact(principal_ref: PrincipalRef, contact: User | None) -> None:
    """Change the responsible contact without re-keying or reauthorizing a service."""
    if not isinstance(principal_ref, PrincipalRef) or (contact is not None and contact.pk is None):
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    with transaction.atomic():
        principal = Principal.objects.select_for_update().filter(uuid=principal_ref.uuid).first()
        if principal is None or principal.kind != Principal.Kind.SERVICE or principal_ref.kind != "service":
            raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
        if principal.responsible_user_id != (contact.pk if contact is not None else None):
            principal.responsible_user = contact
            principal.save(update_fields=["responsible_user", "updated_at"])
            _audit(AuditEntityType.PRINCIPAL, principal.pk, AuditAction.UPDATE, {"contact_changed": True})


def _valid_provider_identity(principal_ref: object, issuer: object, subject: object) -> bool:
    """Return whether a provider-binding request has a closed, bounded shape."""
    return (
        isinstance(principal_ref, PrincipalRef)
        and isinstance(issuer, str)
        and bool(issuer.strip())
        and len(issuer) <= 255
        and isinstance(subject, str)
        and bool(subject.strip())
        and len(subject) <= 255
    )


def _locked_bound_principal(principal_ref: PrincipalRef) -> Principal:
    """Resolve and lock the exact principal named by a public reference."""
    principal = Principal.objects.select_for_update().filter(uuid=principal_ref.uuid).first()
    if principal is None or principal.kind != principal_ref.kind:
        raise PrincipalConflictError(_PRINCIPAL_UNAVAILABLE)
    return principal


def _legacy_identity_conflicts(principal: Principal, issuer: str, subject: str) -> bool:
    """Return whether a compatible legacy tuple belongs to another principal."""
    legacy = UserProfile.objects.filter(cognito_sub=subject).first()
    return bool(legacy is not None and legacy.issuer in ("", issuer) and legacy.user_id != principal.user_id)


def _create_provider_binding(
    principal: Principal, issuer: str, subject: str, *, actor: PrincipalRef | None = None
) -> None:
    """Create and audit one immutable provider tuple after conflict checks."""
    existing = ProviderBinding.objects.filter(issuer=issuer, subject=subject).first()
    if existing is not None:
        if existing.principal_id != principal.id:
            raise PrincipalConflictError(_PROVIDER_IDENTITY_UNAVAILABLE)
        return
    binding = ProviderBinding.objects.create(principal=principal, issuer=issuer, subject=subject)
    _audit(
        AuditEntityType.PROVIDER_BINDING, binding.pk, AuditAction.CREATE, {"principal_id": principal.pk}, actor=actor
    )


def bind_principal_provider_identity(
    principal_ref: PrincipalRef, issuer: str, subject: str, *, actor: PrincipalRef | None = None
) -> None:
    """Bind an exact provider tuple once; never repair by email or subject alone."""
    if not _valid_provider_identity(principal_ref, issuer, subject):
        raise PrincipalConflictError(_PROVIDER_IDENTITY_UNAVAILABLE)
    try:
        with transaction.atomic():
            principal = _locked_bound_principal(principal_ref)
            if _legacy_identity_conflicts(principal, issuer, subject):
                raise PrincipalConflictError(_PROVIDER_IDENTITY_UNAVAILABLE)
            _create_provider_binding(principal, issuer, subject, actor=actor)
    except IntegrityError as exc:
        raise PrincipalConflictError(_PROVIDER_IDENTITY_UNAVAILABLE) from exc


__all__ = [
    "PrincipalConflictError",
    "bind_principal_provider_identity",
    "create_service_principal",
    "ensure_human_principal",
    "principal_for_user",
    "resolve_principal",
    "resolve_principal_uuid",
    "resolve_service_credential",
    "set_service_contact",
]
