from uuid import UUID

import pytest

from shared.authorization import (
    ACTION_CATALOG,
    APPLICATION_ADMINISTRATOR_ACTIONS,
    PREDEFINED_POLICIES,
    AuthorizationContractError,
    AuthorizationDecision,
    AuthorizationRequest,
    CredentialCeiling,
    DecisionKind,
    TargetRef,
    action_definition,
    predefined_policy_definition,
)
from shared.identity_scope import PrincipalRef, ResourceScope

PRINCIPAL_ID = UUID("11111111-1111-1111-1111-111111111111")
ACCOUNT_ID = UUID("22222222-2222-2222-2222-222222222222")
WORKSPACE_ID = UUID("33333333-3333-3333-3333-333333333333")
ORGANIZATION_ID = UUID("44444444-4444-4444-4444-444444444444")


def _workspace_scope() -> ResourceScope:
    return ResourceScope(
        kind="account",
        account_uuid=ACCOUNT_ID,
        organization_uuid=ORGANIZATION_ID,
        workspace_uuid=WORKSPACE_ID,
    )


def test_application_administrator_is_exactly_every_administrative_action() -> None:
    registered = frozenset(action.code for action in ACTION_CATALOG if action.administrative)

    assert registered == APPLICATION_ADMINISTRATOR_ACTIONS
    assert registered
    application = predefined_policy_definition("application_administrator")
    assert application.actions == registered
    assert application.relation == "administrator"


def test_action_catalog_has_unique_codes_and_equivalent_principal_coverage() -> None:
    codes = [action.code for action in ACTION_CATALOG]

    assert len(codes) == len(set(codes))
    assert all(action.principal_kinds == frozenset({"human", "service"}) for action in ACTION_CATALOG)
    assert len(PREDEFINED_POLICIES) == len({item.code for item in PREDEFINED_POLICIES})


@pytest.mark.parametrize(
    ("action", "target_type"),
    [
        ("account.create_event", "account"),
        ("organization.create_event", "organization"),
        ("workspace.create_event", "workspace"),
        ("event.manage_config", "event"),
        ("event.manage_teams", "event"),
        ("event.manage_ranges", "event"),
        ("event.manage_scoring", "event"),
        ("event.manage_awards", "event"),
        ("event.manage_submissions", "event"),
        ("event.manage_content", "event"),
        ("event.manage_lifecycle", "event"),
        ("event.delete", "event"),
        ("event.manage_staff", "event"),
        ("event.transfer_ownership", "event"),
    ],
)
def test_ctf_administrative_actions_are_registered_for_humans_and_services(action, target_type) -> None:
    definition = action_definition(action)
    assert definition.target_type == target_type
    assert definition.principal_kinds == frozenset({"human", "service"})
    assert action in APPLICATION_ADMINISTRATOR_ACTIONS


def test_event_authority_topology_actions_require_administrator_and_cannot_be_delegated() -> None:
    for action in ("event.manage_staff", "event.transfer_ownership"):
        definition = action_definition(action)
        assert definition.requires_administrator
        assert not definition.delegable


def test_unknown_action_fails_closed() -> None:
    with pytest.raises(AuthorizationContractError, match="Unknown authorization action"):
        action_definition("workspace.not_registered")


def test_request_rejects_target_or_scope_mismatch() -> None:
    with pytest.raises(AuthorizationContractError, match="target"):
        AuthorizationRequest(
            principal=PrincipalRef(PRINCIPAL_ID, "human"),
            action="workspace.read",
            target=TargetRef("account", ACCOUNT_ID),
            scope=_workspace_scope(),
            credential=CredentialCeiling(frozenset({"workspace.read"})),
        )


def test_request_rejects_action_outside_credential_ceiling() -> None:
    with pytest.raises(AuthorizationContractError, match="credential ceiling"):
        AuthorizationRequest(
            principal=PrincipalRef(PRINCIPAL_ID, "service"),
            action="workspace.read",
            target=TargetRef("workspace", WORKSPACE_ID),
            scope=_workspace_scope(),
            credential=CredentialCeiling(frozenset()),
        )


def test_credential_target_is_an_independent_immutable_ceiling():
    from uuid import uuid4

    target = TargetRef("workspace", WORKSPACE_ID)
    credential = CredentialCeiling(frozenset({"workspace.read"}), target)
    assert credential.permits("workspace.read", target)
    assert not credential.permits("workspace.read")
    assert not credential.permits("workspace.read", TargetRef("workspace", uuid4()))
    with pytest.raises(AuthorizationContractError, match="credential ceiling"):
        AuthorizationRequest(
            PrincipalRef(PRINCIPAL_ID, "human"),
            "workspace.read",
            target,
            _workspace_scope(),
            CredentialCeiling(credential.actions, TargetRef("workspace", uuid4())),
        )


def test_installation_target_has_no_object_id_or_customer_scope() -> None:
    request = AuthorizationRequest(
        principal=PrincipalRef(PRINCIPAL_ID, "service"),
        action="installation.manage_accounts",
        target=TargetRef("installation"),
        scope=ResourceScope(kind="installation"),
        credential=CredentialCeiling(frozenset({"installation.manage_accounts"})),
    )

    assert request.target.uuid is None


def test_decision_has_bounded_classification_without_provider_message() -> None:
    denied = AuthorizationDecision(DecisionKind.DENIED, reason="policy_denied")
    failed = AuthorizationDecision(DecisionKind.EVALUATOR_ERROR, reason="evaluator_unavailable")

    assert denied.allowed is False
    assert failed.allowed is False
    with pytest.raises(AuthorizationContractError, match="reason"):
        AuthorizationDecision(DecisionKind.DENIED, reason="raw provider error: token=secret")
