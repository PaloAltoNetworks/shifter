from uuid import UUID

import pytest

from shared.authorization import AuthorizationContractError, TargetRef
from shared.authorization.relationships import (
    AdministrativeRoleChange,
    GroupMembershipChange,
    PolicyEffect,
    PolicyRelationshipChange,
    RelationshipSubject,
    RoleAssignmentChange,
    VersionedRelationshipChange,
)

SUBJECT_ID = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE_ID = UUID("33333333-3333-3333-3333-333333333333")


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("principal", f"principal:{SUBJECT_ID}"),
        ("group", f"group:{SUBJECT_ID}#member"),
        ("role", f"role:{SUBJECT_ID}#assignee"),
    ],
)
def test_subjects_have_closed_native_userset_forms(kind: str, expected: str) -> None:
    assert RelationshipSubject(kind, SUBJECT_ID).openfga_user == expected


def test_grant_removes_revocation_fence_and_writes_positive_relation() -> None:
    change = PolicyRelationshipChange(
        subject=RelationshipSubject("principal", SUBJECT_ID),
        action="workspace.read",
        target=TargetRef("workspace", WORKSPACE_ID),
        effect=PolicyEffect.GRANT,
    )

    assert change.writes[0].relation == "grant_workspace_read"
    assert change.deletes[0].relation == "deny_workspace_read"
    assert change.writes[0].object == f"workspace:{WORKSPACE_ID}"


def test_revoke_writes_fence_before_deleting_positive_relation() -> None:
    change = PolicyRelationshipChange(
        subject=RelationshipSubject("role", SUBJECT_ID),
        action="workspace.read",
        target=TargetRef("workspace", WORKSPACE_ID),
        effect=PolicyEffect.REVOKE,
    )

    assert change.writes[0].relation == "deny_workspace_read"
    assert change.deletes[0].relation == "grant_workspace_read"


def test_relationship_contract_rejects_arbitrary_subject_or_action_target() -> None:
    with pytest.raises(AuthorizationContractError):
        RelationshipSubject("user", SUBJECT_ID)  # type: ignore[arg-type]
    with pytest.raises(AuthorizationContractError, match="target"):
        PolicyRelationshipChange(
            subject=RelationshipSubject("principal", SUBJECT_ID),
            action="account.read",
            target=TargetRef("workspace", WORKSPACE_ID),
            effect=PolicyEffect.GRANT,
        )


def test_native_group_membership_uses_exclusion_as_revoke_fence() -> None:
    change = GroupMembershipChange(WORKSPACE_ID, SUBJECT_ID, PolicyEffect.REVOKE)

    assert change.writes[0].relation == "excluded"
    assert change.writes[0].object == f"group:{WORKSPACE_ID}"
    assert change.deletes[0].relation == "direct_member"


def test_native_role_assignment_accepts_principals_and_groups_only() -> None:
    change = RoleAssignmentChange(
        WORKSPACE_ID,
        RelationshipSubject("group", SUBJECT_ID),
        PolicyEffect.GRANT,
    )

    assert change.writes[0].user == f"group:{SUBJECT_ID}#member"
    assert change.writes[0].relation == "direct_assignee"
    with pytest.raises(AuthorizationContractError):
        RoleAssignmentChange(
            WORKSPACE_ID,
            RelationshipSubject("role", SUBJECT_ID),
            PolicyEffect.GRANT,
        )


def test_predefined_administrator_assignments_use_specific_revocation_fence() -> None:
    change = AdministrativeRoleChange(
        RelationshipSubject("principal", SUBJECT_ID),
        "workspace_administrator",
        TargetRef("workspace", WORKSPACE_ID),
        PolicyEffect.REVOKE,
    )

    assert change.writes[0].relation == "deny_administrator"
    assert change.deletes[0].relation == "direct_administrator"
    assert change.writes[0].object == f"workspace:{WORKSPACE_ID}"


def test_predefined_administrator_cannot_be_nested_in_a_custom_role() -> None:
    with pytest.raises(AuthorizationContractError, match="subject"):
        AdministrativeRoleChange(
            RelationshipSubject("role", SUBJECT_ID),
            "workspace_administrator",
            TargetRef("workspace", WORKSPACE_ID),
            PolicyEffect.GRANT,
        )


def test_versioned_change_supersedes_prior_binding_without_deleting_provider_state() -> None:
    base = PolicyRelationshipChange(
        subject=RelationshipSubject("principal", SUBJECT_ID),
        action="workspace.read",
        target=TargetRef("workspace", WORKSPACE_ID),
        effect=PolicyEffect.REVOKE,
    )

    change = VersionedRelationshipChange(base, "a" * 64, 2)

    assert change.deletes == ()
    assert [(item.relation, item.object) for item in change.writes] == [
        ("candidate", f"authorization_binding:{'a' * 64}-2"),
        ("deny_workspace_read", f"workspace:{WORKSPACE_ID}"),
        ("superseded", f"authorization_binding:{'a' * 64}-1"),
    ]
    assert change.writes[1].user == f"authorization_binding:{'a' * 64}-2#active"
