"""Shared first-use assignment and fail-closed membership admission."""

from copy import deepcopy

import pytest

from engine.models import MembershipProjection, ModelAliasAssignment, ModelAllocation
from shared.model_access import ContractError, seal_catalog
from shared.model_access.core_models import AllocationStrategy, SharingFacet

from .test_model_allocation import allocate, allocation_inputs
from .test_sharing import _binding_dto, _pool_dto, _publish, _services

pytestmark = pytest.mark.django_db(transaction=True)


def shared_inputs(django_user_model, *, affinity="per_pool"):
    catalog, first, observations = allocation_inputs(django_user_model)
    _, second, _ = allocation_inputs(django_user_model)
    payload = catalog.model_dump(mode="json")
    other = deepcopy(payload["shards"][0])
    other["shard_id"] = "vertex-secondary"
    payload["shards"].append(other)
    payload["aliases"][0].update(
        strategy="weighted-rendezvous-v1", eligible_shard_ids=["vertex-primary", "vertex-secondary"]
    )
    catalog = seal_catalog(payload)
    requests = []
    for candidate in (first, second):
        requests.append(
            candidate.model_copy(
                update={
                    "subject_ref": candidate.subject_ref.model_copy(update={"owner": "deployment"}),
                    "window_start": first.window_start,
                    "window_end": first.window_end,
                    "need": candidate.need.model_copy(
                        update={"allowed_strategies": (AllocationStrategy.WEIGHTED_RENDEZVOUS_V1,)}
                    ),
                    "demand": candidate.demand.model_copy(
                        update={"allowed_strategy": AllocationStrategy.WEIGHTED_RENDEZVOUS_V1}
                    ),
                }
            )
        )
    binding = _binding_dto(facets=(SharingFacet.ROUTING, SharingFacet.CAPACITY, SharingFacet.SPEND))
    pool = {**_pool_dto(alias_affinities=(("coding-main", affinity),)), "capacity_account_ref": "capacity-a"}
    _publish(_services(), catalog, binding, pool, members=tuple(item.subject_ref.reference for item in requests))
    observations = (
        observations[0].model_copy(
            update={
                "catalog_digest": catalog.digest,
                "healthy_shard_ids": ("vertex-primary", "vertex-secondary"),
            }
        ),
    )
    return catalog, requests, observations


def test_per_user_affinity_does_not_coalesce_distinct_owners(django_user_model):
    catalog, requests, observations = shared_inputs(django_user_model, affinity="per_user")
    for request in requests:
        allocate((catalog, request, observations))
    assignments = ModelAliasAssignment.objects.select_related("group")
    assert {item.group.owner_ref for item in assignments} == {
        f"management:{request.owner_ref.reference}" for request in requests
    }
    assert assignments.count() == 2


def test_later_alias_denial_rolls_back_first_shared_assignment(django_user_model):
    from engine.models import ModelCapacityReservation

    catalog, request, observations = allocation_inputs(django_user_model)
    payload = catalog.model_dump(mode="json")
    alias = deepcopy(payload["aliases"][0])
    alias["logical_alias"] = "z-second"
    payload["aliases"].append(alias)
    catalog = seal_catalog(payload)
    request = request.model_copy(update={"subject_ref": request.subject_ref.model_copy(update={"owner": "deployment"})})
    _publish(
        _services(),
        catalog,
        _binding_dto(facets=(SharingFacet.ROUTING,)),
        _pool_dto(alias_affinities=(("coding-main", "per_pool"), ("z-second", "per_pool"))),
        members=(request.subject_ref.reference,),
    )
    observations = (observations[0].model_copy(update={"catalog_digest": catalog.digest, "limit": 6000}),)
    with pytest.raises(ContractError, match=r"allocation\.capacity_unavailable"):
        allocate((catalog, request, observations))
    assert not ModelAliasAssignment.objects.exists()
    assert not ModelAllocation.objects.exists()
    assert not ModelCapacityReservation.objects.exists()


def test_members_reuse_one_assignment_and_one_parent_commitment(django_user_model):
    catalog, requests, observations = shared_inputs(django_user_model)
    first = allocate((catalog, requests[0], observations))
    second = allocate((catalog, requests[1], observations))
    assert ModelAliasAssignment.objects.count() == 1
    assert first.alias_shards == second.alias_shards
    assert first.draws.get().reservation_id == second.draws.get().reservation_id
    parent = first.draws.get().reservation
    assert parent.amount == 16000
    assert parent.consumed == 8000
    assert first.snapshot["effective_policy"]["spend_account_refs"] == ["acct-shared"]


def test_incompatible_member_cannot_use_private_alternate(django_user_model):
    catalog, requests, observations = shared_inputs(django_user_model)
    first = allocate((catalog, requests[0], observations))
    other = ({"vertex-primary", "vertex-secondary"} - set(first.alias_shards.values())).pop()
    observations = (observations[0].model_copy(update={"healthy_shard_ids": (other,)}),)
    with pytest.raises(ContractError, match=r"allocation\.shared_assignment_incompatible"):
        allocate((catalog, requests[1], observations))
    assert ModelAllocation.objects.count() == 1


def test_missing_membership_is_not_proven_nonmembership(django_user_model):
    catalog, requests, observations = shared_inputs(django_user_model)
    MembershipProjection.objects.all().delete()
    with pytest.raises(ContractError, match=r"allocation\.authority"):
        allocate((catalog, requests[0], observations))
    assert not ModelAllocation.objects.exists()


def test_excluded_subject_does_not_receive_shared_pool_facets(django_user_model):
    catalog, request, observations = allocation_inputs(django_user_model)
    request = request.model_copy(update={"subject_ref": request.subject_ref.model_copy(update={"owner": "deployment"})})
    _publish(
        _services(),
        catalog,
        _binding_dto(facets=(SharingFacet.ROUTING, SharingFacet.CAPACITY, SharingFacet.SPEND)),
        {**_pool_dto(alias_affinities=(("coding-main", "per_pool"),)), "capacity_account_ref": "capacity-a"},
        members=("range:some-other-subject",),
    )

    allocation = allocate((catalog, request, observations))

    effective = allocation.snapshot["effective_policy"]
    assert effective["spend_account_refs"] == []
    assert effective["capacity_account_refs"] == []
    assert effective["alias_routings"] == []
    assert not ModelAliasAssignment.objects.exists()


def test_failed_security_audit_rolls_back_all_model_effects(django_user_model, monkeypatch):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    inputs = allocation_inputs(django_user_model)
    monkeypatch.setattr("shared.audit.audit_log", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        allocate(inputs)
    assert not ModelAllocation.objects.exists()


def test_membership_revision_change_revokes_dependent_grant(django_user_model):
    from .test_sharing import _membership

    catalog, requests, observations = shared_inputs(django_user_model)
    allocation = allocate((catalog, requests[0], observations))
    projection = MembershipProjection.objects.get()
    _membership(_services(), projection.sharing_binding_id, members=(), revision=2, authority_revision=1)
    allocation.grant.refresh_from_db()
    assert allocation.grant.state == "revoked"
    assert allocation.grant.grant_epoch == 2
