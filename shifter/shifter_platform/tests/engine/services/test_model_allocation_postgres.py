"""Real PostgreSQL serialization and rollback proofs for M03."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from django.db import connection, transaction

from engine.models import ModelAllocation, ModelCapacityReservation
from shared.model_access import ContractError

from .test_model_allocation import allocate, allocation_inputs
from .test_model_allocation_sharing import shared_inputs

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _race(inputs):
    barrier = Barrier(len(inputs))

    def run(item):
        try:
            barrier.wait(timeout=10)
            return allocate(item)
        except ContractError as exc:
            return exc.code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(inputs)) as executor:
        return list(executor.map(run, inputs))


def test_overlapping_independent_reservations_cannot_both_spend_headroom(django_user_model):
    catalog, first, observations = allocation_inputs(django_user_model)
    _, second, _ = allocation_inputs(django_user_model)
    observations = (observations[0].model_copy(update={"limit": 6000}),)
    results = _race([(catalog, first, observations), (catalog, second, observations)])
    assert sum(isinstance(item, ModelAllocation) for item in results) == 1
    assert results.count("allocation.capacity_unavailable") == 1
    assert ModelCapacityReservation.objects.get().amount == 4000


def test_shared_first_use_commits_one_assignment_and_parent(django_user_model):
    from engine.models import ModelAliasAssignment

    catalog, requests, observations = shared_inputs(django_user_model)
    results = _race([(catalog, request, observations) for request in requests])
    assert all(isinstance(item, ModelAllocation) for item in results), results
    assert results[0].alias_shards == results[1].alias_shards
    assert ModelAliasAssignment.objects.count() == 1
    assert ModelCapacityReservation.objects.get().consumed == 8000


def test_weighted_cohort_first_use_reserves_both_accounts_once(django_user_model):
    from .test_model_weighted_capacity import cohort_inputs

    catalog, requests, observations = cohort_inputs(django_user_model)
    results = _race([(catalog, request, observations) for request in requests[:4]])
    assert all(isinstance(item, ModelAllocation) for item in results), results
    assert sorted(ModelCapacityReservation.objects.values_list("amount", "consumed")) == [(8000, 8000), (8000, 8000)]


def test_competing_weighted_cohorts_cannot_reserve_the_same_account_shares(django_user_model):
    from uuid import uuid4

    from .test_model_weighted_capacity import cohort_inputs

    catalog, requests, observations = cohort_inputs(django_user_model)
    other_event = requests[1].model_copy(update={"scope_id": uuid4()})
    results = _race([(catalog, request, observations) for request in (requests[0], other_event)])
    assert sum(isinstance(item, ModelAllocation) for item in results) == 1
    assert results.count("allocation.capacity_unavailable") == 1
    assert sorted(ModelCapacityReservation.objects.values_list("amount", flat=True)) == [8000, 8000]


def test_adjacent_windows_do_not_double_count_headroom(django_user_model):
    catalog, first, observations = allocation_inputs(django_user_model)
    _, second, _ = allocation_inputs(django_user_model)
    second = second.model_copy(
        update={
            "window_start": first.window_end,
            "window_end": first.window_end + (first.window_end - first.window_start),
        }
    )
    observations = (observations[0].model_copy(update={"limit": 6000}),)
    results = _race([(catalog, first, observations), (catalog, second, observations)])
    assert all(isinstance(item, ModelAllocation) for item in results), results
    assert ModelCapacityReservation.objects.count() == 2


def test_catalog_rename_does_not_create_more_physical_quota(django_user_model):
    from shared.model_access import seal_catalog

    catalog, first, observations = allocation_inputs(django_user_model)
    _, second, _ = allocation_inputs(django_user_model)
    payload = catalog.model_dump(mode="json")
    payload["quota_pools"][0]["quota_pool_id"] = "renamed-quota"
    payload["shards"][0]["quota_pool_ids"] = ["renamed-quota"]
    renamed = seal_catalog(payload)
    original_reading = observations[0].model_copy(update={"limit": 6000})
    renamed_reading = original_reading.model_copy(
        update={"catalog_digest": renamed.digest, "quota_pool_id": "renamed-quota"}
    )
    results = _race([(catalog, first, (original_reading,)), (renamed, second, (renamed_reading,))])
    assert sum(isinstance(item, ModelAllocation) for item in results) == 1
    assert ModelCapacityReservation.objects.count() == 1


def test_concurrent_duplicate_launch_has_one_effect_vector(django_user_model):
    inputs = allocation_inputs(django_user_model)
    results = _race([inputs, inputs])
    assert results[0].pk == results[1].pk
    assert ModelAllocation.objects.count() == 1
    assert ModelCapacityReservation.objects.get().consumed == 4000


def test_observation_must_still_be_fresh_after_waiting_for_quota_lock(django_user_model, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    from engine.services._model_quota import lock_quotas

    catalog, request, observations = allocation_inputs(django_user_model)
    now = timezone.now()
    observations = (observations[0].model_copy(update={"valid_until": now + timedelta(hours=1)}),)
    clock = [now]
    reached_lock, finished = Event(), Event()
    real_lock_quotas = lock_quotas

    def observed_lock(*args, **kwargs):
        reached_lock.set()
        return real_lock_quotas(*args, **kwargs)

    monkeypatch.setattr("engine.services._model_allocation.lock_quotas", observed_lock)
    monkeypatch.setattr(
        "engine.services._model_allocation.timezone",
        SimpleNamespace(now=lambda: clock[0]),
    )

    def run():
        try:
            with pytest.raises(ContractError, match=r"allocation\.capacity_unavailable"):
                allocate((catalog, request, observations))
        finally:
            connection.close()
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            lock_quotas(catalog)
            future = executor.submit(run)
            assert reached_lock.wait(5)
            clock[0] = observations[0].valid_until + timedelta(seconds=1)
            assert not finished.wait(0.1)
        future.result(timeout=15)
    assert not ModelAllocation.objects.exists()


def test_unrelated_quota_mutex_does_not_block_independent_profile(django_user_model):
    from copy import deepcopy

    from engine.services._model_quota import lock_quotas
    from shared.model_access import seal_catalog

    catalog, request, observations = allocation_inputs(django_user_model)
    payload = catalog.model_dump(mode="json")
    profile = deepcopy(payload["profiles"][0])
    profile["profile_id"] = "independent"
    payload["profiles"].append(profile)
    pool = deepcopy(payload["quota_pools"][0])
    pool.update(quota_pool_id="independent", provider_quota_identity="project:independent")
    payload["quota_pools"].append(pool)
    shard = deepcopy(payload["shards"][0])
    shard.update(shard_id="independent", quota_pool_ids=["independent"])
    payload["shards"].append(shard)
    alias = deepcopy(payload["aliases"][0])
    alias.update(logical_alias="independent", profile_id="independent", eligible_shard_ids=["independent"])
    payload["aliases"].append(alias)
    catalog = seal_catalog(payload)
    request = request.model_copy(update={"need": request.need.model_copy(update={"profile_id": "independent"})})
    observations = (
        observations[0].model_copy(
            update={
                "quota_pool_id": "independent",
                "catalog_digest": catalog.digest,
                "healthy_shard_ids": ("independent",),
            }
        ),
    )

    def run():
        try:
            return allocate((catalog, request, observations))
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as executor, transaction.atomic():
        lock_quotas(catalog, "coding")
        result = executor.submit(run).result(timeout=8)
        assert result.alias_shards == {"independent": "independent"}


def test_membership_must_still_be_fresh_after_quota_lock_wait(django_user_model, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    from engine.models import MembershipProjection
    from engine.services._model_quota import lock_quotas

    catalog, requests, observations = shared_inputs(django_user_model)
    now = timezone.now()
    deadline = now + timedelta(hours=1)
    MembershipProjection.objects.update(freshness_deadline=deadline)
    observations = tuple(
        item.model_copy(update={"valid_until": deadline + timedelta(hours=1)}) for item in observations
    )
    clock = [now]
    reached_lock, finished = Event(), Event()
    real_lock_quotas = lock_quotas

    def observed_lock(*args, **kwargs):
        reached_lock.set()
        return real_lock_quotas(*args, **kwargs)

    monkeypatch.setattr("engine.services._model_allocation.lock_quotas", observed_lock)
    frozen_timezone = SimpleNamespace(now=lambda: clock[0])
    monkeypatch.setattr("engine.services._model_allocation.timezone", frozen_timezone)
    monkeypatch.setattr("engine.services._model_allocation_authority.timezone", frozen_timezone)

    def run():
        try:
            with pytest.raises(ContractError, match=r"allocation\.authority_unavailable"):
                allocate((catalog, requests[0], observations))
        finally:
            connection.close()
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            lock_quotas(catalog)
            future = executor.submit(run)
            assert reached_lock.wait(5)
            clock[0] = deadline + timedelta(seconds=1)
            assert not finished.wait(0.1)
        future.result(timeout=15)
    assert not ModelAllocation.objects.exists()


def test_composed_publication_holds_policy_mutex_before_projection(django_user_model, monkeypatch):
    """Owner resolution precedes the policy lock, which precedes projection locks."""
    from cms import services as cms_services
    from config.model_access_sharing import publish_model_access_binding
    from engine.models import SharingAuthorityFence
    from engine.services._model_allocation_authority import lock_policy_publication
    from shared.model_access import SharingPool

    from .test_model_admission import _catalog
    from .test_sharing import _binding_dto, _pool_dto

    catalog = _catalog()
    actor = django_user_model.objects.create_superuser(username="publication-lock-operator")
    with transaction.atomic():
        fence = lock_policy_publication(catalog.deployment_id)
    reached, proceed = Event(), Event()
    project = cms_services.engine_project_selector_resolution

    def pause_before_projection(**kwargs):
        reached.set()
        assert proceed.wait(10)
        return project(**kwargs)

    monkeypatch.setattr(cms_services, "engine_project_selector_resolution", pause_before_projection)

    def publish():
        try:
            return publish_model_access_binding(
                actor=actor,
                deployment_id=catalog.deployment_id,
                catalog=catalog,
                binding=_binding_dto(),
                pool=SharingPool.model_validate(_pool_dto()),
                expected_definition_revision=0,
            )
        finally:
            connection.close()

    from django.db import OperationalError

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(publish)
        try:
            assert reached.wait(10)
            with pytest.raises(OperationalError), transaction.atomic():
                SharingAuthorityFence.objects.select_for_update(nowait=True).get(pk=fence.pk)
        finally:
            proceed.set()
            future.result(timeout=15)
