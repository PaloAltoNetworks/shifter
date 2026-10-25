from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from management.models import Principal
from shared.audit import AuditAction
from shared.authorization import (
    ACTION_CATALOG,
    AdministrativeRoleChange,
    AuthorizationDecision,
    AuthorizationProviderError,
    CredentialCeiling,
    DecisionKind,
    GroupMembershipChange,
    PolicyEffect,
    RelationshipState,
    RelationshipSubject,
    TargetRef,
)
from shared.identity_scope import PrincipalRef, ResourceScope
from shared.models import AuditLog
from workspaces.models import Account, AuthorizationGroup, AuthorizationOperation, Organization, Workspace
from workspaces.services import (
    AuthorizationAdminError,
    AuthorizationMutationConflict,
    NativeRelationshipMutationRequest,
    PolicyMutationRequest,
    apply_native_relationship_mutation,
    apply_policy_mutation,
    list_authorization_groups,
    reconcile_policy_mutation,
)

ACTOR_ID = UUID("11111111-1111-1111-1111-111111111111")
SUBJECT_ID = UUID("22222222-2222-2222-2222-222222222222")
MODEL_ID = "01J00000000000000000000000"


@pytest.fixture(autouse=True)
def _authorization_principals(db) -> None:
    actor_user = get_user_model().objects.create_user(username="actor")
    Principal.objects.filter(user=actor_user).update(uuid=ACTOR_ID)
    Principal.objects.create(uuid=SUBJECT_ID, kind=Principal.Kind.SERVICE, name="Service subject")


class FakeProvider:
    model_id = MODEL_ID
    store_id = "01J00000000000000000000001"

    def __init__(
        self,
        *,
        allowed: bool = True,
        write_error: bool = False,
        state: RelationshipState | None = None,
        denied_actions: frozenset[str] = frozenset(),
    ):
        self.allowed = allowed
        self.write_error = write_error
        self.state = state or RelationshipState(grant_present=True, deny_present=False)
        self.changes = []
        self.check_requests = []
        self.denied_actions = denied_actions

    def check(self, request):
        self.check_requests.append(request)
        allowed = self.allowed and request.action not in self.denied_actions
        kind = DecisionKind.ALLOWED if allowed else DecisionKind.DENIED
        reason = "policy_allowed" if allowed else "policy_denied"
        return AuthorizationDecision(kind, reason)

    def batch_check(self, requests):
        return tuple(self.check(request) for request in requests)

    def write_relationships(self, change):
        self.changes.append(change)
        if self.write_error:
            raise AuthorizationProviderError("OpenFGA relationship write failed")

    def read_relationships(self, change):
        return self.state


class CrashAfterReservationProvider(FakeProvider):
    def write_relationships(self, change):
        raise SystemExit("simulated process loss")


def _request(
    account: Account,
    *,
    effect: PolicyEffect = PolicyEffect.GRANT,
    key: str = "grant-1",
) -> PolicyMutationRequest:
    action = "account.read"
    return PolicyMutationRequest(
        actor=PrincipalRef(ACTOR_ID, "human"),
        credential=CredentialCeiling(frozenset({action, "account.manage_authorization"})),
        subject=RelationshipSubject("principal", SUBJECT_ID),
        action=action,
        target=TargetRef("account", account.uuid),
        scope=ResourceScope(kind="account", account_uuid=account.uuid),
        effect=effect,
        idempotency_key=key,
        model_id=MODEL_ID,
    )


@pytest.mark.django_db
def test_grant_records_intent_before_effect_and_confirms_only_after_readback() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    provider = FakeProvider()

    result = apply_policy_mutation(_request(account), provider)

    row = AuthorizationOperation.objects.get(pk=result.operation_id)
    assert row.state == AuthorizationOperation.State.CONFIRMED
    assert row.request_digest
    assert row.fence_key
    assert provider.changes[0].effect == PolicyEffect.GRANT
    assert set(AuditLog.objects.exclude(entity_type="principal").values_list("action", flat=True)) == {
        AuditAction.AUTHORIZATION_REQUESTED,
        AuditAction.AUTHORIZATION_CONFIRMED,
    }


@pytest.mark.django_db
def test_uncertain_write_remains_unresolved_and_blocks_conflicting_edit() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    provider = FakeProvider(write_error=True)
    result = apply_policy_mutation(_request(account), provider)

    assert result.state == AuthorizationOperation.State.UNRESOLVED
    assert AuditLog.objects.filter(action=AuditAction.AUTHORIZATION_UNRESOLVED).exists()
    with pytest.raises(AuthorizationMutationConflict, match="unresolved"):
        apply_policy_mutation(_request(account, effect=PolicyEffect.REVOKE, key="revoke-1"), FakeProvider())


@pytest.mark.django_db
def test_requested_operation_is_recovered_on_idempotent_redelivery() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    request = _request(account, key="crash-recovery")

    with pytest.raises(SystemExit, match="process loss"):
        apply_policy_mutation(request, CrashAfterReservationProvider())
    operation = AuthorizationOperation.objects.get(idempotency_key="crash-recovery")
    assert operation.state == AuthorizationOperation.State.REQUESTED
    assert operation.reconcile_lease_until is not None

    blocked_provider = FakeProvider()
    still_owned = apply_policy_mutation(request, blocked_provider)
    assert still_owned.state == AuthorizationOperation.State.REQUESTED
    assert blocked_provider.changes == []

    operation.reconcile_lease_until = timezone.now() - timedelta(seconds=1)
    operation.save(update_fields=["reconcile_lease_until"])

    recovered = apply_policy_mutation(request, FakeProvider())

    operation.refresh_from_db()
    assert recovered.state == AuthorizationOperation.State.CONFIRMED
    assert operation.state == AuthorizationOperation.State.CONFIRMED
    assert operation.reconcile_lease_until is None


@pytest.mark.django_db
def test_reconciliation_advances_only_when_exact_primary_state_matches() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    result = apply_policy_mutation(_request(account), FakeProvider(write_error=True))

    unchanged = reconcile_policy_mutation(result.operation_id, FakeProvider(state=RelationshipState(False, False)))
    confirmed = reconcile_policy_mutation(result.operation_id, FakeProvider(state=RelationshipState(True, False)))

    assert unchanged.state == AuthorizationOperation.State.UNRESOLVED
    assert confirmed.state == AuthorizationOperation.State.CONFIRMED


@pytest.mark.django_db
def test_revocation_writes_deny_fence_and_requires_grant_absence() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    provider = FakeProvider(state=RelationshipState(grant_present=False, deny_present=True))

    result = apply_policy_mutation(_request(account, effect=PolicyEffect.REVOKE, key="revoke-1"), provider)

    assert result.state == AuthorizationOperation.State.CONFIRMED
    assert any(item.relation == "deny_account_read" for item in provider.changes[0].writes)


@pytest.mark.django_db
def test_delegation_denial_records_no_requested_external_effect() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")

    result = apply_policy_mutation(_request(account), FakeProvider(allowed=False))

    assert result.state == AuthorizationOperation.State.DENIED
    assert AuthorizationOperation.objects.get(pk=result.operation_id).state == AuthorizationOperation.State.DENIED
    assert AuditLog.objects.filter(action=AuditAction.AUTHORIZATION_DENIED).exists()


@pytest.mark.django_db
def test_denied_attempt_does_not_create_a_gap_in_provider_generations() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    first_provider = FakeProvider()
    denied_provider = FakeProvider(allowed=False)
    final_provider = FakeProvider(state=RelationshipState(grant_present=False, deny_present=True))

    first = apply_policy_mutation(_request(account, key="generation-1"), first_provider)
    denied = apply_policy_mutation(
        _request(account, effect=PolicyEffect.REVOKE, key="denied-generation"),
        denied_provider,
    )
    final = apply_policy_mutation(
        _request(account, effect=PolicyEffect.REVOKE, key="generation-2"),
        final_provider,
    )

    assert AuthorizationOperation.objects.get(pk=first.operation_id).generation == 1
    assert AuthorizationOperation.objects.get(pk=denied.operation_id).generation == 1
    assert AuthorizationOperation.objects.get(pk=final.operation_id).generation == 2
    assert any(
        item.relation == "superseded" and item.object.endswith("-1") for item in final_provider.changes[0].writes
    )


@pytest.mark.django_db
def test_cross_account_target_is_denied_before_external_effect() -> None:
    owning_account = Account.objects.create(kind=Account.Kind.TEAM, name="Owning")
    other_account = Account.objects.create(kind=Account.Kind.TEAM, name="Other")
    request = _request(owning_account)
    cross_account = PolicyMutationRequest(
        actor=request.actor,
        credential=request.credential,
        subject=request.subject,
        action=request.action,
        target=TargetRef("account", other_account.uuid),
        scope=request.scope,
        effect=request.effect,
        idempotency_key="cross-account",
        model_id=request.model_id,
    )
    provider = FakeProvider()

    result = apply_policy_mutation(cross_account, provider)

    assert result.state == AuthorizationOperation.State.DENIED
    assert provider.changes == []


@pytest.mark.django_db
def test_same_caller_idempotency_key_is_isolated_between_account_scopes() -> None:
    first = Account.objects.create(kind=Account.Kind.TEAM, name="First")
    second = Account.objects.create(kind=Account.Kind.TEAM, name="Second")

    first_result = apply_policy_mutation(_request(first, key="caller-local-key"), FakeProvider())
    second_result = apply_policy_mutation(_request(second, key="caller-local-key"), FakeProvider())

    assert first_result.state == AuthorizationOperation.State.CONFIRMED
    assert second_result.state == AuthorizationOperation.State.CONFIRMED
    assert first_result.operation_id != second_result.operation_id
    assert AuthorizationOperation.objects.filter(idempotency_key="caller-local-key").count() == 2


@pytest.mark.django_db
def test_admin_service_rejects_forged_subdivision_under_individual_account() -> None:
    account = Account.objects.create(
        kind=Account.Kind.INDIVIDUAL,
        name="Individual",
        individual_principal_uuid=ACTOR_ID,
    )
    organization = Organization.objects.create(account=account, name="Forged")
    workspace = Workspace.objects.create(organization=organization, name="Forged")
    provider = FakeProvider()
    scope = ResourceScope(
        kind="account",
        account_uuid=account.uuid,
        organization_uuid=organization.uuid,
        workspace_uuid=workspace.uuid,
    )

    with pytest.raises(AuthorizationAdminError, match="authorization denied"):
        list_authorization_groups(
            PrincipalRef(ACTOR_ID, "human"),
            CredentialCeiling(frozenset({"workspace.manage_authorization"})),
            scope,
            provider,
        )

    assert provider.check_requests == []


def _actions_at_or_below(target_type: str) -> frozenset[str]:
    hierarchy = ("installation", "account", "organization", "workspace", "event", "range")
    root_index = hierarchy.index(target_type)
    return frozenset(
        item.code
        for item in ACTION_CATALOG
        if hierarchy.index(item.target_type) >= root_index and (item.delegable or item.requires_administrator)
    )


@pytest.mark.django_db
def test_group_membership_requires_full_scope_delegation_and_supports_service_principals() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    group = AuthorizationGroup.objects.create(
        scope_kind="account",
        account_uuid=account.uuid,
        name="Operators",
    )
    request = NativeRelationshipMutationRequest(
        actor=PrincipalRef(ACTOR_ID, "human"),
        credential=CredentialCeiling(_actions_at_or_below("account")),
        change=GroupMembershipChange(group.uuid, SUBJECT_ID, PolicyEffect.GRANT),
        scope=ResourceScope(kind="account", account_uuid=account.uuid),
        idempotency_key="group-member-1",
        model_id=MODEL_ID,
    )

    result = apply_native_relationship_mutation(request, FakeProvider())

    operation = AuthorizationOperation.objects.get(pk=result.operation_id)
    assert result.state == AuthorizationOperation.State.CONFIRMED
    assert operation.relationship_kind == AuthorizationOperation.RelationshipKind.GROUP_MEMBERSHIP
    assert operation.subject_uuid == SUBJECT_ID


@pytest.mark.django_db
def test_group_self_add_is_denied_before_external_effect() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    group = AuthorizationGroup.objects.create(
        scope_kind="account",
        account_uuid=account.uuid,
        name="Operators",
    )
    provider = FakeProvider()
    request = NativeRelationshipMutationRequest(
        actor=PrincipalRef(ACTOR_ID, "human"),
        credential=CredentialCeiling(_actions_at_or_below("account")),
        change=GroupMembershipChange(group.uuid, ACTOR_ID, PolicyEffect.GRANT),
        scope=ResourceScope(kind="account", account_uuid=account.uuid),
        idempotency_key="group-self-add",
        model_id=MODEL_ID,
    )

    result = apply_native_relationship_mutation(request, provider)

    assert result.state == AuthorizationOperation.State.DENIED
    assert provider.changes == []


@pytest.mark.django_db
def test_predefined_administrator_checks_exact_policy_actions_not_unrelated_actions() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    organization = Organization.objects.create(account=account, name="O")
    workspace = Workspace.objects.create(organization=organization, name="W")
    scope = ResourceScope(
        kind="account",
        account_uuid=account.uuid,
        organization_uuid=organization.uuid,
        workspace_uuid=workspace.uuid,
    )
    provider = FakeProvider()
    request = NativeRelationshipMutationRequest(
        actor=PrincipalRef(ACTOR_ID, "human"),
        credential=CredentialCeiling(frozenset(item.code for item in ACTION_CATALOG)),
        change=AdministrativeRoleChange(
            RelationshipSubject("principal", SUBJECT_ID),
            "workspace_administrator",
            TargetRef("workspace", workspace.uuid),
            PolicyEffect.GRANT,
        ),
        scope=scope,
        idempotency_key="workspace-admin-exact-actions",
        model_id=MODEL_ID,
    )

    result = apply_native_relationship_mutation(request, provider)

    checked_actions = {item.action for item in provider.check_requests}
    assert result.state == AuthorizationOperation.State.CONFIRMED
    assert "workspace.update" in checked_actions
    assert "workspace.read" in checked_actions
    assert "workspace.leave" not in checked_actions
    assert "workspace.launch_range" not in checked_actions


@pytest.mark.django_db
def test_predefined_administrator_denies_when_a_concrete_descendant_permission_is_denied(monkeypatch) -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    organization = Organization.objects.create(account=account, name="O")
    workspace = Workspace.objects.create(organization=organization, name="W")
    event = TargetRef("event", UUID("33333333-3333-3333-3333-333333333333"))
    scope = ResourceScope(
        kind="account",
        account_uuid=account.uuid,
        organization_uuid=organization.uuid,
        workspace_uuid=workspace.uuid,
    )
    inventory_calls = []

    def resolve_descendants(workspace_ids, limit):
        inventory_calls.append((workspace_ids, limit))
        return (event,)

    monkeypatch.setattr(
        "workspaces.services._authorization_delegation.resolve_authorization_descendants",
        resolve_descendants,
    )
    provider = FakeProvider(denied_actions=frozenset({"event.manage"}))
    request = NativeRelationshipMutationRequest(
        actor=PrincipalRef(ACTOR_ID, "human"),
        credential=CredentialCeiling(frozenset(item.code for item in ACTION_CATALOG)),
        change=AdministrativeRoleChange(
            RelationshipSubject("principal", SUBJECT_ID),
            "workspace_administrator",
            TargetRef("workspace", workspace.uuid),
            PolicyEffect.GRANT,
        ),
        scope=scope,
        idempotency_key="workspace-admin-descendant-denied",
        model_id=MODEL_ID,
    )

    result = apply_native_relationship_mutation(request, provider)

    assert result.state == AuthorizationOperation.State.DENIED
    assert inventory_calls == [((workspace.pk,), 1000)]
    assert any(item.action == "event.manage" and item.target == event for item in provider.check_requests)


@pytest.mark.django_db
def test_account_placed_event_is_included_in_account_delegation_proof() -> None:
    from ctf.models import CTFEvent

    account = Account.objects.create(
        kind=Account.Kind.INDIVIDUAL, name="Personal account", individual_principal_uuid=ACTOR_ID
    )
    now = timezone.now()
    event = CTFEvent.objects.create(
        name="Account event",
        created_by=get_user_model().objects.get(username="actor"),
        scope_kind="account",
        account_id=account.pk,
        scenario_id="synthetic",
        event_start=now,
        event_end=now + timedelta(days=1),
    )
    provider = FakeProvider(denied_actions=frozenset({"event.manage_config"}))
    request = NativeRelationshipMutationRequest(
        actor=PrincipalRef(ACTOR_ID, "human"),
        credential=CredentialCeiling(frozenset(item.code for item in ACTION_CATALOG)),
        change=AdministrativeRoleChange(
            RelationshipSubject("principal", SUBJECT_ID),
            "account_administrator",
            TargetRef("account", account.uuid),
            PolicyEffect.GRANT,
        ),
        scope=ResourceScope("account", account.uuid),
        idempotency_key="account-event-descendant-denied",
        model_id=MODEL_ID,
    )

    result = apply_native_relationship_mutation(request, provider)

    assert result.state == AuthorizationOperation.State.DENIED
    assert any(
        item.action == "event.manage_config" and item.target == TargetRef("event", event.id)
        for item in provider.check_requests
    )


@pytest.mark.django_db
def test_event_policy_mutation_requires_exact_account_event_scope() -> None:
    from ctf.models import CTFEvent

    first = Account.objects.create(
        kind=Account.Kind.INDIVIDUAL, name="First account", individual_principal_uuid=ACTOR_ID
    )
    sibling = Account.objects.create(
        kind=Account.Kind.INDIVIDUAL, name="Sibling account", individual_principal_uuid=SUBJECT_ID
    )
    now = timezone.now()
    event = CTFEvent.objects.create(
        name="Account event",
        created_by=get_user_model().objects.get(username="actor"),
        scope_kind="account",
        account_id=first.pk,
        scenario_id="synthetic",
        event_start=now,
        event_end=now + timedelta(days=1),
    )
    action = "event.manage_config"
    request = PolicyMutationRequest(
        actor=PrincipalRef(ACTOR_ID, "human"),
        credential=CredentialCeiling(frozenset({action, "event.manage"})),
        subject=RelationshipSubject("principal", SUBJECT_ID),
        action=action,
        target=TargetRef("event", event.id),
        scope=ResourceScope("account", sibling.uuid),
        effect=PolicyEffect.GRANT,
        idempotency_key="sibling-event-policy-denied",
        model_id=MODEL_ID,
    )

    provider = FakeProvider()
    result = apply_policy_mutation(request, provider)

    assert result.state == AuthorizationOperation.State.DENIED
    assert provider.check_requests == []
    assert provider.changes == []
    assert provider.changes == []


@pytest.mark.parametrize("target_type", ["installation", "account", "organization"])
def test_broad_administrator_checks_each_descendant_with_its_own_scope(target_type) -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    organization = Organization.objects.create(account=account, name="O")
    workspace = Workspace.objects.create(organization=organization, name="W")
    target, scope = {
        "installation": (TargetRef("installation"), ResourceScope("installation")),
        "account": (TargetRef("account", account.uuid), ResourceScope("account", account.uuid)),
        "organization": (
            TargetRef("organization", organization.uuid),
            ResourceScope("account", account.uuid, organization.uuid),
        ),
    }[target_type]
    provider = FakeProvider()
    request = NativeRelationshipMutationRequest(
        actor=PrincipalRef(ACTOR_ID, "human"),
        credential=CredentialCeiling(frozenset(item.code for item in ACTION_CATALOG)),
        change=AdministrativeRoleChange(
            RelationshipSubject("principal", SUBJECT_ID),
            "application_administrator" if target_type == "installation" else f"{target_type}_administrator",
            target,
            PolicyEffect.GRANT,
        ),
        scope=scope,
        idempotency_key=f"broad-{target_type}",
        model_id=MODEL_ID,
    )

    result = apply_native_relationship_mutation(request, provider)

    assert result.state == AuthorizationOperation.State.CONFIRMED
    workspace_checks = [
        item for item in provider.check_requests if item.target == TargetRef("workspace", workspace.uuid)
    ]
    assert workspace_checks
    assert all(
        item.scope == ResourceScope("account", account.uuid, organization.uuid, workspace.uuid)
        for item in workspace_checks
    )


@pytest.mark.parametrize("changed_field", ["model_id", "store_id"])
def test_recovery_refuses_changed_provider_binding(changed_field) -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    result = apply_policy_mutation(_request(account), FakeProvider(write_error=True))
    replacement = FakeProvider()
    setattr(replacement, changed_field, "01J00000000000000000000009")

    with pytest.raises(AuthorizationMutationConflict, match="binding changed"):
        reconcile_policy_mutation(result.operation_id, replacement)

    assert replacement.changes == []
    operation = AuthorizationOperation.objects.get(pk=result.operation_id)
    assert operation.state == AuthorizationOperation.State.UNRESOLVED
    assert operation.reconcile_lease_until is None


def test_mutation_rejects_model_different_from_evaluator_before_reservation() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    provider = FakeProvider()

    with pytest.raises(AuthorizationMutationConflict, match="binding changed"):
        apply_policy_mutation(replace(_request(account), model_id="01J00000000000000000000009"), provider)

    assert provider.changes == []
    assert not AuthorizationOperation.objects.exists()


@pytest.mark.parametrize("target_type,action", [("event", "event.manage"), ("range", "range.manage")])
def test_leaf_mutation_rejects_unowned_target_even_when_evaluator_allows(target_type, action) -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    organization = Organization.objects.create(account=account, name="O")
    workspace = Workspace.objects.create(organization=organization, name="W")
    request = replace(
        _request(account),
        action=action,
        target=TargetRef(target_type, UUID("33333333-3333-3333-3333-333333333333")),
        scope=ResourceScope("account", account.uuid, organization.uuid, workspace.uuid),
        credential=CredentialCeiling(frozenset(item.code for item in ACTION_CATALOG)),
    )
    provider = FakeProvider()

    result = apply_policy_mutation(request, provider)

    assert result.state == AuthorizationOperation.State.DENIED
    assert provider.check_requests == []
    assert provider.changes == []


def test_disabled_human_actor_cannot_delegate_through_service_entrypoint() -> None:
    account = Account.objects.create(kind=Account.Kind.TEAM, name="A")
    get_user_model().objects.filter(identity_principal__uuid=ACTOR_ID).update(is_active=False)
    provider = FakeProvider()

    result = apply_policy_mutation(_request(account), provider)

    assert result.state == AuthorizationOperation.State.DENIED
    assert provider.check_requests == []
    assert provider.changes == []
