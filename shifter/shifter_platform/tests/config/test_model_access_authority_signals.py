"""Defense-in-depth fences for direct identity admin and reverse M2M paths."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from engine.models import SharingAuthorityFence
from engine.services import publish_authority_fence

pytestmark = pytest.mark.django_db

_DEPLOYMENT = "11111111-1111-4111-8111-111111111111"
User = get_user_model()


def _fence(owner, reference, revision=1):
    return publish_authority_fence(
        deployment_id=_DEPLOYMENT,
        authority_ref={"owner": owner, "reference": reference},
        authority_revision=revision,
        state="allowed",
    )


def test_reverse_group_clear_and_group_delete_invalidate_shared_group_revision():
    user = User.objects.create_user("member@test")
    group = Group.objects.create(name="mutable")
    group.user_set.add(user)
    _fence("management", f"auth-group:{group.pk}")

    group.user_set.clear()
    fence = SharingAuthorityFence.objects.get(
        deployment_id=_DEPLOYMENT,
        authority_owner="management",
        authority_reference=f"auth-group:{group.pk}",
    )
    assert (fence.authority_revision, fence.state) == (2, "unknown")

    publish_authority_fence(
        deployment_id=_DEPLOYMENT,
        authority_ref={"owner": "management", "reference": f"auth-group:{group.pk}"},
        authority_revision=3,
        state="allowed",
    )
    group.delete()
    fence.refresh_from_db()
    assert (fence.authority_revision, fence.state) == (4, "unknown")


def test_direct_user_disable_invalidates_user_and_operator_authority():
    user = User.objects.create_user("subject@test")
    _fence("management", f"user:{user.pk}")
    _fence("management", f"operator:{user.pk}")

    user.is_active = False
    user.save(update_fields=["is_active"])

    states = {
        row.authority_reference: (row.authority_revision, row.state)
        for row in SharingAuthorityFence.objects.filter(
            deployment_id=_DEPLOYMENT,
            authority_owner="management",
        )
    }
    assert states[f"user:{user.pk}"] == (2, "revoked")
    assert states[f"operator:{user.pk}"] == (2, "revoked")
