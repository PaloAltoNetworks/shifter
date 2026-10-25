"""Real PostgreSQL proofs for PLAT-202 sharing authority serialization."""

from __future__ import annotations

import threading
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection, transaction
from django.utils import timezone

from engine.models import MembershipProjection, Range, Request, SharingAuthorityFence
from engine.services import (
    project_selector_resolution,
    publish_authority_fence,
    reassign_range_owner_by_request,
)
from shared.enums import RequestType
from shared.model_access import SelectorKind, SelectorResolution, SharingSelector, compute_digest, seal_sharing_binding

from .test_sharing import _PUBLISHER, _binding_dto, _catalog, _pool_dto, _services

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
User = get_user_model()


def _fence(deployment_id, owner, reference):
    return publish_authority_fence(
        deployment_id=deployment_id,
        authority_ref={"owner": owner, "reference": reference},
        authority_revision=1,
        state="allowed",
    )


def _lock_order_resolution():
    selector = SharingSelector(kind=SelectorKind.ALL_RANGES)
    digest = compute_digest(selector)
    member = {"owner": "deployment", "reference": "range:lock-order"}
    return SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=digest,
        assessment_count=1,
        member_refs=(member,),
        selector_authority_refs=({"owner": "engine", "reference": "all-ranges"},),
        subject_authorities=(
            {
                "subject_ref": member,
                "authority_ref": {"owner": "cms", "reference": "range:lock-order"},
            },
        ),
        publisher_requirements=(
            {
                "selector_digest": digest,
                "authority_ref": {"owner": "management", "reference": "operator:platform"},
                "scope": "deployment",
            },
        ),
    )


@pytest.mark.parametrize("operation", ("publish", "drain"))
def test_projection_refresh_uses_the_publication_and_drain_lock_order(operation):
    """Refresh waits on projection before fences, avoiding the inverse deadlock."""
    deployment_id = uuid4()
    binding_id = f"lock-order-{operation}"
    pool_id = f"pool-{operation}"
    resolution = _lock_order_resolution()
    svc = _services()
    projection = project_selector_resolution(
        deployment_id=deployment_id,
        sharing_binding_id=binding_id,
        publisher_identity=_PUBLISHER,
        resolution=resolution,
        observed_at=timezone.now(),
        freshness_deadline=timezone.now() + timedelta(minutes=5),
    )
    binding = _binding_dto(
        binding_id=binding_id,
        pool_id=pool_id,
        deployment_id=deployment_id,
    )
    pool = _pool_dto(pool_id=pool_id)
    catalog = _catalog(deployment_id)
    if operation == "drain":
        svc["publish"](
            deployment_id=deployment_id,
            catalog=catalog,
            binding=binding,
            pool=pool,
            publisher_identity=_PUBLISHER,
            expected_definition_revision=0,
        )

    started = threading.Event()
    finished = threading.Event()
    result = {}

    def refresh_projection():
        started.set()
        try:
            result["projection"] = project_selector_resolution(
                deployment_id=deployment_id,
                sharing_binding_id=binding_id,
                publisher_identity=_PUBLISHER,
                resolution=resolution,
                observed_at=timezone.now(),
                freshness_deadline=timezone.now() + timedelta(minutes=5),
            )
        except Exception as exc:
            result["error"] = exc
        finally:
            finished.set()
            connection.close()

    worker = threading.Thread(target=refresh_projection, daemon=True)
    with transaction.atomic():
        MembershipProjection.objects.select_for_update().get(pk=projection.pk)
        worker.start()
        assert started.wait(timeout=10)
        assert not finished.wait(timeout=2), "refresh bypassed the projection lock"

        # A correct refresh holds no fence while it waits for the projection.
        tuple(
            SharingAuthorityFence.objects.select_for_update(nowait=True)
            .filter(deployment_id=deployment_id)
            .order_by("authority_owner", "authority_reference")
        )
        if operation == "publish":
            svc["publish"](
                deployment_id=deployment_id,
                catalog=catalog,
                binding=binding,
                pool=pool,
                publisher_identity=_PUBLISHER,
                expected_definition_revision=0,
            )
        else:
            svc["drain"](
                deployment_id=deployment_id,
                sharing_binding_id=binding_id,
                publisher_identity=_PUBLISHER,
                expected_definition_revision=1,
            )

    assert finished.wait(timeout=30)
    worker.join(timeout=30)
    assert "error" not in result, result.get("error")
    assert result["projection"].membership_revision == 2


def test_group_removal_serializes_on_owner_row_then_invalidates_projected_revision():
    """A resolver's Group lock and m2m removal share one PostgreSQL mutex."""
    deployment_id = uuid4()
    operator = User.objects.create_superuser("group-race-operator@example.test")
    member = User.objects.create_user("group-race-member@example.test")
    group = Group.objects.create(name="group-race")
    member.groups.add(group)
    range_obj = Range.objects.create(user=member, workspace_id=1, status=Range.Status.READY)
    selector = SharingSelector(kind=SelectorKind.AUTH_GROUP, ids=(str(group.pk),))

    from config.model_access_sharing import resolve_model_access_selector

    resolution = resolve_model_access_selector(operator, selector)
    projection = project_selector_resolution(
        deployment_id=deployment_id,
        sharing_binding_id="group-race",
        publisher_identity={"owner": "management", "reference": f"operator:{operator.pk}"},
        resolution=resolution,
        observed_at=timezone.now(),
        freshness_deadline=timezone.now() + timedelta(minutes=5),
    )
    observed = next(
        item["authority_revision"]
        for item in projection.selector_authorities
        if item["authority_ref"]
        == {
            "owner": "management",
            "reference": f"auth-group:{group.pk}",
        }
    )
    started = threading.Event()
    finished = threading.Event()
    result = {}

    def remove_member():
        started.set()
        try:
            worker_member = User.objects.get(pk=member.pk)
            worker_group = Group.objects.get(pk=group.pk)
            worker_member.groups.remove(worker_group)
        except Exception as exc:
            result["error"] = exc
        finally:
            finished.set()
            connection.close()

    worker = threading.Thread(target=remove_member, daemon=True)
    with transaction.atomic():
        Group.objects.select_for_update().get(pk=group.pk)
        worker.start()
        assert started.wait(timeout=10)
        assert not finished.wait(timeout=2), "group removal bypassed the resolver's owner lock"

    assert finished.wait(timeout=30)
    worker.join(timeout=30)
    assert "error" not in result, result.get("error")
    fence = SharingAuthorityFence.objects.get(
        deployment_id=deployment_id,
        authority_owner="management",
        authority_reference=f"auth-group:{group.pk}",
    )
    assert fence.authority_revision == observed + 1
    assert fence.state == "unknown"
    assert range_obj.pk


def test_large_group_bulk_change_is_bounded_and_invalidates_every_fence():
    deployment_id = uuid4()
    member = User.objects.create_user("bulk-group-member@example.test")
    groups = tuple(Group.objects.create(name=f"bulk-group-{index}") for index in range(70))
    for group in groups:
        _fence(deployment_id, "management", f"auth-group:{group.pk}")

    member.groups.add(*groups)

    fences = SharingAuthorityFence.objects.filter(
        deployment_id=deployment_id,
        authority_owner="management",
        authority_reference__startswith="auth-group:",
    )
    assert fences.count() == 70
    assert not fences.exclude(authority_revision=2, state="unknown").exists()


def test_range_owner_transfer_invalidates_old_new_and_range_authority():
    deployment_id = uuid4()
    previous_owner = User.objects.create_user("transfer-old@example.test")
    new_owner = User.objects.create_user("transfer-new@example.test")
    request = Request.objects.create(
        request_id=uuid4(),
        request_type=RequestType.RANGE.value,
        user=previous_owner,
    )
    range_obj = Range.objects.create(
        request=request,
        user=previous_owner,
        workspace_id=9,
        status=Range.Status.READY,
    )
    refs = (
        ("engine", f"range:{range_obj.uuid}"),
        ("management", f"user:{previous_owner.pk}"),
        ("management", f"user:{new_owner.pk}"),
    )
    for owner, reference in refs:
        _fence(deployment_id, owner, reference)

    assert reassign_range_owner_by_request(request.request_id, new_owner) is True

    for owner, reference in refs:
        fence = SharingAuthorityFence.objects.get(
            deployment_id=deployment_id,
            authority_owner=owner,
            authority_reference=reference,
        )
        assert (fence.authority_revision, fence.state) == (2, "unknown")


def test_failed_publication_rolls_back_projection_and_retry_can_reassess(monkeypatch):
    from config.model_access_sharing import publish_model_access_binding

    deployment_id = uuid4()
    selector = SharingSelector(kind=SelectorKind.USER, ids=("41",))
    digest = compute_digest(selector)
    authority_ref = {"owner": "management", "reference": "user:41"}
    resolution = SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=digest,
        assessment_count=1,
        member_refs=({"owner": "deployment", "reference": "range:retry"},),
        selector_authority_refs=(authority_ref,),
        subject_authorities=(
            {
                "subject_ref": {"owner": "deployment", "reference": "range:retry"},
                "authority_ref": authority_ref,
            },
        ),
        publisher_requirements=({"selector_digest": digest, "authority_ref": authority_ref, "scope": "selector"},),
    )
    binding = seal_sharing_binding(
        {
            "contract_version": "model-access-sharing/v1",
            "sharing_binding_id": "postgres-retry",
            "deployment_id": str(deployment_id),
            "selector": selector.model_dump(mode="json"),
            "membership_mode": "dynamic",
            "membership_revision": 1,
            "authorized_publisher_ref": {"owner": "forged", "reference": "forged:actor"},
            "sharing_pool_id": "pool-retry",
            "facets": ["spend"],
            "effective_from": "2026-09-14T00:00:00Z",
            "effective_until": "2026-09-15T00:00:00Z",
        }
    )
    monkeypatch.setattr(
        "config.model_access_sharing.resolve_model_access_selector",
        lambda actor, selector: resolution,
    )
    monkeypatch.setattr("management.services.is_platform_operator", lambda actor: False)

    def fail_publish(**kwargs):
        raise RuntimeError("refused")

    monkeypatch.setattr("cms.services.engine_publish_sharing_binding", fail_publish)
    actor = SimpleNamespace(pk=41)
    with pytest.raises(RuntimeError, match="refused"):
        publish_model_access_binding(
            actor=actor,
            deployment_id=deployment_id,
            catalog=object(),
            binding=binding,
            pool=object(),
            expected_definition_revision=0,
        )
    assert not MembershipProjection.objects.filter(deployment_id=deployment_id).exists()
    assert not SharingAuthorityFence.objects.filter(deployment_id=deployment_id).exists()

    monkeypatch.setattr(
        "cms.services.engine_publish_sharing_binding",
        lambda **kwargs: SimpleNamespace(definition_revision=1, state="active"),
    )
    revision = publish_model_access_binding(
        actor=actor,
        deployment_id=deployment_id,
        catalog=object(),
        binding=binding,
        pool=object(),
        expected_definition_revision=0,
    )
    assert revision["definition_revision"] == 1
    assert MembershipProjection.objects.filter(deployment_id=deployment_id).exists()
    assert SharingAuthorityFence.objects.filter(deployment_id=deployment_id).exists()
