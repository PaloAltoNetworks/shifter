"""Engine sharing-authority invalidation and canonical range fencing."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from shared.model_access import (
    AuthorityInvalidation,
    PublisherAuthorityScope,
    SelectorResolution,
    SharingSelector,
    compute_digest,
)
from shared.model_access.core_models import SelectorKind

from .test_sharing import (
    _DEPLOYMENT,
    _OTHER_DEPLOYMENT,
    _PUBLISHER,
    _SUBJECT,
    _binding_dto,
    _catalog,
    _membership,
    _pool_dto,
    _preview,
    _publish,
    _services,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_membership_projection_is_monotonic_and_exact_replay_is_idempotent():
    svc = _services()
    observed_at = timezone.now()
    first = _membership(svc, "binding-a", revision=2, observed_at=observed_at)
    replay = _membership(svc, "binding-a", revision=2, observed_at=observed_at)
    assert replay.pk == first.pk

    with pytest.raises(svc["SharingError"]) as lower:
        _membership(
            svc,
            "binding-a",
            revision=1,
            authority_revision=2,
            publish_fences=False,
            observed_at=observed_at,
        )
    assert lower.value.code == "sharing.membership_revision_regressed"

    with pytest.raises(svc["SharingError"]) as conflict:
        _membership(svc, "binding-a", revision=2, members=("range:r-2",), observed_at=observed_at)
    assert conflict.value.code == "sharing.membership_revision_conflict"


def test_membership_projection_rolls_back_when_strict_audit_fails(monkeypatch):
    from engine.models import MembershipProjection

    svc = _services()

    def fail_audit(event, *, strict=False):
        assert strict is True
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("shared.audit.audit_log", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        _membership(svc, "audit-failure")

    assert not MembershipProjection.objects.filter(
        deployment_id=_DEPLOYMENT,
        sharing_binding_id="audit-failure",
    ).exists()


def test_matching_uses_the_complete_owned_reference():
    svc = _services()
    catalog = _catalog()
    _publish(svc, catalog, _binding_dto(), _pool_dto())

    foreign = _preview(
        svc,
        catalog,
        subject={"owner": "foreign-deployment", "reference": "range:r-1"},
    )
    assert foreign.contributions == ()


def test_snapshot_inclusion_still_checks_live_subject_authority_fence():
    svc = _services()
    catalog = _catalog()
    _publish(svc, catalog, _binding_dto(mode="snapshot"), _pool_dto())

    svc["fence"](
        deployment_id=_DEPLOYMENT,
        authority_ref={"owner": "cms", "reference": "range:r-1"},
        authority_revision=2,
        state="revoked",
    )

    assert _preview(svc, catalog).contributions == ()


def test_publish_rechecks_current_publisher_authority():
    svc = _services()
    catalog = _catalog()
    binding = _binding_dto()
    _membership(svc, "binding-a")
    svc["fence"](
        deployment_id=_DEPLOYMENT,
        authority_ref={"owner": "management", "reference": "operator:platform"},
        authority_revision=2,
        state="revoked",
    )

    with pytest.raises(svc["SharingError"]) as denied:
        _publish(svc, catalog, binding, _pool_dto(), membership=False)
    assert denied.value.code == "sharing.publisher_authority_required"


def test_publish_requires_every_authority_fact_for_a_multi_owner_selector():
    svc = _services()
    catalog = _catalog()
    selector = SharingSelector(kind=SelectorKind.SELECTED_RANGES, ids=("r-1", "r-2"))
    digest = compute_digest(selector)
    authority_refs = (
        {"owner": "engine", "reference": "range:r-1"},
        {"owner": "engine", "reference": "range:r-2"},
    )
    selector_authority_ref = {"owner": "cms", "reference": "selected-range-set:one"}
    resolution = SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=digest,
        assessment_count=1,
        member_refs=(_SUBJECT,),
        selector_authority_refs=(selector_authority_ref,),
        subject_authorities=({"subject_ref": _SUBJECT, "authority_ref": authority_refs[0]},),
        publisher_requirements=tuple(
            {
                "selector_digest": digest,
                "authority_ref": authority_ref,
                "scope": PublisherAuthorityScope.SELECTOR,
            }
            for authority_ref in authority_refs
        ),
    )
    now = timezone.now()
    svc["project_resolution"](
        deployment_id=_DEPLOYMENT,
        sharing_binding_id="binding-a",
        publisher_identity=_PUBLISHER,
        resolution=resolution,
        observed_at=now,
        freshness_deadline=now + timedelta(minutes=5),
    )
    svc["invalidate"](
        AuthorityInvalidation(
            deployment_id=_DEPLOYMENT,
            authority_refs=(authority_refs[1],),
            state="revoked",
            reason="range-authority-revoked",
        )
    )

    binding = _binding_dto(selector=selector.model_dump(mode="json"))
    with pytest.raises(svc["SharingError"]) as denied:
        _publish(svc, catalog, binding, _pool_dto(), membership=False)
    assert denied.value.code == "sharing.publisher_authority_required"


def test_all_ranges_requires_deployment_scoped_publisher_authority():
    svc = _services()
    catalog = _catalog()
    binding = _binding_dto()
    _membership(svc, "binding-a", publisher_scope=PublisherAuthorityScope.SELECTOR)

    with pytest.raises(svc["SharingError"]) as denied:
        _publish(svc, catalog, binding, _pool_dto(), membership=False)
    assert denied.value.code == "sharing.deployment_operator_required"


def test_funded_auth_group_requires_independent_spending_eligibility():
    svc = _services()
    catalog = _catalog()
    selector = {"kind": "auth_group", "ids": ["4"]}
    binding = _binding_dto(selector=selector)
    digest = compute_digest(binding.selector)
    _membership(
        svc,
        "binding-a",
        selector_digest=digest,
        publisher_scope=PublisherAuthorityScope.SELECTOR,
    )
    with pytest.raises(svc["SharingError"]) as denied:
        _publish(svc, catalog, binding, _pool_dto(), membership=False)
    assert denied.value.code == "sharing.spending_eligibility_required"

    eligibility = (
        {
            "authority_ref": {"owner": "management", "reference": "auth-group:4"},
            "eligibility_revision": 1,
            "state": "allowed",
            "basis": "managed_membership",
        },
    )
    _membership(
        svc,
        "binding-a",
        selector_digest=digest,
        revision=2,
        publisher_scope=PublisherAuthorityScope.SELECTOR,
        spending_eligibilities=eligibility,
    )
    binding = _binding_dto(selector=selector, membership_revision=2)
    published = _publish(svc, catalog, binding, _pool_dto(), membership=False)
    assert published.definition_revision == 1


def test_funded_multi_group_selector_requires_eligibility_for_every_group():
    svc = _services()
    catalog = _catalog()
    selector = {"kind": "auth_group", "ids": ["4", "5"]}
    binding = _binding_dto(selector=selector)
    digest = compute_digest(binding.selector)
    eligibility = (
        {
            "authority_ref": {"owner": "management", "reference": "auth-group:4"},
            "eligibility_revision": 1,
            "state": "allowed",
            "basis": "managed_membership",
        },
    )
    _membership(
        svc,
        "binding-a",
        selector_digest=digest,
        publisher_scope=PublisherAuthorityScope.SELECTOR,
        spending_eligibilities=eligibility,
    )

    with pytest.raises(svc["SharingError"]) as denied:
        _publish(svc, catalog, binding, _pool_dto(), membership=False)
    assert denied.value.code == "sharing.spending_eligibility_required"


def test_owner_invalidation_advances_the_shared_fence_before_fanout():
    svc = _services()
    authority_ref = {"owner": "management", "reference": "user:7"}
    svc["fence"](
        deployment_id=_DEPLOYMENT,
        authority_ref=authority_ref,
        authority_revision=1,
        state="allowed",
    )
    svc["fence"](
        deployment_id=_OTHER_DEPLOYMENT,
        authority_ref=authority_ref,
        authority_revision=1,
        state="allowed",
    )

    changed = svc["invalidate"](
        AuthorityInvalidation(
            deployment_id=_DEPLOYMENT,
            authority_refs=(authority_ref,),
            state="revoked",
            reason="user-disabled",
        )
    )
    assert changed == 1

    from engine.models import SharingAuthorityFence

    first = SharingAuthorityFence.objects.get(
        deployment_id=_DEPLOYMENT,
        authority_owner="management",
        authority_reference="user:7",
    )
    other = SharingAuthorityFence.objects.get(
        deployment_id=_OTHER_DEPLOYMENT,
        authority_owner="management",
        authority_reference="user:7",
    )
    assert (first.authority_revision, first.state) == (2, "revoked")
    assert (other.authority_revision, other.state) == (1, "allowed")


def test_range_mutation_invalidates_range_collection_owner_and_workspace_fences(django_user_model):
    from engine.models import Range, SharingAuthorityFence

    svc = _services()
    owner = django_user_model.objects.create_user("range-fence@example.test")
    refs = (
        {"owner": "engine", "reference": "all-ranges"},
        {"owner": "management", "reference": f"user:{owner.pk}"},
        {"owner": "workspaces", "reference": "workspace-id:51"},
    )
    for authority_ref in refs:
        svc["fence"](
            deployment_id=_DEPLOYMENT,
            authority_ref=authority_ref,
            authority_revision=1,
            state="allowed",
        )

    range_obj = Range.objects.create(user=owner, workspace_id=51, status=Range.Status.READY)
    for authority_ref in refs:
        fence = SharingAuthorityFence.objects.get(
            deployment_id=_DEPLOYMENT,
            authority_owner=authority_ref["owner"],
            authority_reference=authority_ref["reference"],
        )
        assert (fence.authority_revision, fence.state) == (2, "unknown")

    range_ref = {"owner": "engine", "reference": f"range:{range_obj.uuid}"}
    svc["fence"](
        deployment_id=_DEPLOYMENT,
        authority_ref=range_ref,
        authority_revision=1,
        state="allowed",
    )
    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])
    range_fence = SharingAuthorityFence.objects.get(
        deployment_id=_DEPLOYMENT,
        authority_owner="engine",
        authority_reference=f"range:{range_obj.uuid}",
    )
    assert (range_fence.authority_revision, range_fence.state) == (2, "unknown")


def test_owner_resolution_refreshes_fences_and_publishes_next_membership_revision():
    svc = _services()
    digest = f"sha256:{'c' * 64}"
    authority_ref = {"owner": "ctf", "reference": "event:e-1"}
    resolution = SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=digest,
        assessment_count=1,
        member_refs=({"owner": "deployment", "reference": "range:r-1"},),
        selector_authority_refs=(authority_ref,),
        subject_authorities=(
            {
                "subject_ref": {"owner": "deployment", "reference": "range:r-1"},
                "authority_ref": {"owner": "engine", "reference": "range:r-1"},
            },
        ),
        publisher_requirements=({"selector_digest": digest, "authority_ref": authority_ref, "scope": "selector"},),
    )
    now = timezone.now()
    first = svc["project_resolution"](
        deployment_id=_DEPLOYMENT,
        sharing_binding_id="binding-a",
        publisher_identity=_PUBLISHER,
        resolution=resolution,
        observed_at=now,
        freshness_deadline=now + timedelta(minutes=5),
    )
    assert first.membership_revision == 1

    svc["invalidate"](
        AuthorityInvalidation(
            deployment_id=_DEPLOYMENT,
            authority_refs=(authority_ref,),
            state="unknown",
            reason="event-membership-changed",
        )
    )
    refreshed = svc["project_resolution"](
        deployment_id=_DEPLOYMENT,
        sharing_binding_id="binding-a",
        publisher_identity=_PUBLISHER,
        resolution=resolution,
        observed_at=now + timedelta(seconds=1),
        freshness_deadline=now + timedelta(minutes=5),
    )
    assert refreshed.membership_revision == 2
    assert refreshed.selector_authorities[0]["authority_revision"] == 3
