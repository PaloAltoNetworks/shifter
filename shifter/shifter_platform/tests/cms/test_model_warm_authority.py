"""Warm preparation authority follows the real inactive-owner ledger lifecycle."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from cms.services._model_allocation import prepare_model_access_for_dispatch
from cms.services._warm_pool_reconcile import create_managed_warm_user
from engine.models import ModelAllocation, ModelLaunchPreparationRecord, Range, WarmRangeGeneration
from engine.services import record_model_observations
from engine.services._model_allocation_launch import allocate_launch_models
from shared.model_access import ContractError

from ..engine.services.test_model_allocation import allocation_inputs
from .test_model_allocation_dispatch import setup_launch

pytestmark = pytest.mark.django_db(transaction=True)


def warm_launch(django_user_model, settings):
    owner, request, instance = setup_launch(django_user_model, settings, owner=create_managed_warm_user())
    instance.expires_at = instance.maximum_expires_at = None
    instance.save(update_fields=["expires_at", "maximum_expires_at"])
    generation = WarmRangeGeneration.objects.create(
        request_id=request.request_id,
        range=Range.objects.get(uuid=request.range_id),
        bucket_id="model-warm",
        compatibility_digest="sha256:" + "a" * 64,
        effective_policy_fingerprint="sha256:" + "b" * 64,
        backend="gce",
        range_source="mission_control",
        capacity_partition="default",
        capacity_scope_ref=uuid4(),
        capacity_draw_key=uuid4(),
        idle_deadline=request.window_end,
    )
    _, _, observations = allocation_inputs(django_user_model)
    record_model_observations(settings.MODEL_ACCESS_CATALOG, lambda _: observations)
    return owner, request, generation


def allocate_preparation(request, operation="provision"):
    with transaction.atomic():
        return allocate_launch_models(
            {"resource": "raes-range", "operation": operation, "request_id": str(request.request_id)},
            request.operation_id,
        )


@pytest.mark.parametrize(
    ("invalid", "error_code"),
    [
        ("active", r"allocation\.authority_unavailable"),
        ("password", r"allocation\.authority_unavailable"),
        ("unmanaged", r"allocation\.authority_unavailable"),
        ("deleted", r"allocation\.authority_unavailable"),
        ("expired", r"allocation\.scope_unavailable"),
        ("retired", r"allocation\.scope_unavailable"),
        ("absent", r"allocation\.scope_unavailable"),
    ],
)
def test_warm_preparation_requires_real_system_identity_and_live_ledger(
    django_user_model, settings, invalid, error_code
):
    owner, request, generation = warm_launch(django_user_model, settings)
    if invalid == "active":
        owner.is_active = True
        owner.save(update_fields=["is_active"])
    elif invalid == "password":
        owner.set_password("not-a-system-owner")
        owner.save(update_fields=["password"])
    elif invalid == "unmanaged":
        owner.email = "ordinary@example.invalid"
        owner.save(update_fields=["email"])
    elif invalid == "deleted":
        owner.profile.deleted_at = timezone.now()
        owner.profile.save(update_fields=["deleted_at"])
    elif invalid == "expired":
        generation.idle_deadline = timezone.now() - timedelta(seconds=1)
        generation.save(update_fields=["idle_deadline"])
    elif invalid == "retired":
        generation.state = "retiring"
        generation.save(update_fields=["state"])
    else:
        generation.delete()
    with pytest.raises(ContractError, match=error_code):
        prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    assert not ModelLaunchPreparationRecord.objects.exists()
    assert not ModelAllocation.objects.exists()


@pytest.mark.parametrize("allocated", [False, True])
@pytest.mark.parametrize("mutation", ["claim", "retire", "deadline", "scope", "draw"])
def test_warm_ledger_mutation_invalidates_preparation(django_user_model, settings, allocated, mutation):
    _, request, generation = warm_launch(django_user_model, settings)
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    allocation = allocate_preparation(request)[0] if allocated else None
    with transaction.atomic():
        if mutation == "claim":
            generation.state = "ready"
            generation.save(update_fields=["state"])
            from engine.services import claim_ready_generation

            assert (
                claim_ready_generation(
                    candidates=[(generation.bucket_id, generation.compatibility_digest)],
                    backend=generation.backend,
                    range_source=generation.range_source,
                    claimant_request_id=uuid4(),
                )
                is not None
            )
        elif mutation == "retire":
            generation.state = "retiring"
            generation.save(update_fields=["state"])
        elif mutation == "deadline":
            generation.idle_deadline -= timedelta(minutes=1)
            generation.save(update_fields=["idle_deadline"])
        else:
            field = "capacity_scope_ref" if mutation == "scope" else "capacity_draw_key"
            setattr(generation, field, uuid4())
            generation.save(update_fields=[field])
        if allocation is not None:
            allocation.grant.refresh_from_db()
            assert allocation.grant.state == "revoked"
        else:
            with pytest.raises(ContractError, match=r"allocation\.authority_unavailable"):
                allocate_preparation(request)
            assert not ModelAllocation.objects.exists()


def test_preparation_authority_cannot_activate_a_claimant(django_user_model, settings):
    _, request, _ = warm_launch(django_user_model, settings)
    prepare_model_access_for_dispatch(request.request_id, range_id=request.range_id)
    with pytest.raises(ContractError, match=r"allocation\.system_preparation_only"):
        allocate_preparation(request, "activate")
    assert not ModelAllocation.objects.exists()
