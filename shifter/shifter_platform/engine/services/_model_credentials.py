"""Generation-bound, one-use enrollment and rotating guest capabilities.

Only the authenticated control listener may expose these functions remotely.
Provisioner identity is additionally bound to the exact operation before issue;
the broker may exchange/refresh/authenticate but cannot issue enrollment.
"""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from pydantic import SecretStr

from shared.model_access import ContractError
from shared.model_access.credentials import ModelAccessAuthorization, ModelEnrollment, ModelTokenPair
from shared.model_access.effective_policy import EffectivePolicy
from shared.model_access.network import RFC1918_IPV4_NETWORKS, peer_matches_binding

from ._model_request_accounting import _recheck_authority
from ._model_request_lifecycle import fence_revoked_requests

if TYPE_CHECKING:
    from engine.models import ModelAccessCredential, ModelAllocation, ModelPendingGrant, Range

_DENIED = "credential.unavailable"
_NETWORK_UNAVAILABLE = "credential.network_unavailable"


def _hash(value: str) -> str:
    """Hash opaque capability bytes without retaining their plaintext."""
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _token(grant_id: UUID) -> str:
    """Mint an opaque capability carrying the public grant identifier."""
    return f"{grant_id}.{secrets.token_urlsafe(32)}"


def _parse_token(value: str) -> UUID:
    """Validate a bounded token envelope and return only its public grant identity."""
    try:
        if not isinstance(value, str) or len(value) != 80 or not value.isascii():
            raise ValueError
        public_id, secret = value.split(".")
        if len(secret) != 43 or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in secret
        ):
            raise ValueError
        return UUID(public_id)
    except (ValueError, TypeError):
        raise ContractError(_DENIED) from None


def _lock_binding(allocation_id: UUID, moment: datetime) -> tuple[ModelAllocation, ModelPendingGrant, Range]:
    """Lock the range, allocation and grant in canonical authorization order."""
    from engine.models import ModelAllocation, ModelPendingGrant, Range

    candidate = ModelAllocation.objects.filter(pk=allocation_id).first()
    if candidate is None:
        raise ContractError(_DENIED)
    range_obj = Range.objects.select_for_update().filter(uuid=candidate.range_id).first()
    allocation = ModelAllocation.objects.select_for_update().get(pk=allocation_id)
    grant = ModelPendingGrant.objects.select_for_update().filter(allocation=allocation).first()
    if (
        range_obj is None
        or grant is None
        or grant.state not in {"pending", "active"}
        or not _allocation_is_current(allocation, range_obj, moment)
        or range_obj.status not in {Range.Status.PENDING, Range.Status.PROVISIONING, Range.Status.READY}
        or range_obj.egress_mode == "none"
    ):
        raise ContractError(_DENIED)
    _recheck_authority(allocation)
    return allocation, grant, range_obj


def _allocation_is_current(allocation: ModelAllocation, range_obj: Range, moment: datetime) -> bool:
    """Check allocation lifetime and exact execution and policy generations."""
    return (
        allocation.released_at is None
        and allocation.deadline > moment
        and range_obj.provisioner_operation_id == allocation.operation_id
        and range_obj.model_source_policy_revision == allocation.source_policy_revision
    )


def issue_model_enrollment(*, allocation_id: UUID, operation_id: UUID, now: datetime | None = None) -> ModelEnrollment:
    """Issue only for the admitted operation and its already-reserved network."""
    from engine.models import ModelAccessCredential

    moment = now or timezone.now()
    with transaction.atomic():
        allocation, grant, range_obj = _lock_binding(allocation_id, moment)
        if allocation.operation_id != operation_id:
            raise ContractError(_DENIED)
        subnets = _trusted_subnets(range_obj, allocation)
        previous = ModelAccessCredential.objects.select_for_update().filter(grant=grant).first()
        if previous is not None:
            grant.grant_epoch += 1
            fence_revoked_requests(allocation_id=allocation.pk)
        grant.state = "pending"
        grant.save(update_fields=["state", "grant_epoch"])
        token = _token(grant.public_id)
        expires = min(moment + timedelta(seconds=120), allocation.deadline)
        ModelAccessCredential.objects.update_or_create(
            grant=grant,
            defaults={
                "grant_epoch": grant.grant_epoch,
                "admitted_subnets": subnets,
                "enrollment_hash": _hash(token),
                "enrollment_expires_at": expires,
                "access_hash": "",
                "access_expires_at": None,
                "refresh_hash": "",
                "hard_expires_at": min(moment + timedelta(hours=8), allocation.deadline),
            },
        )
        _audit(grant, "enrollment issued")
        return ModelEnrollment(grant_id=grant.public_id, enrollment_token=SecretStr(token), expires_at=expires)


def _trusted_subnets(range_obj: Range, allocation: ModelAllocation) -> list[str]:
    """Resolve only incumbent private subnet reservations owned by this range."""
    from engine.models import SubnetAllocation

    # A participant/request cannot choose a network. Read the incumbent subnet
    # reservation owned by this exact range and request, across either cloud.
    values = list(
        SubnetAllocation.objects.filter(range_id=range_obj.pk, request_id=str(allocation.request_id))
        .order_by("cidr")
        .values_list("cidr", flat=True)[:65]
    )
    if not values or len(values) > 64:
        raise ContractError(_NETWORK_UNAVAILABLE)
    for value in values:
        try:
            subnet = ipaddress.IPv4Network(value, strict=True)
        except ValueError:
            raise ContractError(_NETWORK_UNAVAILABLE) from None
        if not any(subnet.subnet_of(private) for private in RFC1918_IPV4_NETWORKS):
            raise ContractError(_NETWORK_UNAVAILABLE)
    return values


def _lock_credential(
    token: str, peer: str, kind: str, moment: datetime
) -> tuple[ModelAllocation, ModelPendingGrant, ModelAccessCredential]:
    """Lock and verify the current credential, token deadline and socket peer."""
    from engine.models import ModelAccessCredential, ModelPendingGrant

    public_id = _parse_token(token)
    candidate = ModelPendingGrant.objects.filter(pk=public_id).first()
    if candidate is None:
        raise ContractError(_DENIED)
    allocation, grant, range_obj = _lock_binding(candidate.allocation_id, moment)
    credential = ModelAccessCredential.objects.select_for_update().filter(grant=grant).first()
    if credential is None or credential.grant_epoch != grant.grant_epoch or credential.hard_expires_at <= moment:
        raise ContractError(_DENIED)
    _verify_token(credential, grant, token, kind, moment)
    current_subnets = _trusted_subnets(range_obj, allocation)
    if current_subnets != credential.admitted_subnets or not any(
        peer_matches_binding(peer, subnet) for subnet in current_subnets
    ):
        raise ContractError(_DENIED)
    return allocation, grant, credential


def _verify_token(
    credential: ModelAccessCredential,
    grant: ModelPendingGrant,
    token: str,
    kind: str,
    moment: datetime,
) -> None:
    """Require the current token kind, constant-time hash match and unexpired deadline."""
    if (kind == "enrollment" and grant.state != "pending") or (kind != "enrollment" and grant.state != "active"):
        raise ContractError(_DENIED)
    expected = getattr(credential, f"{kind}_hash")
    if not expected or not secrets.compare_digest(expected, _hash(token)):
        raise ContractError(_DENIED)
    deadline = getattr(credential, f"{kind}_expires_at", credential.hard_expires_at)
    if deadline is None or deadline <= moment:
        raise ContractError(_DENIED)


def _rotate(grant: ModelPendingGrant, credential: ModelAccessCredential, moment: datetime) -> ModelTokenPair:
    """Replace both guest capabilities while consuming the previous token pair."""
    window = credential.rotation_window_started_at
    if window is None or moment >= window + timedelta(seconds=60):
        credential.rotation_window_started_at = moment
        credential.rotation_count = 0
    if credential.rotation_count >= 60:
        raise ContractError("credential.rate_limited")
    credential.rotation_count += 1
    access, refresh = _token(grant.public_id), _token(grant.public_id)
    expires = min(moment + timedelta(minutes=5), credential.hard_expires_at)
    credential.enrollment_hash = ""
    credential.access_hash = _hash(access)
    credential.access_expires_at = expires
    credential.refresh_hash = _hash(refresh)
    credential.save(
        update_fields=[
            "enrollment_hash",
            "access_hash",
            "access_expires_at",
            "refresh_hash",
            "updated_at",
            "rotation_window_started_at",
            "rotation_count",
        ]
    )
    _audit(grant, "credential rotated")
    return ModelTokenPair(
        access_token=SecretStr(access),
        refresh_token=SecretStr(refresh),
        access_expires_at=expires,
        hard_expires_at=credential.hard_expires_at,
    )


def exchange_model_enrollment(*, token: str, transport_peer: str, now: datetime | None = None) -> ModelTokenPair:
    """Consume enrollment exactly once and return fresh opaque guest tokens."""
    moment = now or timezone.now()
    with transaction.atomic():
        _, grant, credential = _lock_credential(token, transport_peer, "enrollment", moment)
        grant.state = "active"
        grant.save(update_fields=["state"])
        return _rotate(grant, credential, moment)


def refresh_model_access(*, token: str, transport_peer: str, now: datetime | None = None) -> ModelTokenPair:
    """Consume the current refresh token and invalidate its predecessor pair."""
    moment = now or timezone.now()
    with transaction.atomic():
        from ._model_credential_transition import refresh_successor

        successor = refresh_successor(token, transport_peer, moment)
        if successor is not None:
            return successor
        _, grant, credential = _lock_credential(token, transport_peer, "refresh", moment)
        return _rotate(grant, credential, moment)


def authenticate_model_access(
    *, token: str, transport_peer: str, now: datetime | None = None
) -> ModelAccessAuthorization:
    """Recheck generation, owner projection, epoch, expiry and socket peer."""
    moment = now or timezone.now()
    with transaction.atomic():
        allocation, grant, credential = _lock_credential(token, transport_peer, "access", moment)
        policy = EffectivePolicy.model_validate(allocation.snapshot["effective_policy"])
        if not policy.admissible or policy.effective_profile is None:
            raise ContractError(_DENIED)
        return ModelAccessAuthorization(
            allocation_id=allocation.pk,
            operation_id=allocation.operation_id,
            grant_epoch=grant.grant_epoch,
            aliases=allocation.snapshot["shards"],
            limits=policy.effective_profile.limits,
            hard_expires_at=credential.hard_expires_at,
        )


def _audit(grant: ModelPendingGrant, context: str) -> None:
    """Audit credential lifecycle events without recording capability material."""
    from engine.models import ModelAccessCredential
    from shared.audit import AuditActorType, AuditEvent, audit_log
    from shared.audit.vocabulary import AuditAction, AuditEntityType

    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.MODEL_CREDENTIAL.value,
            entity_id=ModelAccessCredential.objects.only("pk").get(grant=grant).pk,
            action=AuditAction.UPDATE.value,
            actor_type=AuditActorType.SYSTEM,
            context=context,
            entity_ref=str(grant.public_id),
        ),
        strict=True,
    )
