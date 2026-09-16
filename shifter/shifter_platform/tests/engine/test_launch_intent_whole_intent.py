"""Internal re-enqueue must compare the complete immutable intent (#2086, ADR-063-R2).

The stored ``OperationInput`` is immutable per operation generation. Re-enqueuing
the same generation with a *different* composed intent (a changed compiled plan or
binding) must fail closed rather than silently reuse the stale input; an unchanged
re-enqueue still reuses idempotently.
"""

from __future__ import annotations

import pytest

_WORKSPACE_ID = 1
pytestmark = pytest.mark.django_db(databases=["default"])


def _provisioning_range(request_id: str, range_config: dict) -> None:
    from django.contrib.auth import get_user_model

    from engine.models import Range, Request

    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="range", user=user)
    Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        status=Range.Status.PROVISIONING,
        range_config=range_config,
    )


def test_reenqueue_with_changed_intent_conflicts() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import Range

    request_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    _provisioning_range(request_id, {"nodes": [{"name": "a"}]})
    command = ["range", "provision", "--request-id", request_id]
    enqueue_provisioner_launch(command)

    # Mutate the compiled intent for the SAME operation generation.
    Range.objects.filter(request__request_id=request_id).update(range_config={"nodes": [{"name": "b"}]})

    with pytest.raises(ValueError, match="does not match the stored"):
        enqueue_provisioner_launch(command)


def test_reenqueue_with_unchanged_intent_reuses() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent

    request_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    _provisioning_range(request_id, {"nodes": [{"name": "a"}]})
    command = ["range", "provision", "--request-id", request_id]

    first = enqueue_provisioner_launch(command)
    second = enqueue_provisioner_launch(command)

    assert second == first
    assert ProvisionerLaunchIntent.objects.count() == 1
