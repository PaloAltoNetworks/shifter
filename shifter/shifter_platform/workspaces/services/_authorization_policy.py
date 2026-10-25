"""Scoped authorization policy responsibilities (ADR-066, #2315)."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal, cast
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.authorization import (
    AuthorizationProvider,
    AuthorizationProviderError,
    AuthorizationRequest,
    CredentialCeiling,
    PolicyEffect,
    PolicyRelationshipChange,
    RelationshipState,
)
from shared.identity_scope import PrincipalRef, ResourceScope
from workspaces.models import (
    AuthorizationOperation,
)

from ._account import resolve_resource_scope
from ._authorization_commands import (
    AuthorizationMutationConflict as AuthorizationMutationConflict,
)
from ._authorization_commands import (
    MutationRequest as MutationRequest,
)
from ._authorization_commands import (
    NativeRelationshipMutationRequest as NativeRelationshipMutationRequest,
)
from ._authorization_commands import (
    PolicyMutationRequest as PolicyMutationRequest,
)
from ._authorization_commands import (
    PolicyMutationResult as PolicyMutationResult,
)
from ._authorization_delegation import (
    _delegation_requests,
    _native_delegation_requests,
    _resolve_native_change,
    _resolve_policy_change,
)
from ._authorization_journal import (
    _assert_operation_provider,
    _assert_request_provider,
    _base_change_from_operation,
    _change_from_operation,
    _clear_reconcile_lease,
    _operation_result,
    _reserve,
    _set_outcome,
)

_RECONCILE_LEASE = timedelta(seconds=30)
_RECOVERABLE_STATES = {AuthorizationOperation.State.REQUESTED, AuthorizationOperation.State.UNRESOLVED}


def _matches(effect: str, state: RelationshipState) -> bool:
    """Require the intended tuple and absence of its opposing relationship."""
    if effect == PolicyEffect.GRANT:
        return bool(state.grant_present and not state.deny_present)
    return bool(state.deny_present and not state.grant_present)


def apply_policy_mutation(request: PolicyMutationRequest, provider: AuthorizationProvider) -> PolicyMutationResult:
    """Authorize, journal, apply and read back one serialized tuple change."""
    resolve_resource_scope(request.scope)
    _assert_request_provider(request, provider)
    try:
        _resolve_policy_change(request)
        decisions = provider.batch_check(_delegation_requests(request))
        allowed = len(decisions) == 2 and all(decision.allowed for decision in decisions)
    except Exception:
        allowed = False
    return _apply_authorized_mutation(request, provider, allowed)


def _apply_authorized_mutation(
    request: MutationRequest, provider: AuthorizationProvider, allowed: bool
) -> PolicyMutationResult:
    """Persist the authorization decision before attempting a provider write."""
    if not allowed:
        operation, _ = _reserve(
            request,
            provider,
            state=AuthorizationOperation.State.DENIED,
            reason="delegation_denied",
            block=False,
        )
        return _operation_result(operation)
    operation, created = _reserve(
        request,
        provider,
        state=AuthorizationOperation.State.REQUESTED,
        reason="accepted",
        block=True,
    )
    if not created and operation.state in _RECOVERABLE_STATES:
        return reconcile_policy_mutation(operation.id, provider)
    if created and operation.state == AuthorizationOperation.State.REQUESTED:
        operation = _write_and_confirm(operation, provider)
    return _operation_result(operation)


def _write_and_confirm(operation: AuthorizationOperation, provider: AuthorizationProvider) -> AuthorizationOperation:
    """Record confirmation only after the intended relationship is read back."""
    change = _change_from_operation(operation)
    try:
        provider.write_relationships(change)
        observed = provider.read_relationships(change)
    except AuthorizationProviderError:
        return _set_outcome(operation, AuthorizationOperation.State.UNRESOLVED, "provider_outcome_unknown")
    if not _matches(operation.effect, observed):
        return _set_outcome(operation, AuthorizationOperation.State.UNRESOLVED, "readback_mismatch")
    return _set_outcome(operation, AuthorizationOperation.State.CONFIRMED, "readback_confirmed")


def apply_native_relationship_mutation(
    request: NativeRelationshipMutationRequest,
    provider: AuthorizationProvider,
) -> PolicyMutationResult:
    """Apply a serialized native group membership or role assignment."""
    resolve_resource_scope(request.scope)
    _assert_request_provider(request, provider)
    try:
        _resolve_native_change(request)
        checks = _native_delegation_requests(request)
        decisions = provider.batch_check(checks)
        allowed = bool(checks) and len(decisions) == len(checks) and all(item.allowed for item in decisions)
    except Exception:
        allowed = False
    return _apply_authorized_mutation(request, provider, allowed)


def authorize_operation_reconciliation(
    operation_id: UUID,
    actor: PrincipalRef,
    credential: CredentialCeiling,
    provider: AuthorizationProvider,
) -> None:
    """Require current caller authority for every effect a recovery can replay."""
    operation = AuthorizationOperation.objects.get(pk=operation_id)
    _assert_operation_provider(operation, provider)
    scope = ResourceScope(
        cast(Literal["installation", "account"], operation.scope_kind),
        operation.account_uuid,
        operation.organization_uuid,
        operation.workspace_uuid,
    )
    resolve_resource_scope(scope)
    change = _base_change_from_operation(operation)
    checks: tuple[AuthorizationRequest, ...]
    if isinstance(change, PolicyRelationshipChange):
        request = PolicyMutationRequest(
            actor=actor,
            credential=credential,
            scope=scope,
            model_id=operation.model_id,
            idempotency_key=operation.idempotency_key,
            subject=change.subject,
            action=change.action,
            target=change.target,
            effect=change.effect,
        )
        _resolve_policy_change(request)
        checks = _delegation_requests(request)
    else:
        native_request = NativeRelationshipMutationRequest(
            actor=actor,
            credential=credential,
            scope=scope,
            model_id=operation.model_id,
            idempotency_key=operation.idempotency_key,
            change=change,
        )
        _resolve_native_change(native_request)
        checks = _native_delegation_requests(native_request)
    decisions = provider.batch_check(checks)
    if not checks or len(decisions) != len(checks) or not all(item.allowed for item in decisions):
        raise AuthorizationMutationConflict("authorization recovery denied")


def reconcile_policy_mutation(operation_id: UUID, provider: AuthorizationProvider) -> PolicyMutationResult:
    """Lease and recover a requested/ambiguous write using idempotent tuples."""
    with transaction.atomic():
        operation = AuthorizationOperation.objects.select_for_update().get(pk=operation_id)
        if operation.state not in _RECOVERABLE_STATES:
            return _operation_result(operation)
        _assert_operation_provider(operation, provider)
        now = timezone.now()
        if operation.reconcile_lease_until is not None and operation.reconcile_lease_until > now:
            return _operation_result(operation)
        operation.reconcile_lease_until = now + _RECONCILE_LEASE
        operation.save(update_fields=["reconcile_lease_until", "updated_at"])
    return _operation_result(_recover_leased_operation(operation, provider))


def _recover_leased_operation(
    operation: AuthorizationOperation, provider: AuthorizationProvider
) -> AuthorizationOperation:
    """Replay under the lease, retaining the fence until primary readback agrees."""
    change = _change_from_operation(operation)
    try:
        observed = provider.read_relationships(change)
        if not _matches(operation.effect, observed):
            provider.write_relationships(change)
            observed = provider.read_relationships(change)
    except AuthorizationProviderError:
        if operation.state == AuthorizationOperation.State.REQUESTED:
            return _set_outcome(operation, AuthorizationOperation.State.UNRESOLVED, "provider_outcome_unknown")
        observed = None
    if observed is None or not _matches(operation.effect, observed):
        return _clear_reconcile_lease(operation)
    return _set_outcome(operation, AuthorizationOperation.State.CONFIRMED, "reconciled_primary_read")
