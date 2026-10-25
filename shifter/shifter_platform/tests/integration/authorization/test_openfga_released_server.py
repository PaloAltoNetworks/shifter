"""OpenFGA 1.20.0/PostgreSQL conformance and durable-write integration."""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.utils import timezone
from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
from openfga_sdk.exceptions import ApiException
from openfga_sdk.models import CreateStoreRequest, WriteAuthorizationModelRequest

from config.openfga_authorization import OpenFgaAuthorizationProvider, OpenFgaRuntimeSettings
from management.models import Principal
from shared.authorization import (
    ACTION_CATALOG,
    AdministrativeRoleChange,
    AuthorizationProviderError,
    AuthorizationRequest,
    CredentialCeiling,
    DecisionKind,
    GroupMembershipChange,
    PolicyEffect,
    PolicyRelationshipChange,
    RelationshipSubject,
    RoleAssignmentChange,
    TargetRef,
)
from shared.identity_scope import PrincipalRef, ResourceScope
from workspaces.models import Account, AuthorizationMutationFence, AuthorizationOperation
from workspaces.services import (
    AuthorizationMutationConflict,
    PolicyMutationRequest,
    apply_policy_mutation,
    reconcile_policy_mutation,
)

pytestmark = [pytest.mark.openfga, pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        if os.environ.get("OPENFGA_INTEGRATION_REQUIRED") == "1":
            pytest.fail(f"required OpenFGA integration setting is missing: {name}")
        pytest.skip("run through scripts/run_openfga_integration.sh")
    return value


@pytest.fixture
def provider() -> OpenFgaAuthorizationProvider:
    return OpenFgaAuthorizationProvider(
        OpenFgaRuntimeSettings(
            api_url=_required("OPENFGA_INTEGRATION_URL"),
            store_id=_required("OPENFGA_INTEGRATION_STORE_ID"),
            model_id=_required("OPENFGA_INTEGRATION_MODEL_ID"),
            api_token=_required("OPENFGA_INTEGRATION_TOKEN"),
            ca_cert_path=_required("OPENFGA_INTEGRATION_CA_CERT"),
            timeout_ms=2_000,
        )
    )


def _all_actions() -> CredentialCeiling:
    return CredentialCeiling(frozenset(item.code for item in ACTION_CATALOG))


def _write_fixture_tuple(provider: OpenFgaAuthorizationProvider, tuple_: ClientTuple) -> None:
    provider._client.write(
        ClientWriteRequest(writes=[tuple_]),
        {"authorization_model_id": provider._settings.model_id},
    )


def test_runtime_key_cannot_create_a_policy_store(provider) -> None:
    """Exercise the released API directly, beyond the application's allowlist."""
    with pytest.raises(ApiException):
        provider._client.create_store(CreateStoreRequest(name="synthetic-forbidden-runtime-store"))


def test_runtime_key_cannot_publish_models_assertions_or_delete_store(provider) -> None:
    """The pinned server fails every administrative write without its SQL duty."""
    model = provider._client.read_authorization_model().authorization_model
    model_write = WriteAuthorizationModelRequest(
        schema_version=model.schema_version,
        type_definitions=model.type_definitions,
        conditions=model.conditions,
    )
    with pytest.raises(ApiException):
        provider._client.write_authorization_model(model_write)
    with pytest.raises(ApiException):
        provider._client.write_assertions([])
    with pytest.raises(ApiException):
        provider._client.delete_store()
    # A denied deletion must leave the active store/model intact.
    assert provider._client.read_authorization_model().authorization_model.id == provider._settings.model_id


def test_distinct_admin_identity_can_publish_and_runtime_key_is_rejected(provider) -> None:
    """Admin API authority is separate from both runtime and schema ownership."""
    admin = OpenFgaAuthorizationProvider(
        OpenFgaRuntimeSettings(
            api_url=_required("OPENFGA_INTEGRATION_ADMIN_URL"),
            store_id=provider._settings.store_id,
            model_id=provider._settings.model_id,
            api_token=_required("OPENFGA_INTEGRATION_ADMIN_TOKEN"),
            ca_cert_path=provider._settings.ca_cert_path,
        )
    )
    wrong_key = OpenFgaAuthorizationProvider(
        OpenFgaRuntimeSettings(
            api_url=_required("OPENFGA_INTEGRATION_ADMIN_URL"),
            store_id=provider._settings.store_id,
            model_id=provider._settings.model_id,
            api_token=provider._settings.api_token,
            ca_cert_path=provider._settings.ca_cert_path,
        )
    )
    try:
        with pytest.raises(ApiException) as denied:
            wrong_key._client.read_authorization_model()
        assert denied.value.status == 401
        created = admin._client.create_store(CreateStoreRequest(name="synthetic-admin-store"))
        assert created.id != provider._settings.store_id
        model = admin._client.read_authorization_model().authorization_model
        published = admin._client.write_authorization_model(
            WriteAuthorizationModelRequest(
                schema_version=model.schema_version,
                type_definitions=model.type_definitions,
                conditions=model.conditions,
            )
        )
        assert published.authorization_model_id != provider._settings.model_id
    finally:
        admin._client.close()
        wrong_key._client.close()


def test_duty_reconciliation_rejects_a_runtime_login_with_admin_membership() -> None:
    """A valid login must not retain administrative authority via another role."""
    container = _required("OPENFGA_INTEGRATION_POSTGRES_CONTAINER")
    assert re.fullmatch(r"openfga-integration-\d+-postgres", container)
    command = ["docker", "exec", "-i", container, "psql", "-h", "127.0.0.1", "-U", "openfga", "-d", "openfga"]
    duties = Path(__file__).resolve().parents[5] / "platform/charts/shifter/files/openfga-duties.sql"
    subprocess.run(  # noqa: S603 -- harness-owned local PostgreSQL container, validated above
        [*command, "-v", "ON_ERROR_STOP=1"],
        input="GRANT shifter_openfga_admin TO integration_runtime;",
        text=True,
        capture_output=True,
        check=True,
    )
    try:
        result = subprocess.run(  # noqa: S603 -- harness-owned local PostgreSQL container
            [*command, "-v", "runtime_login=integration_runtime", "-v", "admin_login=integration_admin"],
            input=duties.read_text(),
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
    finally:
        subprocess.run(  # noqa: S603 -- harness-owned local PostgreSQL container
            [*command, "-v", "ON_ERROR_STOP=1"],
            input="REVOKE shifter_openfga_admin FROM integration_runtime;",
            text=True,
            capture_output=True,
            check=True,
        )


def test_released_model_hierarchy_human_service_deny_and_transport_fail_closed(provider) -> None:
    account_uuid = uuid4()
    human_uuid = uuid4()
    service_uuid = uuid4()
    scope = ResourceScope(kind="account", account_uuid=account_uuid)
    target = TargetRef("account", account_uuid)
    _write_fixture_tuple(
        provider,
        ClientTuple("installation:root", "installation", f"account:{account_uuid}"),
    )

    for principal_uuid in (human_uuid, service_uuid):
        provider.write_relationships(
            AdministrativeRoleChange(
                RelationshipSubject("principal", principal_uuid),
                "application_administrator",
                TargetRef("installation"),
                PolicyEffect.GRANT,
            )
        )
        decision = provider.check(
            AuthorizationRequest(
                PrincipalRef(principal_uuid, "human" if principal_uuid == human_uuid else "service"),
                "account.update",
                target,
                scope,
                _all_actions(),
            )
        )
        assert decision.allowed

    provider.write_relationships(
        PolicyRelationshipChange(
            RelationshipSubject("principal", human_uuid),
            "account.update",
            target,
            PolicyEffect.REVOKE,
        )
    )
    denied = provider.check(
        AuthorizationRequest(
            PrincipalRef(human_uuid, "human"),
            "account.update",
            target,
            scope,
            _all_actions(),
        )
    )
    assert denied.kind == DecisionKind.DENIED

    wrong_token = OpenFgaAuthorizationProvider(
        OpenFgaRuntimeSettings(
            api_url=_required("OPENFGA_INTEGRATION_URL"),
            store_id=_required("OPENFGA_INTEGRATION_STORE_ID"),
            model_id=_required("OPENFGA_INTEGRATION_MODEL_ID"),
            api_token="intentionally-wrong-integration-token",
            ca_cert_path=_required("OPENFGA_INTEGRATION_CA_CERT"),
        )
    )
    assert (
        wrong_token.check(
            AuthorizationRequest(
                PrincipalRef(service_uuid, "service"),
                "account.update",
                target,
                scope,
                _all_actions(),
            )
        ).kind
        == DecisionKind.EVALUATOR_ERROR
    )

    wrong_ca = OpenFgaAuthorizationProvider(
        OpenFgaRuntimeSettings(
            api_url=_required("OPENFGA_INTEGRATION_URL"),
            store_id=_required("OPENFGA_INTEGRATION_STORE_ID"),
            model_id=_required("OPENFGA_INTEGRATION_MODEL_ID"),
            api_token=_required("OPENFGA_INTEGRATION_TOKEN"),
            ca_cert_path="/etc/ssl/certs/ca-certificates.crt",
        )
    )
    assert (
        wrong_ca.check(
            AuthorizationRequest(
                PrincipalRef(service_uuid, "service"),
                "account.update",
                target,
                scope,
                _all_actions(),
            )
        ).kind
        == DecisionKind.EVALUATOR_ERROR
    )


def test_released_model_evaluates_direct_group_custom_role_and_scoped_predefined_usersets(provider) -> None:
    account_uuid = uuid4()
    organization_uuid = uuid4()
    workspace_uuid = uuid4()
    event_uuid = uuid4()
    group_uuid = uuid4()
    role_uuid = uuid4()
    direct_principal = uuid4()
    grouped_principal = uuid4()
    role_principal = uuid4()
    administrator_principal = uuid4()
    scope = ResourceScope(
        kind="account",
        account_uuid=account_uuid,
        organization_uuid=organization_uuid,
        workspace_uuid=workspace_uuid,
    )
    workspace = TargetRef("workspace", workspace_uuid)
    event = TargetRef("event", event_uuid)
    for tuple_ in (
        ClientTuple("installation:root", "installation", f"account:{account_uuid}"),
        ClientTuple(f"account:{account_uuid}", "account", f"organization:{organization_uuid}"),
        ClientTuple(f"organization:{organization_uuid}", "organization", f"workspace:{workspace_uuid}"),
        ClientTuple(f"workspace:{workspace_uuid}", "workspace", f"event:{event_uuid}"),
    ):
        _write_fixture_tuple(provider, tuple_)

    def allowed(principal_uuid, action: str, target: TargetRef) -> bool:
        return provider.check(
            AuthorizationRequest(
                PrincipalRef(principal_uuid, "service"),
                action,
                target,
                scope,
                _all_actions(),
            )
        ).allowed

    direct = PolicyRelationshipChange(
        RelationshipSubject("principal", direct_principal),
        "workspace.update",
        workspace,
        PolicyEffect.GRANT,
    )
    provider.write_relationships(direct)
    assert allowed(direct_principal, "workspace.update", workspace)
    provider.write_relationships(
        PolicyRelationshipChange(direct.subject, direct.action, direct.target, PolicyEffect.REVOKE)
    )
    assert not allowed(direct_principal, "workspace.update", workspace)

    provider.write_relationships(GroupMembershipChange(group_uuid, grouped_principal, PolicyEffect.GRANT))
    provider.write_relationships(
        PolicyRelationshipChange(
            RelationshipSubject("group", group_uuid),
            "workspace.update",
            workspace,
            PolicyEffect.GRANT,
        )
    )
    assert allowed(grouped_principal, "workspace.update", workspace)
    provider.write_relationships(GroupMembershipChange(group_uuid, grouped_principal, PolicyEffect.REVOKE))
    assert not allowed(grouped_principal, "workspace.update", workspace)

    provider.write_relationships(
        RoleAssignmentChange(
            role_uuid,
            RelationshipSubject("principal", role_principal),
            PolicyEffect.GRANT,
        )
    )
    provider.write_relationships(
        PolicyRelationshipChange(
            RelationshipSubject("role", role_uuid),
            "workspace.update",
            workspace,
            PolicyEffect.GRANT,
        )
    )
    assert allowed(role_principal, "workspace.update", workspace)
    provider.write_relationships(
        RoleAssignmentChange(
            role_uuid,
            RelationshipSubject("principal", role_principal),
            PolicyEffect.REVOKE,
        )
    )
    assert not allowed(role_principal, "workspace.update", workspace)

    provider.write_relationships(
        AdministrativeRoleChange(
            RelationshipSubject("principal", administrator_principal),
            "workspace_administrator",
            workspace,
            PolicyEffect.GRANT,
        )
    )
    assert allowed(administrator_principal, "event.manage", event)
    provider.write_relationships(
        AdministrativeRoleChange(
            RelationshipSubject("principal", administrator_principal),
            "workspace_administrator",
            workspace,
            PolicyEffect.REVOKE,
        )
    )
    assert not allowed(administrator_principal, "event.manage", event)


class _BoundProvider:
    @property
    def model_id(self):
        return self.provider.model_id

    @property
    def store_id(self):
        return self.provider.store_id


def test_released_model_denies_stale_parent_even_when_direct_permission_allows(provider) -> None:
    account_uuid, other_account_uuid, organization_uuid, principal_uuid = (uuid4() for _ in range(4))
    for tuple_ in (
        ClientTuple("installation:root", "installation", f"account:{account_uuid}"),
        ClientTuple("installation:root", "installation", f"account:{other_account_uuid}"),
        ClientTuple(f"account:{other_account_uuid}", "account", f"organization:{organization_uuid}"),
    ):
        _write_fixture_tuple(provider, tuple_)
    target = TargetRef("organization", organization_uuid)
    provider.write_relationships(
        PolicyRelationshipChange(
            RelationshipSubject("principal", principal_uuid), "organization.update", target, PolicyEffect.GRANT
        )
    )
    request = AuthorizationRequest(
        PrincipalRef(principal_uuid, "service"),
        "organization.update",
        target,
        ResourceScope("account", account_uuid, organization_uuid),
        _all_actions(),
    )

    assert not provider.check(request).allowed
    assert not provider.batch_check((request,))[0].allowed


def test_released_model_accepts_event_only_range_ancestry_and_denies_conflicting_parent(provider) -> None:
    account, organization, workspace, event, range_uuid, principal = (uuid4() for _ in range(6))
    for tuple_ in (
        ClientTuple("installation:root", "installation", f"account:{account}"),
        ClientTuple(f"account:{account}", "account", f"organization:{organization}"),
        ClientTuple(f"organization:{organization}", "organization", f"workspace:{workspace}"),
        ClientTuple(f"workspace:{workspace}", "workspace", f"event:{event}"),
        ClientTuple(f"event:{event}", "event", f"range:{range_uuid}"),
    ):
        _write_fixture_tuple(provider, tuple_)
    provider.write_relationships(
        PolicyRelationshipChange(
            RelationshipSubject("principal", principal),
            "range.read",
            TargetRef("range", range_uuid),
            PolicyEffect.GRANT,
        )
    )
    request = AuthorizationRequest(
        PrincipalRef(principal, "service"),
        "range.read",
        TargetRef("range", range_uuid),
        ResourceScope("account", account, organization, workspace),
        _all_actions(),
    )
    assert provider.check(request).allowed
    assert provider.batch_check((request,))[0].allowed
    _write_fixture_tuple(provider, ClientTuple(f"workspace:{uuid4()}", "workspace", f"range:{range_uuid}"))
    assert not provider.check(request).allowed
    assert not provider.batch_check((request,))[0].allowed


def test_released_model_allows_human_and_service_admin_on_account_event_and_rejects_extra_parent(provider) -> None:
    account, event = uuid4(), uuid4()
    _write_fixture_tuple(provider, ClientTuple("installation:root", "installation", f"account:{account}"))
    _write_fixture_tuple(provider, ClientTuple(f"account:{account}", "account", f"event:{event}"))
    requests = []
    for kind in ("human", "service"):
        principal = uuid4()
        provider.write_relationships(
            AdministrativeRoleChange(
                RelationshipSubject("principal", principal),
                "application_administrator",
                TargetRef("installation"),
                PolicyEffect.GRANT,
            )
        )
        for action in ("event.manage_staff", "event.transfer_ownership"):
            request = AuthorizationRequest(
                PrincipalRef(principal, kind),
                action,
                TargetRef("event", event),
                ResourceScope("account", account),
                _all_actions(),
            )
            assert provider.check(request).allowed
            requests.append(request)
        assert provider.check(
            AuthorizationRequest(
                PrincipalRef(principal, kind),
                "account.create_event",
                TargetRef("account", account),
                ResourceScope("account", account),
                _all_actions(),
            )
        ).allowed
    _write_fixture_tuple(provider, ClientTuple(f"workspace:{uuid4()}", "workspace", f"event:{event}"))
    assert all(not provider.check(request).allowed for request in requests)


@dataclass
class _DelayedLostResponse(_BoundProvider):
    provider: OpenFgaAuthorizationProvider

    def __post_init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()
        self.thread: threading.Thread | None = None

    def check(self, request):
        return self.provider.check(request)

    def batch_check(self, requests):
        return self.provider.batch_check(requests)

    def write_relationships(self, change):
        def delayed_write() -> None:
            self.entered.set()
            self.release.wait(timeout=10)
            self.provider.write_relationships(change)
            self.completed.set()

        self.thread = threading.Thread(target=delayed_write, daemon=True)
        self.thread.start()
        assert self.entered.wait(timeout=10)
        raise AuthorizationProviderError("simulated lost response")

    def read_relationships(self, change):
        return self.provider.read_relationships(change)


class _BlockingProvider(_BoundProvider):
    def __init__(self, provider: OpenFgaAuthorizationProvider) -> None:
        self.provider = provider
        self.entered = threading.Event()
        self.release = threading.Event()

    def check(self, request):
        return self.provider.check(request)

    def batch_check(self, requests):
        return self.provider.batch_check(requests)

    def write_relationships(self, change):
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise AuthorizationProviderError("integration synchronization timeout")
        self.provider.write_relationships(change)

    def read_relationships(self, change):
        return self.provider.read_relationships(change)


class _BlockingWriteThenReadError(_BlockingProvider):
    def read_relationships(self, change):
        raise AuthorizationProviderError("simulated stale dispatcher read failure")


class _BatchBarrierProvider(_BoundProvider):
    def __init__(self, provider: OpenFgaAuthorizationProvider, parties: int) -> None:
        self.provider = provider
        self.barrier = threading.Barrier(parties)

    def check(self, request):
        return self.provider.check(request)

    def batch_check(self, requests):
        self.barrier.wait(timeout=10)
        return self.provider.batch_check(requests)

    def write_relationships(self, change):
        self.provider.write_relationships(change)

    def read_relationships(self, change):
        return self.provider.read_relationships(change)


def test_postgres_fence_unknown_outcome_and_concurrent_revoke(provider) -> None:
    actor_user = get_user_model().objects.create_user(username=f"actor-{uuid4()}")
    actor = actor_user.identity_principal
    subject = Principal.objects.create(kind=Principal.Kind.SERVICE, name=f"subject-{uuid4()}")
    account = Account.objects.create(kind=Account.Kind.TEAM, name=f"Account {uuid4()}")
    scope = ResourceScope(kind="account", account_uuid=account.uuid)
    target = TargetRef("account", account.uuid)
    _write_fixture_tuple(provider, ClientTuple("installation:root", "installation", f"account:{account.uuid}"))
    provider.write_relationships(
        AdministrativeRoleChange(
            RelationshipSubject("principal", actor.uuid),
            "application_administrator",
            TargetRef("installation"),
            PolicyEffect.GRANT,
        )
    )
    credential = _all_actions()

    def request(effect: PolicyEffect, key: str) -> PolicyMutationRequest:
        return PolicyMutationRequest(
            actor=PrincipalRef(actor.uuid, "human"),
            credential=credential,
            subject=RelationshipSubject("principal", subject.uuid),
            action="account.update",
            target=target,
            scope=scope,
            effect=effect,
            idempotency_key=key,
            model_id=provider._settings.model_id,
        )

    delayed = _DelayedLostResponse(provider)
    uncertain = apply_policy_mutation(request(PolicyEffect.GRANT, "lost-response"), delayed)
    assert uncertain.state == "unresolved"
    assert reconcile_policy_mutation(uncertain.operation_id, provider).state == "confirmed"

    revoked_after_lost_response = apply_policy_mutation(
        request(PolicyEffect.REVOKE, "revoke-before-stale-arrival"),
        provider,
    )
    assert revoked_after_lost_response.state == "confirmed"
    delayed.release.set()
    assert delayed.thread is not None
    delayed.thread.join(timeout=10)
    assert not delayed.thread.is_alive()
    assert delayed.completed.is_set()
    assert (
        provider.check(
            AuthorizationRequest(
                PrincipalRef(subject.uuid, "service"),
                "account.update",
                target,
                scope,
                credential,
            )
        ).kind
        == DecisionKind.DENIED
    )

    collision_provider = _BatchBarrierProvider(provider, 2)
    other_subject = Principal.objects.create(kind=Principal.Kind.SERVICE, name=f"subject-{uuid4()}")
    collision_outcomes: list[str] = []

    def collide(subject_uuid) -> None:
        close_old_connections()
        try:
            collision_request = PolicyMutationRequest(
                actor=PrincipalRef(actor.uuid, "human"),
                credential=credential,
                subject=RelationshipSubject("principal", subject_uuid),
                action="account.update",
                target=target,
                scope=scope,
                effect=PolicyEffect.GRANT,
                idempotency_key="cross-fence-collision",
                model_id=provider._settings.model_id,
            )
            collision_outcomes.append(apply_policy_mutation(collision_request, collision_provider).state)
        except AuthorizationMutationConflict:
            collision_outcomes.append("conflict")
        finally:
            close_old_connections()

    collision_threads = [
        threading.Thread(target=collide, args=(candidate,), daemon=True)
        for candidate in (subject.uuid, other_subject.uuid)
    ]
    for collision_thread in collision_threads:
        collision_thread.start()
    for collision_thread in collision_threads:
        collision_thread.join(timeout=15)

    assert all(not collision_thread.is_alive() for collision_thread in collision_threads)
    assert sorted(collision_outcomes) == ["confirmed", "conflict"]

    stale_dispatcher = _BlockingWriteThenReadError(provider)
    takeover_outcome: list[str] = []

    def grant_with_expired_dispatch_lease() -> None:
        close_old_connections()
        try:
            result = apply_policy_mutation(
                request(PolicyEffect.GRANT, "expired-dispatch-lease"),
                stale_dispatcher,
            )
            takeover_outcome.append(result.state)
        finally:
            close_old_connections()

    takeover_thread = threading.Thread(target=grant_with_expired_dispatch_lease, daemon=True)
    takeover_thread.start()
    assert stale_dispatcher.entered.wait(timeout=10)
    operation = AuthorizationOperation.objects.get(idempotency_key="expired-dispatch-lease")
    operation.reconcile_lease_until = timezone.now() - timedelta(seconds=1)
    operation.save(update_fields=["reconcile_lease_until"])

    reconciled = reconcile_policy_mutation(operation.id, provider)
    assert reconciled.state == AuthorizationOperation.State.CONFIRMED
    stale_dispatcher.release.set()
    takeover_thread.join(timeout=10)

    operation.refresh_from_db()
    fence = AuthorizationMutationFence.objects.get(key=operation.fence_key)
    assert not takeover_thread.is_alive()
    assert takeover_outcome == [AuthorizationOperation.State.CONFIRMED]
    assert operation.state == AuthorizationOperation.State.CONFIRMED
    assert operation.reconcile_lease_until is None
    assert fence.blocked_operation_id is None

    blocking = _BlockingProvider(provider)
    outcome: list[str] = []

    def grant_in_thread() -> None:
        close_old_connections()
        try:
            outcome.append(apply_policy_mutation(request(PolicyEffect.GRANT, "concurrent-grant"), blocking).state)
        finally:
            close_old_connections()

    thread = threading.Thread(target=grant_in_thread, daemon=True)
    thread.start()
    assert blocking.entered.wait(timeout=10)
    with pytest.raises(AuthorizationMutationConflict, match="unresolved"):
        apply_policy_mutation(request(PolicyEffect.REVOKE, "concurrent-revoke"), provider)
    blocking.release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert outcome == ["confirmed"]

    revoked = apply_policy_mutation(request(PolicyEffect.REVOKE, "completed-revoke"), provider)
    assert revoked.state == "confirmed"
    # Redelivery of the completed older grant is idempotent and cannot emit a
    # late positive tuple after the newer revocation fence is confirmed.
    assert apply_policy_mutation(request(PolicyEffect.GRANT, "concurrent-grant"), provider).state == "confirmed"
    assert (
        provider.check(
            AuthorizationRequest(
                PrincipalRef(subject.uuid, "service"),
                "account.update",
                target,
                scope,
                credential,
            )
        ).kind
        == DecisionKind.DENIED
    )


@pytest.mark.parametrize("kind", ["human", "service"])
def test_prepared_administrator_discovers_hierarchy_and_edits_without_membership(provider, kind):
    from management import services as identities
    from shared.authorization.catalog import APPLICATION_ADMINISTRATOR_ACTIONS
    from shared.credentials import CredentialContext
    from workspaces import services as tenancy
    from workspaces.models import Organization, Workspace

    if kind == "human":
        user = get_user_model().objects.create_user(username=f"admin-{uuid4()}")
        principal = identities.principal_for_user(user)
    else:
        row = Principal.objects.create(kind="service", name="Synthetic administrator")
        principal = PrincipalRef(row.uuid, "service")
    actor = CredentialContext(
        principal,
        "session" if kind == "human" else "service",
        uuid4(),
        CredentialCeiling(APPLICATION_ADMINISTRATOR_ACTIONS),
        frozenset(),
    )
    account = tenancy.create_account(kind="team", name="Synthetic team")
    organization = Organization.objects.get(account_id=account.id)
    workspace = Workspace.objects.get(organization=organization)
    for user, relation, target in (
        ("installation:root", "installation", f"account:{account.uuid}"),
        (f"account:{account.uuid}", "account", f"organization:{organization.uuid}"),
        (f"organization:{organization.uuid}", "organization", f"workspace:{workspace.uuid}"),
    ):
        _write_fixture_tuple(provider, ClientTuple(user, relation, target))
    provider.write_relationships(
        AdministrativeRoleChange(
            RelationshipSubject("principal", principal.uuid),
            "application_administrator",
            TargetRef("installation"),
            PolicyEffect.GRANT,
        )
    )
    assert tenancy.admin_get_account(actor, provider, account.uuid).uuid == account.uuid
    assert tenancy.admin_list_organizations(actor, provider, account.uuid).results[0].uuid == organization.uuid
    assert (
        tenancy.admin_list_workspaces(actor, provider, account.uuid, organization.uuid).results[0].uuid
        == workspace.uuid
    )
    tenancy.admin_update_organization_profile(
        actor, provider, account.uuid, organization.uuid, {"description": "Updated"}
    )
    assert tenancy.admin_workspace_quota_usage(actor, provider, workspace.uuid).workspace_uuid == workspace.uuid
    assert not actor.ceiling.permits("installation.use_personal_tokens", TargetRef("installation"))
    limited = CredentialContext(
        principal,
        actor.kind,
        uuid4(),
        CredentialCeiling(frozenset({"account.read"}), target=TargetRef("account", account.uuid)),
        frozenset(),
    )
    assert tenancy.admin_get_account(limited, provider, account.uuid).uuid == account.uuid
    with pytest.raises(tenancy.AccountScopeError):
        tenancy.admin_update_organization_profile(
            limited, provider, account.uuid, organization.uuid, {"description": "Denied"}
        )
