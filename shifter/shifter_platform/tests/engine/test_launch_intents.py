"""Security and validation tests for durable provisioner launch intents."""

from __future__ import annotations

from uuid import UUID

import pytest

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db(databases=["default"])


def _authorized_range(request_id: str) -> None:
    from django.contrib.auth import get_user_model

    from engine.models import Range, Request

    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="range", user=user)
    Range.objects.create(workspace_id=_WORKSPACE_ID, request=request, user=user, status=Range.Status.PROVISIONING)


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


@pytest.mark.parametrize("provider", ["aws", "gcp"])
def test_public_dispatch_enqueues_the_same_intent_on_both_providers(settings, provider: str) -> None:
    """AWS and GCP share the single launch-intent contract (ADR-043-R2, #1833):
    the public dispatch entrypoint persists exactly one ``ProvisionerLaunchIntent``
    and returns its reserved ref without ever launching the provider TaskRunner,
    regardless of which provider is configured."""
    from engine.ecs import start_range_provisioning
    from engine.models import ProvisionerLaunchIntent

    settings.CLOUD_PROVIDER = provider
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = "shifter-jobs"
    settings.ENGINE_TASK_DEFINITION = "registry.example/provisioner:sha"
    if provider == "aws":
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
    request_id = UUID("99999999-9999-9999-9999-999999999999")
    _authorized_range(str(request_id))

    ref = start_range_provisioning(request_id)

    intent = ProvisionerLaunchIntent.objects.get()
    assert ref == intent.task_ref
    assert intent.payload["resource"] == "range"
    assert intent.payload["operation"] == "provision"
    assert intent.payload["request_id"] == str(request_id)


@pytest.mark.parametrize("provider", ["aws", "gcp"])
def test_public_dispatch_fails_closed_when_domain_state_forbids_operation(settings, provider: str) -> None:
    """Fail-closed authorization (ADR-043-R2): the dispatch entrypoint enqueues
    nothing and raises when current domain state does not authorize the operation.
    The happy-path dispatch tests all build the row in an authorizing status, so
    this exercises the ``authorize_provisioner_payload`` rejection branch they
    never hit — deleting that check would now fail a test, on both providers."""
    from engine.ecs import start_range_provisioning
    from engine.models import ProvisionerLaunchIntent, Range

    settings.CLOUD_PROVIDER = provider
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = "shifter-jobs"
    settings.ENGINE_TASK_DEFINITION = "registry.example/provisioner:sha"
    if provider == "aws":
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
    request_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    request_uuid = UUID(request_id)
    _authorized_range(request_id)
    # READY is not a provision-authorizing status; the operation must fail closed.
    Range.objects.filter(request__request_id=request_id).update(status=Range.Status.READY)

    with pytest.raises(ValueError):
        start_range_provisioning(request_uuid)
    assert not ProvisionerLaunchIntent.objects.exists()


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


def test_enqueue_materializes_immutable_operation_input() -> None:
    """The immutable operation-input projection is created with the intent,
    keyed by the same operation_id, and carries a valid transport envelope."""
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import OperationInput, ProvisionerLaunchIntent, Range
    from shared.operation_envelope import validate_operation_envelope

    request_id = "12121212-1212-1212-1212-121212121212"
    _authorized_range(request_id)
    ref = enqueue_provisioner_launch(["range", "provision", "--request-id", request_id])

    intent = ProvisionerLaunchIntent.objects.get(intent_id=UUID(ref))
    range_row = Range.objects.get(request__request_id=request_id)
    op_input = OperationInput.objects.get()
    assert op_input.operation_id == intent.operation_id == range_row.provisioner_operation_id
    assert str(op_input.request_id) == request_id
    assert op_input.resource == "range"
    assert op_input.operation == "provision"
    # Envelope validates and the input payload is a reference-only projection.
    envelope = validate_operation_envelope(op_input.envelope)
    assert envelope["operation_id"] == str(intent.operation_id)
    assert "range_spec" in envelope["payload"]


def test_operation_input_is_not_duplicated_on_idempotent_replay() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import OperationInput

    request_id = "13131313-1313-1313-1313-131313131313"
    _authorized_range(request_id)
    command = ["range", "provision", "--request-id", request_id]
    enqueue_provisioner_launch(command)
    enqueue_provisioner_launch(command)  # replay: same operation generation

    assert OperationInput.objects.count() == 1


def test_new_operation_generation_materializes_a_new_input() -> None:
    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import OperationInput, Range

    request_id = "14141414-1414-1414-1414-141414141414"
    _authorized_range(request_id)
    enqueue_provisioner_launch(["range", "provision", "--request-id", request_id])
    range_row = Range.objects.get(request__request_id=request_id)
    range_row.status = Range.Status.DESTROYING
    range_row.save(update_fields=["status", "updated_at"])
    enqueue_provisioner_launch(["range", "destroy", "--request-id", request_id])

    # One immutable input per operation generation; the first is not mutated.
    assert OperationInput.objects.count() == 2
    assert set(OperationInput.objects.values_list("operation", flat=True)) == {"provision", "destroy"}


def test_command_from_payload_round_trips_the_operation_id() -> None:
    from engine.launch_intents import command_from_payload, validate_provisioner_command

    operation_id = "15151515-1515-1515-1515-151515151515"
    request_id = "16161616-1616-1616-1616-161616161616"
    payload = {
        "version": 1,
        "resource": "range",
        "operation": "provision",
        "request_id": request_id,
        "operation_id": operation_id,
    }
    command = command_from_payload(payload)
    assert command == ["range", "provision", "--request-id", request_id, "--operation-id", operation_id]
    assert validate_provisioner_command(command) == payload


def test_validate_rejects_non_uuid_operation_id() -> None:
    from engine.launch_intents import validate_provisioner_command

    request_id = "17171717-1717-1717-1717-171717171717"
    with pytest.raises(ValueError, match="operation_id must be a UUID"):
        validate_provisioner_command(["range", "provision", "--request-id", request_id, "--operation-id", "nope"])


def test_stored_intent_check_is_a_noop_when_no_input_was_materialized() -> None:
    """A generation with no stored ``OperationInput`` (a legacy range) has nothing
    to compare, so the replay-equivalence guard returns without raising."""
    from uuid import uuid4

    from engine.launch_intents import _assert_stored_intent_matches

    payload = {
        "version": 1,
        "resource": "range",
        "operation": "provision",
        "request_id": "31313131-3131-3131-3131-313131313131",
    }
    # No OperationInput exists for this operation generation.
    _assert_stored_intent_matches(payload, uuid4())


def test_stored_intent_check_is_a_noop_for_a_legacy_range_without_a_request() -> None:
    """A legacy range carries no linked ``Request``, so there is no current intent
    to compose and compare; the guard returns before the digest check."""
    from uuid import uuid4

    from django.contrib.auth import get_user_model

    from engine.launch_intents import _assert_stored_intent_matches
    from engine.models import OperationInput, Range

    operation_id = uuid4()
    user = get_user_model().objects.create_user(username=f"{uuid4()}@example.com")
    legacy_range = Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=None,
        user=user,
        status=Range.Status.PROVISIONING,
    )
    OperationInput.objects.create(
        operation_id=operation_id,
        request_id=uuid4(),
        resource="range",
        operation="provision",
        contract_version="1",
        envelope={},
    )
    payload = {
        "version": 1,
        "resource": "range",
        "operation": "provision",
        "range_id": legacy_range.pk,
        "user_id": legacy_range.user_id,
    }

    _assert_stored_intent_matches(payload, operation_id)
