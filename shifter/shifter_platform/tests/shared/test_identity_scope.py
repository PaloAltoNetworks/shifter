"""Closed, dependency-neutral identity and resource scope contracts."""

from uuid import UUID, uuid4

import pytest

from shared.identity_scope import PrincipalRef, ResourceScope, ScopeContractError


def test_principal_ref_keeps_one_stable_identity_independent_of_credentials():
    principal_id = uuid4()
    assert PrincipalRef(uuid=principal_id, kind="human").uuid == principal_id
    assert PrincipalRef(uuid=principal_id, kind="service").uuid == principal_id


@pytest.mark.parametrize("kind", ["", "user", "operator", None])
def test_principal_ref_rejects_unknown_kind(kind):
    with pytest.raises(ScopeContractError):
        PrincipalRef(uuid=uuid4(), kind=kind)


@pytest.mark.parametrize("identifier", [None, "not-a-uuid", UUID(int=0)])
def test_principal_ref_rejects_noncanonical_identifier(identifier):
    with pytest.raises(ScopeContractError):
        PrincipalRef(uuid=identifier, kind="human")


def test_installation_scope_is_explicit_and_has_no_customer_ids():
    assert ResourceScope(kind="installation").kind == "installation"
    with pytest.raises(ScopeContractError):
        ResourceScope(kind="installation", account_uuid=uuid4())


def test_account_scope_allows_direct_individual_and_nested_workspace_shapes():
    account_id, organization_id, workspace_id = uuid4(), uuid4(), uuid4()
    assert ResourceScope(kind="account", account_uuid=account_id).workspace_uuid is None
    scope = ResourceScope(
        kind="account",
        account_uuid=account_id,
        organization_uuid=organization_id,
        workspace_uuid=workspace_id,
    )
    assert scope.workspace_uuid == workspace_id


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "account"},
        {"kind": "account", "workspace_uuid": uuid4()},
        {"kind": "account", "account_uuid": uuid4(), "workspace_uuid": uuid4()},
        {"kind": "account", "account_uuid": "not-a-uuid"},
        {"kind": "unknown", "account_uuid": uuid4()},
    ],
)
def test_malformed_customer_scope_fails_closed(fields):
    with pytest.raises(ScopeContractError):
        ResourceScope(**fields)
