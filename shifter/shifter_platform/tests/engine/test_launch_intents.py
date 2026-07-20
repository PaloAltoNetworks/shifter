"""Security and validation tests for durable provisioner launch intents."""

from __future__ import annotations

from uuid import UUID

import pytest

pytestmark = pytest.mark.django_db(databases=["default"])


def _authorized_range(request_id: str) -> None:
    from django.contrib.auth import get_user_model

    from engine.models import Range, Request

    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="range", user=user)
    Range.objects.create(request=request, user=user, status=Range.Status.PROVISIONING)


def test_enqueue_stores_only_validated_non_secret_intent() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, Range

    request_id = "11111111-1111-1111-1111-111111111111"
    _authorized_range(request_id)
    intent_ref = enqueue_provisioner_launch(["range", "provision", "--request-id", request_id])

    row = ProvisionerLaunchIntent.objects.get(intent_id=UUID(intent_ref))
    range_row = Range.objects.get(request__request_id=request_id)
    assert row.operation_id == range_row.provisioner_operation_id
    assert row.payload == {
        "version": 1,
        "resource": "range",
        "operation": "provision",
        "request_id": "11111111-1111-1111-1111-111111111111",
    }
    assert "env" not in row.payload
    assert "secret" not in str(row.payload).lower()


def test_duplicate_delivery_is_idempotent() -> None:
    from django.utils import timezone

    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, Range

    request_id = "22222222-2222-2222-2222-222222222222"
    _authorized_range(request_id)
    command = ["range", "provision", "--request-id", request_id]
    first = enqueue_provisioner_launch(command)
    Range.objects.filter(request__request_id=request_id).update(updated_at=timezone.now())
    second = enqueue_provisioner_launch(command)

    assert second == first
    assert ProvisionerLaunchIntent.objects.count() == 1


def test_same_operation_generation_reuses_intent_across_command_aliases() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, Range

    request_id = "77777777-7777-7777-7777-777777777777"
    _authorized_range(request_id)
    range_row = Range.objects.get(request__request_id=request_id)

    request_ref = enqueue_provisioner_launch(["range", "provision", "--request-id", request_id])
    legacy_ref = enqueue_provisioner_launch(
        ["range", "provision", "--range-id", str(range_row.pk), "--user-id", str(range_row.user_id)]
    )

    assert legacy_ref == request_ref
    assert ProvisionerLaunchIntent.objects.count() == 1


def test_new_domain_operation_gets_a_new_stable_identity() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, Range

    request_id = "55555555-5555-5555-5555-555555555555"
    _authorized_range(request_id)
    provision_ref = enqueue_provisioner_launch(["range", "provision", "--request-id", request_id])
    range_row = Range.objects.get(request__request_id=request_id)
    provision_operation_id = range_row.provisioner_operation_id
    range_row.status = Range.Status.DESTROYING
    range_row.save(update_fields=["status", "updated_at"])

    destroy_ref = enqueue_provisioner_launch(["range", "destroy", "--request-id", request_id])
    range_row.refresh_from_db()

    assert destroy_ref != provision_ref
    assert range_row.provisioner_operation_id != provision_operation_id
    assert ProvisionerLaunchIntent.objects.count() == 2


def test_intent_insert_failure_rolls_back_operation_generation() -> None:
    from django.db import IntegrityError, connection

    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, Range

    if connection.vendor != "sqlite":
        pytest.skip("failure-injection trigger is SQLite-specific")
    request_id = "66666666-6666-6666-6666-666666666666"
    _authorized_range(request_id)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TRIGGER fail_provisioner_intent_insert "
                "BEFORE INSERT ON engine_provisioner_launch_intent "
                "BEGIN SELECT RAISE(ABORT, 'injected insert failure'); END"
            )
        with pytest.raises(IntegrityError):
            enqueue_provisioner_launch(["range", "provision", "--request-id", request_id])
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER IF EXISTS fail_provisioner_intent_insert")

    range_row = Range.objects.get(request__request_id=request_id)
    assert range_row.provisioner_operation == ""
    assert range_row.provisioner_operation_id is None
    assert ProvisionerLaunchIntent.objects.count() == 0


@pytest.mark.parametrize(
    "command",
    [
        ["shell", "provision", "--request-id", "11111111-1111-1111-1111-111111111111"],
        ["range", "exec", "--request-id", "11111111-1111-1111-1111-111111111111"],
        ["range", "provision", "--request-id", "not-a-uuid"],
        ["range", "provision", "--request-id", "11111111-1111-1111-1111-111111111111", "--extra"],
    ],
)
def test_rejects_non_canonical_launch_commands(command: list[str]) -> None:
    from engine.launch_intents import enqueue_provisioner_launch

    with pytest.raises(ValueError):
        enqueue_provisioner_launch(command)


def test_legacy_range_intent_validates_integer_identifiers() -> None:
    from engine.launch_intents import enqueue_provisioner_launch

    with pytest.raises(ValueError):
        enqueue_provisioner_launch(["range", "provision", "--range-id", "-1", "--user-id", "7"])


def test_gcp_public_dispatch_enqueues_without_launching(settings) -> None:
    from engine.ecs import start_range_provisioning
    from engine.models import ProvisionerLaunchIntent

    settings.CLOUD_PROVIDER = "gcp"
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = "shifter-jobs"
    settings.ENGINE_TASK_DEFINITION = "registry.example/provisioner:sha"
    request_id = UUID("33333333-3333-3333-3333-333333333333")
    _authorized_range(str(request_id))

    ref = start_range_provisioning(request_id)

    row = ProvisionerLaunchIntent.objects.get(task_ref=ref)
    assert row.payload["request_id"] == str(request_id)
    assert ref.startswith(f"{settings.ENGINE_TASK_CLUSTER}/pulumi-provisioner-")


def test_gcp_public_dispatch_does_not_enqueue_with_incomplete_task_config(settings) -> None:
    from engine.ecs import start_range_provisioning
    from engine.models import ProvisionerLaunchIntent

    settings.CLOUD_PROVIDER = "gcp"
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = ""
    settings.ENGINE_TASK_DEFINITION = ""
    settings.ENGINE_ECS_CLUSTER_ARN = ""
    settings.ENGINE_TASK_DEFINITION_ARN = ""
    request_id = UUID("66666666-6666-6666-6666-666666666666")
    _authorized_range(str(request_id))

    assert start_range_provisioning(request_id) is None
    assert not ProvisionerLaunchIntent.objects.exists()


def test_succeeded_operation_cannot_be_reenqueued() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, ProvisionerLaunchStatus

    command = ["range", "provision", "--request-id", "44444444-4444-4444-4444-444444444444"]
    _authorized_range("44444444-4444-4444-4444-444444444444")
    first = enqueue_provisioner_launch(command)
    ProvisionerLaunchIntent.objects.filter(intent_id=first).update(status=ProvisionerLaunchStatus.SUCCEEDED)

    assert enqueue_provisioner_launch(command) == first
    assert ProvisionerLaunchIntent.objects.count() == 1


def test_dead_lettered_same_operation_starts_a_new_generation() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, ProvisionerLaunchStatus, Range

    request_id = "77777777-7777-7777-7777-777777777777"
    _authorized_range(request_id)
    command = ["range", "provision", "--request-id", request_id]
    first = enqueue_provisioner_launch(command)
    first_row = ProvisionerLaunchIntent.objects.get(intent_id=first)
    first_operation_id = first_row.operation_id
    first_row.status = ProvisionerLaunchStatus.DLQ
    first_row.save(update_fields=["status"])

    second = enqueue_provisioner_launch(command)

    assert second != first
    assert ProvisionerLaunchIntent.objects.count() == 2
    range_row = Range.objects.get(request__request_id=request_id)
    assert range_row.provisioner_operation_id != first_operation_id


def test_failed_episode_can_retry_the_same_operation() -> None:
    from engine.launch_intents import clear_provisioner_operation_after_failure, enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, ProvisionerLaunchStatus, Range

    request_id = "88888888-8888-8888-8888-888888888888"
    _authorized_range(request_id)
    command = ["range", "provision", "--request-id", request_id]
    first = enqueue_provisioner_launch(command)
    ProvisionerLaunchIntent.objects.filter(intent_id=first).update(status=ProvisionerLaunchStatus.SUCCEEDED)
    range_row = Range.objects.get(request__request_id=request_id)
    range_row.status = Range.Status.FAILED
    failed_fields = clear_provisioner_operation_after_failure(range_row)
    range_row.save(update_fields=["status", "updated_at", *failed_fields])
    range_row.status = Range.Status.PROVISIONING
    range_row.save(update_fields=["status", "updated_at"])

    second = enqueue_provisioner_launch(command)

    assert second != first
    assert ProvisionerLaunchIntent.objects.count() == 2
