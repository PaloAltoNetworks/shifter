"""Engine-owned signed-receipt registration and assignment fencing."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range, ReceiptVerifierRegistration, Request
from engine.services import (
    ReceiptBindingUnavailable,
    ReceiptRegistrationConflict,
    cancel_range_by_request,
    destroy_range,
    destroy_range_by_request,
    project_receipt_verifier_binding,
    reassign_range_owner_by_request,
    register_receipt_verifier,
    revoke_receipt_verifier,
)
from shared.enums import RequestType, ResourceStatus
from shared.models import AuditLog
from shared.receipt_validation import ReceiptKeyMode, ReceiptRegistrationDemand
from shared.schemas import RangeRef

pytestmark = pytest.mark.django_db

_WORKSPACE_ID = 1
_PROVISIONING_OPERATION_ID = uuid4()


def _owned_range(*, status: str = Range.Status.READY):
    user = get_user_model().objects.create_user(username=f"receipt-{uuid4()}@example.test")
    request = Request.objects.create(
        request_id=uuid4(),
        request_type=RequestType.RANGE.value,
        user=user,
    )
    range_obj = Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        cms_user_id=user.pk,
        status=status,
        provisioner_operation="provision",
        provisioner_operation_id=_PROVISIONING_OPERATION_ID,
    )
    return user, request, range_obj


def _demand(
    *,
    event_id=None,
    participant_id=None,
    objectives=("flag-agent-control",),
    reset_generation=0,
    secret_version_ref=None,
):
    return ReceiptRegistrationDemand(
        deployment_id="gcp-dev",
        profile_id="keplerops-penr1",
        provider_contract="penr1-v1",
        ctf_event_id=event_id or uuid4(),
        ctf_participant_id=participant_id or uuid4(),
        objectives=objectives,
        issuer_id="keplerops-proof",
        provider_range_namespace="range-355-a1",
        provider_participant_namespace="participant-01",
        key_mode=ReceiptKeyMode.REMOTE_SYMMETRIC,
        algorithm_id="hmac-sha256",
        key_id="range-key-v1",
        secret_version_ref=secret_version_ref or "provider-secret-version-ref",
        reset_generation=reset_generation,
    )


def test_registration_projects_only_the_active_server_binding():
    user, request, range_obj = _owned_range()
    demand = _demand()

    registered = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)
    projected = project_receipt_verifier_binding(
        request.request_id,
        owner_user_id=user.pk,
        event_id=demand.ctf_event_id,
        participant_id=demand.ctf_participant_id,
        profile_id=demand.profile_id,
        objective_id="flag-agent-control",
    )

    assert registered.registration_revision == projected.registration_revision
    assert projected.materialization_id == range_obj.uuid
    assert projected.provider_range_namespace == demand.provider_range_namespace
    assert projected.provider_participant_namespace == demand.provider_participant_namespace
    assert projected.assignment_epoch == registered.assignment_epoch
    assert not hasattr(projected, "secret_version_ref")


def test_exact_registration_replay_is_idempotent_but_changed_binding_conflicts():
    _user, request, _range_obj = _owned_range()
    demand = _demand()

    first = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)
    second = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)

    assert second.registration_revision == first.registration_revision
    assert ReceiptVerifierRegistration.objects.count() == 1

    changed_demand = _demand(participant_id=uuid4())
    with pytest.raises(ReceiptRegistrationConflict):
        register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, changed_demand)


def test_registration_rejects_stale_operation_generation_and_non_provision_operation():
    _user, request, range_obj = _owned_range(status=Range.Status.PROVISIONING)

    stale_operation_id = uuid4()
    demand = _demand()
    with pytest.raises(ReceiptBindingUnavailable, match="operation generation"):
        register_receipt_verifier(request.request_id, stale_operation_id, demand)

    range_obj.provisioner_operation = "destroy"
    range_obj.save(update_fields=["provisioner_operation"])
    with pytest.raises(ReceiptBindingUnavailable, match="operation generation"):
        register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)


def test_rotated_operation_generation_immediately_fences_active_projection():
    user, request, range_obj = _owned_range()
    demand = _demand()
    register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)

    range_obj.provisioner_operation_id = uuid4()
    range_obj.save(update_fields=["provisioner_operation_id"])

    with pytest.raises(ReceiptBindingUnavailable):
        project_receipt_verifier_binding(
            request.request_id,
            owner_user_id=user.pk,
            event_id=demand.ctf_event_id,
            participant_id=demand.ctf_participant_id,
            profile_id=demand.profile_id,
            objective_id="flag-agent-control",
        )


def test_asymmetric_registration_projects_only_public_verification_material():
    user, request, _range_obj = _owned_range()
    demand = replace(
        _demand(),
        key_mode=ReceiptKeyMode.ASYMMETRIC_PUBLIC,
        algorithm_id="ed25519",
        key_id="range-public-key-v1",
        secret_version_ref="",
        public_verification_key="-----BEGIN PUBLIC KEY-----\nunit-test-public-material\n-----END PUBLIC KEY-----",
    )

    binding = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)

    assert binding.key_mode is ReceiptKeyMode.ASYMMETRIC_PUBLIC
    assert binding.algorithm_id == "ed25519"
    assert binding.key_id == "range-public-key-v1"
    assert binding.public_verification_key == demand.public_verification_key
    assert (
        project_receipt_verifier_binding(
            request.request_id,
            owner_user_id=user.pk,
            event_id=demand.ctf_event_id,
            participant_id=demand.ctf_participant_id,
            profile_id=demand.profile_id,
            objective_id="flag-agent-control",
        )
        == binding
    )


def test_registration_audit_contains_only_bounded_security_metadata():
    _user, request, _range_obj = _owned_range()
    demand = _demand()

    binding = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)

    audit = AuditLog.objects.get(
        context="receipt_verifier_registration",
        entity_id=_range_obj.pk,
    )
    encoded = json.dumps(audit.new_state, sort_keys=True)
    assert audit.new_state["receipt_registration_revision"] == str(binding.registration_revision)
    assert audit.new_state["receipt_provisioning_operation_id"] == str(_PROVISIONING_OPERATION_ID)
    assert demand.secret_version_ref not in encoded
    assert demand.provider_range_namespace not in encoded
    assert demand.provider_participant_namespace not in encoded
    assert str(demand.ctf_participant_id) not in encoded


@pytest.mark.parametrize(
    "override",
    [
        {"owner_user_id": 999999},
        {"event_id": uuid4()},
        {"participant_id": uuid4()},
        {"profile_id": "another-profile"},
        {"objective_id": "another-objective"},
    ],
)
def test_projection_rejects_every_foreign_binding(override):
    user, request, _range_obj = _owned_range()
    demand = _demand()
    register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)
    query = {
        "owner_user_id": user.pk,
        "event_id": demand.ctf_event_id,
        "participant_id": demand.ctf_participant_id,
        "profile_id": demand.profile_id,
        "objective_id": "flag-agent-control",
    }
    query.update(override)

    with pytest.raises(ReceiptBindingUnavailable):
        project_receipt_verifier_binding(request.request_id, **query)


def test_pause_and_explicit_revocation_fail_closed():
    user, request, range_obj = _owned_range()
    demand = _demand()
    register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)
    range_obj.status = Range.Status.PAUSED
    range_obj.save(update_fields=["status"])

    with pytest.raises(ReceiptBindingUnavailable):
        project_receipt_verifier_binding(
            request.request_id,
            owner_user_id=user.pk,
            event_id=demand.ctf_event_id,
            participant_id=demand.ctf_participant_id,
            profile_id=demand.profile_id,
            objective_id="flag-agent-control",
        )

    range_obj.status = Range.Status.READY
    range_obj.save(update_fields=["status"])
    assert revoke_receipt_verifier(request.request_id) is True
    assert revoke_receipt_verifier(request.request_id) is False

    with pytest.raises(ReceiptBindingUnavailable):
        project_receipt_verifier_binding(
            request.request_id,
            owner_user_id=user.pk,
            event_id=demand.ctf_event_id,
            participant_id=demand.ctf_participant_id,
            profile_id=demand.profile_id,
            objective_id="flag-agent-control",
        )


def test_owner_reassignment_revokes_the_previous_assignment_epoch():
    old_user, request, _range_obj = _owned_range()
    new_user = get_user_model().objects.create_user(username=f"receipt-new-{uuid4()}@example.test")
    demand = _demand()
    registered = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, demand)

    assert reassign_range_owner_by_request(request.request_id, new_user) is True

    row = ReceiptVerifierRegistration.objects.get(registration_revision=registered.registration_revision)
    assert row.status == ReceiptVerifierRegistration.Status.REVOKED
    assert row.revoked_at is not None

    with pytest.raises(ReceiptBindingUnavailable):
        project_receipt_verifier_binding(
            request.request_id,
            owner_user_id=old_user.pk,
            event_id=demand.ctf_event_id,
            participant_id=demand.ctf_participant_id,
            profile_id=demand.profile_id,
            objective_id="flag-agent-control",
        )


def test_reset_registration_rotates_revision_epoch_and_key_reference():
    user, request, _range_obj = _owned_range()
    first_demand = _demand()
    first = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, first_demand)
    assert revoke_receipt_verifier(request.request_id) is True

    next_operation_id = uuid4()
    _range_obj.provisioner_operation_id = next_operation_id
    _range_obj.save(update_fields=["provisioner_operation_id"])

    reset_demand = _demand(
        event_id=first_demand.ctf_event_id,
        participant_id=first_demand.ctf_participant_id,
        reset_generation=1,
        secret_version_ref="provider-secret-version-ref-v2",
    )
    second = register_receipt_verifier(request.request_id, next_operation_id, reset_demand)

    assert second.registration_revision != first.registration_revision
    assert second.assignment_epoch != first.assignment_epoch
    assert second.reset_generation == 1
    assert (
        project_receipt_verifier_binding(
            request.request_id,
            owner_user_id=user.pk,
            event_id=reset_demand.ctf_event_id,
            participant_id=reset_demand.ctf_participant_id,
            profile_id=reset_demand.profile_id,
            objective_id="flag-agent-control",
        )
        == second
    )


def test_teardown_revokes_receipt_registration_before_dispatch(monkeypatch):
    _user, request, _range_obj = _owned_range()
    registered = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, _demand())
    dispatched = []
    monkeypatch.setattr("engine.ecs.start_range_teardown", lambda request_id: dispatched.append(request_id))

    assert destroy_range_by_request(request.request_id) is True

    row = ReceiptVerifierRegistration.objects.get(registration_revision=registered.registration_revision)
    assert row.status == ReceiptVerifierRegistration.Status.REVOKED
    assert row.revoked_at is not None
    assert dispatched == [request.request_id]


def test_range_id_teardown_revokes_receipt_registration_before_dispatch(monkeypatch):
    user, request, range_obj = _owned_range()
    registered = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, _demand())
    dispatched = []
    monkeypatch.setattr("engine.ecs.start_teardown", lambda range_id, user_id: dispatched.append((range_id, user_id)))

    assert (
        destroy_range(
            RangeRef(
                request_id=request.request_id,
                range_id=range_obj.pk,
                user_id=user.pk,
                status=ResourceStatus.READY,
            )
        )
        is True
    )

    row = ReceiptVerifierRegistration.objects.get(registration_revision=registered.registration_revision)
    assert row.status == ReceiptVerifierRegistration.Status.REVOKED
    assert dispatched == [(range_obj.pk, user.pk)]


def test_cancel_revokes_registration_created_during_provisioning():
    _user, request, _range_obj = _owned_range(status=Range.Status.PROVISIONING)
    registered = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, _demand())

    assert cancel_range_by_request(request.request_id) is True

    row = ReceiptVerifierRegistration.objects.get(registration_revision=registered.registration_revision)
    assert row.status == ReceiptVerifierRegistration.Status.REVOKED


def test_terminal_failure_result_revokes_receipt_registration(monkeypatch):
    _user, request, range_obj = _owned_range()
    registered = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, _demand())
    monkeypatch.setattr("engine.services._operation_apply_domain._audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "engine.services._operation_apply_domain._enqueue_range_status_event",
        lambda *args, **kwargs: None,
    )
    from engine.services._operation_apply_domain import _apply_failure

    _apply_failure(range_obj, {"reason_code": "cloud_operation_failed"}, str(request.request_id), is_range=True)

    row = ReceiptVerifierRegistration.objects.get(registration_revision=registered.registration_revision)
    assert row.status == ReceiptVerifierRegistration.Status.REVOKED


def test_raes_destroy_result_revokes_receipt_registration(monkeypatch):
    _user, request, range_obj = _owned_range()
    binding = register_receipt_verifier(request.request_id, _PROVISIONING_OPERATION_ID, _demand())
    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])
    monkeypatch.setattr("engine.services._operation_apply_raes._audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "engine.services._operation_apply_raes._enqueue_range_status_event",
        lambda *args, **kwargs: None,
    )
    from engine.services._operation_apply_raes import _apply_lifecycle

    _apply_lifecycle(range_obj, ResourceStatus.DESTROYED.value, str(request.request_id))

    row = ReceiptVerifierRegistration.objects.get(registration_revision=binding.registration_revision)
    assert row.status == ReceiptVerifierRegistration.Status.REVOKED
