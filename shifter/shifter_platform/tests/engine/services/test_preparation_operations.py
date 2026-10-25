"""Durable preparation requests are authorized, idempotent and generation fenced."""

from copy import deepcopy

import pytest
from django.contrib.auth.models import Permission, User

from engine.models import PreparationAttempt, PreparationOperation
from engine.services import cancel_artifact_preparation, request_artifact_preparation
from shared.exceptions import ValidationError
from tests.engine.services.test_preparation_adapters import administrator, grant
from tests.shared.raes.test_preparation_contract import manifest_payload, requirement_payload
from tests.shared.raes.test_preparation_inputs import bound_input_fixture

pytestmark = pytest.mark.django_db
__all__ = ["administrator", "grant"]


@pytest.fixture
def installed(administrator, grant):
    from engine.services import install_preparation_adapter

    return install_preparation_adapter(administrator, grant.pk, manifest_payload())


@pytest.fixture
def operator():
    actor = User.objects.create_user(username="preparation-operator")
    actor.user_permissions.add(Permission.objects.get(codename="prepare_artifacts"))
    return actor


def package_input():
    return {
        "scenario_id": "private-example",
        "package_digest": "sha256:" + "3" * 64,
        "lock_digest": "sha256:" + "4" * 64,
        "requirement_address": "plan/private-example/web/source-artifact",
        "requirement": requirement_payload(),
        "specification_id": "example-image",
        "input_bindings": [bound_input_fixture().model_dump(mode="json")],
    }


def test_admitted_output_is_reused_without_worker_or_foreign_operation_disclosure(operator, installed, monkeypatch):
    from tests.shared.raes.test_prepared_inventory import inventory_fixture

    requirement, owned = inventory_fixture()
    raw = dict(package_input(), requirement=requirement.model_dump(mode="json"))
    monkeypatch.setattr("engine.services._raes_image.list_backend_artifacts", lambda **_: [owned])
    result = request_artifact_preparation(operator, installed.id, raw)
    assert result.state == "available" and result.reused and result.id is None
    assert not PreparationAttempt.objects.exists() and not PreparationOperation.objects.exists()


def test_oversized_combined_input_is_rejected_before_queuing(operator, installed, grant):
    from shared.preparation_grant import PreparationGrantConfiguration

    # Every individual field fits its public bound, but the combined worker
    # message must leave room for ancestor verification evidence and receipts.
    grant.configuration["trusted_input_bindings"].update(
        {f"policy-{number}-" + "x" * 900: ["sha256:" + "8" * 64] * 64 for number in range(50)}
    )
    grant.configuration_digest = PreparationGrantConfiguration.model_validate(grant.configuration).digest
    grant.save()
    with pytest.raises(ValidationError, match="size"):
        request_artifact_preparation(operator, installed.id, package_input())
    assert not PreparationAttempt.objects.exists()


def test_multi_input_package_is_rejected_before_queuing(operator, installed):
    raw = package_input()
    second = deepcopy(raw["input_bindings"][0])
    second["lock"]["input_id"] = "second-input"
    raw["input_bindings"].append(second)

    with pytest.raises(ValidationError, match="exactly one input"):
        request_artifact_preparation(operator, installed.id, raw)

    assert not PreparationAttempt.objects.exists()


def test_preparation_is_separate_from_ranges_and_retries_converge(operator, installed):
    from shared.models import AuditLog

    first = request_artifact_preparation(operator, installed.id, package_input())
    retry = request_artifact_preparation(operator, installed.id, package_input())
    assert first.id == retry.id
    assert first.state == "queued"
    assert PreparationOperation.objects.count() == 1
    assert PreparationAttempt.objects.count() == 1
    attempt = PreparationAttempt.objects.get(operation_id=first.id)
    assert attempt.phase == "verify-inputs"
    assert attempt.input["adapter"]["worker_image"].endswith("b" * 64)
    assert attempt.input["package"]["package_digest"] == "sha256:" + "3" * 64
    event = AuditLog.objects.filter(entity_type="artifact_preparation").latest("timestamp")
    assert event.entity_ref == str(first.id)


@pytest.mark.parametrize("failure", ["missing", "identity", "untrusted"])
def test_preparation_needs_complete_bound_and_operator_admitted_inputs(operator, installed, failure):
    raw = package_input()
    if failure == "missing":
        raw["input_bindings"] = []
    elif failure == "identity":
        raw["input_bindings"][0]["lock"]["artifact"]["version"] = "changed"
    else:
        raw["input_bindings"][0]["image_id"] = "5555"
    with pytest.raises(ValidationError):
        request_artifact_preparation(operator, installed.id, raw)
    assert not PreparationAttempt.objects.exists()


def test_staff_cannot_request_without_explicit_preparation_permission(installed):
    staff = User.objects.create_user(username="staff", is_staff=True)
    with pytest.raises(ValidationError):
        request_artifact_preparation(staff, installed.id, package_input())
    assert not PreparationOperation.objects.exists()


def test_disabled_adapter_cannot_start_a_new_operation(operator, administrator, installed):
    from engine.services import set_preparation_adapter_state

    set_preparation_adapter_state(administrator, installed.id, "disabled")
    with pytest.raises(ValidationError):
        request_artifact_preparation(operator, installed.id, package_input())
    assert not PreparationAttempt.objects.exists()


def test_cancellation_fences_admission_and_preserves_cleanup(operator, installed):
    request = request_artifact_preparation(operator, installed.id, package_input())
    cancelled = cancel_artifact_preparation(operator, request.id)
    assert cancelled.state == "cancelled"
    row = PreparationOperation.objects.get(pk=request.id)
    assert row.current_attempt_id is None
    assert row.cleanup_pending
    assert PreparationAttempt.objects.filter(operation=row).count() == 1


def test_ordinary_operator_cannot_cancel_another_operators_request(operator, installed):
    request = request_artifact_preparation(operator, installed.id, package_input())
    other = User.objects.create_user(username="other-operator")
    other.user_permissions.add(Permission.objects.get(codename="prepare_artifacts"))
    with pytest.raises(ValidationError):
        cancel_artifact_preparation(other, request.id)
    assert PreparationOperation.objects.get(pk=request.id).state == "queued"


def test_request_pins_manifest_and_grant_even_after_retirement(operator, administrator, installed):
    from engine.services import set_preparation_adapter_state

    request = request_artifact_preparation(operator, installed.id, package_input())
    attempt = PreparationAttempt.objects.get(operation_id=request.id)
    immutable = attempt.input
    set_preparation_adapter_state(administrator, installed.id, "retired")
    attempt.refresh_from_db()
    assert attempt.input == immutable
    assert attempt.input["manifest_digest"] == installed.manifest_digest


def test_unpermitted_route_has_no_durable_execution(operator, installed):
    raw = package_input()
    raw["requirement"]["permitted_routes"][0]["timing"] = "realization"
    with pytest.raises(ValidationError):
        request_artifact_preparation(operator, installed.id, raw)
    assert not PreparationAttempt.objects.exists()


def test_budget_includes_cancelled_work_awaiting_cleanup(operator, installed):
    first = request_artifact_preparation(operator, installed.id, package_input())
    second_input = package_input()
    second_input["package_digest"] = "sha256:" + "5" * 64
    request_artifact_preparation(operator, installed.id, second_input)
    cancel_artifact_preparation(operator, first.id)
    third_input = package_input()
    third_input["package_digest"] = "sha256:" + "6" * 64
    with pytest.raises(ValidationError, match="capacity"):
        request_artifact_preparation(operator, installed.id, third_input)
    assert request_artifact_preparation(operator, installed.id, second_input).state == "queued"
    assert PreparationOperation.objects.count() == 2


def test_grant_replacement_does_not_reset_scope_budget(operator, administrator, installed, grant):
    from engine.models import PreparationGrant
    from engine.services import install_preparation_adapter
    from shared.preparation_grant import PreparationGrantConfiguration

    request_artifact_preparation(operator, installed.id, package_input())
    raw = dict(grant.configuration, max_concurrent_operations=1)
    configuration = PreparationGrantConfiguration.model_validate(raw)
    replacement = PreparationGrant.objects.create(
        scope_digest=configuration.scope_digest,
        configuration_digest=configuration.digest,
        configuration=raw,
        active=True,
    )
    manifest = dict(manifest_payload(), version="2")
    adapter = install_preparation_adapter(administrator, replacement.pk, manifest)
    with pytest.raises(ValidationError, match="capacity"):
        request_artifact_preparation(operator, adapter.id, package_input())


def test_mutated_adapter_record_cannot_authorize_new_work(operator, installed):
    from engine.models import PreparationAdapter

    altered = dict(installed.manifest, worker_image="registry.example/private/changed@sha256:" + "f" * 64)
    PreparationAdapter.objects.filter(pk=installed.id).update(manifest=altered)
    with pytest.raises(ValidationError):
        request_artifact_preparation(operator, installed.id, package_input())
    assert not PreparationOperation.objects.exists()


def test_explicit_retry_waits_for_cleanup_and_fences_the_previous_attempt(operator, installed):
    from engine.services._preparation_operations import retry_artifact_preparation

    requested = request_artifact_preparation(operator, installed.id, package_input())
    previous = PreparationAttempt.objects.get(operation_id=requested.id)
    cancel_artifact_preparation(operator, requested.id)
    with pytest.raises(ValidationError):
        retry_artifact_preparation(operator, requested.id)
    PreparationOperation.objects.filter(pk=requested.id).update(cleanup_pending=False)
    retried = retry_artifact_preparation(operator, requested.id)
    assert retried.id == requested.id
    assert retried.state == "queued"
    row = PreparationOperation.objects.get(pk=requested.id)
    assert row.current_attempt_id != previous.id
    assert PreparationAttempt.objects.filter(operation=row).count() == 2
    assert retry_artifact_preparation(operator, requested.id).id == requested.id
    assert PreparationAttempt.objects.filter(operation=row).count() == 2


def test_deduplication_does_not_disclose_another_operators_private_operation(operator, installed):
    first = request_artifact_preparation(operator, installed.id, package_input())
    other = User.objects.create_user(username="deduplicating-operator")
    other.user_permissions.add(Permission.objects.get(codename="prepare_artifacts"))
    with pytest.raises(ValidationError):
        request_artifact_preparation(other, installed.id, package_input())
    assert PreparationOperation.objects.get().pk == first.id
