"""Closed sharing-authority projection contracts for PLAT-202 M20."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from shared.model_access import (
    AuthorityState,
    EligibilityBasis,
    ModelAccessRangePage,
    PublisherAuthorityEvidence,
    PublisherAuthorityRequirement,
    PublisherAuthorityScope,
    ResolvedSubjectAuthority,
    SelectorAuthorityEvidence,
    SelectorResolution,
    SharingAuthorityEvidence,
    SpendingEligibilityEvidence,
    SubjectAuthorizationEvidence,
)

_DEPLOYMENT = UUID("11111111-1111-4111-8111-111111111111")
_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _projection(**overrides):
    payload = {
        "contract_version": "model-access-sharing-authority/v1",
        "deployment_id": _DEPLOYMENT,
        "sharing_binding_id": "binding-a",
        "selector_digest": f"sha256:{'a' * 64}",
        "membership_revision": 4,
        "assessment_count": 3,
        "selector_authorities": (
            {
                "authority_ref": {"owner": "ctf", "reference": "event:e-1"},
                "authority_revision": 7,
                "state": "allowed",
            },
        ),
        "state": "allowed",
        "member_refs": (
            {"owner": "deployment", "reference": "range:r-2"},
            {"owner": "ctf", "reference": "draw:d-1"},
            {"owner": "deployment", "reference": "range:r-1"},
        ),
        "subject_authorizations": (
            {
                "subject_ref": {"owner": "deployment", "reference": "range:r-2"},
                "authority_ref": {"owner": "cms", "reference": "range:r-2"},
                "authority_revision": 2,
                "state": "allowed",
            },
            {
                "subject_ref": {"owner": "ctf", "reference": "draw:d-1"},
                "authority_ref": {"owner": "ctf", "reference": "participant:p-1"},
                "authority_revision": 3,
                "state": "allowed",
            },
            {
                "subject_ref": {"owner": "deployment", "reference": "range:r-1"},
                "authority_ref": {"owner": "cms", "reference": "range:r-1"},
                "authority_revision": 5,
                "state": "allowed",
            },
        ),
        "publisher_authorities": (
            {
                "publisher_ref": {"owner": "deployment", "reference": "operator:platform"},
                "authority_ref": {"owner": "management", "reference": "operator:1"},
                "authority_revision": 9,
                "selector_digest": f"sha256:{'a' * 64}",
                "scope": "deployment",
                "state": "allowed",
            },
        ),
        "spending_eligibilities": (),
        "observed_at": _NOW,
        "freshness_deadline": _NOW + timedelta(minutes=5),
    }
    payload.update(overrides)
    return SharingAuthorityEvidence.model_validate(payload)


def test_projection_normalizes_complete_owned_references_without_discarding_owner():
    projection = _projection()

    assert [(item.owner, item.reference) for item in projection.member_refs] == [
        ("ctf", "draw:d-1"),
        ("deployment", "range:r-1"),
        ("deployment", "range:r-2"),
    ]
    assert projection.subject_authorization_for(projection.member_refs[0]).authority_revision == 3
    assert projection.subject_authorization_for({"owner": "foreign", "reference": "draw:d-1"}) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "maybe"),
        ("membership_revision", 0),
        (
            "selector_authorities",
            (
                {
                    "authority_ref": {"owner": "ctf", "reference": "event:e-1"},
                    "authority_revision": -1,
                    "state": "allowed",
                },
            ),
        ),
        ("member_refs", ("range:r-1",)),
        ("observed_at", datetime(2026, 9, 14, 12)),
        ("freshness_deadline", _NOW - timedelta(seconds=1)),
    ],
)
def test_projection_rejects_open_or_non_authoritative_shapes(field, value):
    with pytest.raises(ValidationError):
        _projection(**{field: value})


def test_projection_rejects_duplicate_members_and_missing_subject_authorization():
    duplicate = (
        {"owner": "deployment", "reference": "range:r-1"},
        {"owner": "deployment", "reference": "range:r-1"},
    )
    with pytest.raises(ValidationError, match="member_refs"):
        _projection(member_refs=duplicate)

    with pytest.raises(ValidationError, match="subject authorization"):
        _projection(subject_authorizations=())

    with pytest.raises(ValidationError, match="assessment_count"):
        _projection(assessment_count=2)


def test_range_page_is_bounded_sorted_and_carries_assessment_continuation():
    first = UUID(int=1)
    second = UUID(int=2)
    page = ModelAccessRangePage(
        items=(
            {
                "range_ref": {"owner": "deployment", "reference": "range:1"},
                "authority_ref": {"owner": "engine", "reference": "range:1"},
                "range_uuid": first,
                "owner_user_id": 1,
                "workspace_id": 1,
            },
            {
                "range_ref": {"owner": "deployment", "reference": "range:2"},
                "authority_ref": {"owner": "engine", "reference": "range:2"},
                "range_uuid": second,
                "owner_user_id": 1,
                "workspace_id": 1,
            },
        ),
        assessment_count=3,
        continuation=second,
    )

    assert page.assessment_count == 3
    assert page.continuation == second
    invalid = page.model_dump()
    invalid["continuation"] = first
    with pytest.raises(ValidationError, match="continuation"):
        ModelAccessRangePage.model_validate(invalid)


def test_publisher_and_spending_evidence_keep_independent_revisions():
    selector = SelectorAuthorityEvidence(
        authority_ref={"owner": "ctf", "reference": "event:e-1"},
        authority_revision=7,
        state=AuthorityState.ALLOWED,
    )
    publisher = PublisherAuthorityEvidence(
        publisher_ref={"owner": "deployment", "reference": "operator:platform"},
        authority_ref={"owner": "management", "reference": "operator:1"},
        authority_revision=11,
        selector_digest=f"sha256:{'a' * 64}",
        scope=PublisherAuthorityScope.DEPLOYMENT,
        state=AuthorityState.ALLOWED,
    )
    spending = SpendingEligibilityEvidence(
        authority_ref={"owner": "management", "reference": "group:4"},
        eligibility_revision=13,
        state=AuthorityState.ALLOWED,
        basis=EligibilityBasis.MANAGED_MEMBERSHIP,
    )
    subject = SubjectAuthorizationEvidence(
        subject_ref={"owner": "deployment", "reference": "range:r-1"},
        authority_ref={"owner": "cms", "reference": "range:r-1"},
        authority_revision=17,
        state=AuthorityState.ALLOWED,
    )

    assert selector.authority_revision == 7
    assert publisher.authority_revision == 11
    assert spending.eligibility_revision == 13
    assert subject.authority_revision == 17


def test_owner_resolution_is_closed_bounded_and_complete():
    resolution = SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=f"sha256:{'b' * 64}",
        assessment_count=2,
        member_refs=(
            {"owner": "deployment", "reference": "range:r-2"},
            {"owner": "deployment", "reference": "range:r-1"},
        ),
        selector_authority_refs=({"owner": "workspaces", "reference": "workspace:w-1"},),
        subject_authorities=(
            {
                "subject_ref": {"owner": "deployment", "reference": "range:r-1"},
                "authority_ref": {"owner": "engine", "reference": "range:r-1"},
            },
            {
                "subject_ref": {"owner": "deployment", "reference": "range:r-2"},
                "authority_ref": {"owner": "engine", "reference": "range:r-2"},
            },
        ),
        publisher_requirements=(
            {
                "selector_digest": f"sha256:{'b' * 64}",
                "authority_ref": {"owner": "workspaces", "reference": "workspace:w-1"},
                "scope": "selector",
            },
        ),
    )

    assert isinstance(resolution.subject_authorities[0], ResolvedSubjectAuthority)
    assert isinstance(resolution.publisher_requirements[0], PublisherAuthorityRequirement)
    assert [item.reference for item in resolution.member_refs] == ["range:r-1", "range:r-2"]

    invalid = resolution.model_dump(mode="json")
    invalid["subject_authorities"] = []
    with pytest.raises(ValidationError, match="subject authority"):
        SelectorResolution.model_validate(invalid)
