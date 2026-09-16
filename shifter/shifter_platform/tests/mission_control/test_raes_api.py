"""End-to-end tests for the Mission Control RAES operation read APIs (#1275).

Drives the real DRF endpoints with ``APIClient`` against real ``RangeInstance``
/ ``Request`` rows and seeded ``RaesOperationRecord`` sidecar rows. Covers
authorized session + token reads, forbidden/fail-closed cases, ownership 404s
(no enumeration), response redaction, bounded limit, and legacy non-RAES
behavior.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from cms.models import RangeInstance, Request
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.enums import RequestType
from shared.models import RaesOperationRecord, RaesParticipantRuntimeRecord
from shared.raes.contracts import SHIFTER_BACKEND_PROFILE
from shared.schemas.raes_operation import canonical_raes_payload_digest
from shared.schemas.raes_participant_runtime import (
    canonical_raes_payload_digest as canonical_participant_payload_digest,
)

pytestmark = pytest.mark.django_db

_CONTRACT_VERSION = {
    RaesOperationRecord.RecordKind.OPERATION_RECEIPT: "operation-receipt-v1",
    RaesOperationRecord.RecordKind.OPERATION_STATUS: "operation-status-v1",
    RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT: "runtime-snapshot-v1",
}

_PARTICIPANT_CONTRACT_VERSION = {
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION: "participant-implementation-v1",
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME: "participant-runtime-v1",
}


def _status_url(request_id) -> str:
    return f"/api/v1/mission-control/range/{request_id}/raes/operation-status/"


def _receipts_url(request_id) -> str:
    return f"/api/v1/mission-control/range/{request_id}/raes/operation-receipts/"


def _snapshots_url(request_id) -> str:
    return f"/api/v1/mission-control/range/{request_id}/raes/snapshots/"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="raes-mc@example.com", email="raes-mc@example.com")


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(username="raes-other@example.com", email="raes-other@example.com")


@pytest.fixture
def client():
    return APIClient()


def _owned_range(user):
    """Create a RangeInstance + Request owned by ``user``; return the request_id."""
    from workspaces.services import resolve_personal_workspace

    workspace_id = resolve_personal_workspace(user).workspace_id
    request = Request.objects.create(
        workspace_id=workspace_id, request_id=uuid4(), request_type=RequestType.RANGE.value, user=user
    )
    RangeInstance.objects.create(
        workspace_id=workspace_id, scenario_id="basic", user_id=user.id, status="ready", request=request
    )
    return request.request_id


def _revoke_workspace_membership(user) -> None:
    from workspaces.models import WorkspaceMembership

    WorkspaceMembership.objects.filter(user=user).delete()


def _seed_record(request_id, *, record_kind, payload, source_timestamp=None):
    return RaesOperationRecord.objects.create(
        request_id=request_id,
        operation_id=payload["operation_id"],
        idempotency_key=f"{record_kind}:{(source_timestamp or timezone.now()).isoformat()}",
        contract_kind=RaesOperationRecord.ContractKind.RAES,
        contract_version=_CONTRACT_VERSION[record_kind],
        contract_profile=SHIFTER_BACKEND_PROFILE,
        record_kind=record_kind,
        source_timestamp=source_timestamp or timezone.now(),
        payload_digest=canonical_raes_payload_digest(payload),
        payload=payload,
    )


def _seed_participant_record(request_id, *, participant_ref, record_kind, payload, source_timestamp=None):
    ts = source_timestamp or timezone.now()
    return RaesParticipantRuntimeRecord.objects.create(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=f"{record_kind}:{participant_ref}:{ts.isoformat()}",
        contract_kind=RaesParticipantRuntimeRecord.ContractKind.RAES,
        contract_version=_PARTICIPANT_CONTRACT_VERSION[record_kind],
        contract_profile=SHIFTER_BACKEND_PROFILE,
        participant_runtime_profile="shifter-provisioning",
        record_kind=record_kind,
        source_timestamp=ts,
        payload_digest=canonical_participant_payload_digest(payload),
        payload=payload,
    )


def _token(user, *granted_scopes: str) -> str:
    _, raw = ApiToken.create_token(name="raes-mc", created_by=user, scopes=list(granted_scopes))
    return raw


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


class TestOperationStatusRead:
    def test_session_owner_reads_status(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS,
            payload={"operation_id": "op-1", "status": "running"},
        )
        client.force_authenticate(user=user)
        response = client.get(_status_url(request_id))
        assert response.status_code == 200
        body = response.json()
        assert body["record_kind"] == "operation_status"
        assert body["request_id"] == str(request_id)
        assert len(body["results"]) == 1
        assert body["results"][0]["payload"]["status"] == "running"

    def test_token_with_range_read_scope_reads_status(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS,
            payload={"operation_id": "op-1", "status": "ready"},
        )
        _bearer(client, _token(user, scopes.MISSION_CONTROL_RANGE_READ))
        response = client.get(_status_url(request_id))
        assert response.status_code == 200
        assert response.json()["results"][0]["payload"]["status"] == "ready"

    def test_anonymous_is_rejected(self, client, user):
        request_id = _owned_range(user)
        response = client.get(_status_url(request_id))
        assert response.status_code in (401, 403)

    def test_token_without_range_read_scope_is_forbidden(self, client, user):
        request_id = _owned_range(user)
        _bearer(client, _token(user, scopes.MISSION_CONTROL_UPLOAD_WRITE))
        response = client.get(_status_url(request_id))
        assert response.status_code == 403

    def test_malformed_bearer_fails_closed_over_session(self, client, user):
        request_id = _owned_range(user)
        # A real session login plus a malformed bearer: ApiTokenAuthentication
        # runs first and must fail closed (401), never fall through to session.
        client.force_login(user)
        _bearer(client, "shf_missing.invalid")
        response = client.get(_status_url(request_id))
        assert response.status_code == 401

    def test_other_users_range_is_not_found(self, client, user, other_user):
        request_id = _owned_range(other_user)
        _seed_record(
            request_id,
            record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS,
            payload={"operation_id": "op-1", "status": "running"},
        )
        client.force_authenticate(user=user)
        response = client.get(_status_url(request_id))
        assert response.status_code == 404

    def test_membership_removal_revokes_status_read(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS,
            payload={"operation_id": "op-1", "status": "running"},
        )
        _revoke_workspace_membership(user)
        client.force_authenticate(user=user)

        assert client.get(_status_url(request_id)).status_code == 404

    def test_unknown_request_id_is_not_found(self, client, user):
        client.force_authenticate(user=user)
        response = client.get(_status_url(uuid4()))
        assert response.status_code == 404

    def test_response_redacts_non_allowlisted_payload_keys(self, client, user):
        request_id = _owned_range(user)
        # ``request_id`` is a valid persisted payload key but not in the response
        # allowlist; the API must not echo it inside ``payload``.
        _seed_record(
            request_id,
            record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS,
            payload={"operation_id": "op-1", "status": "running", "request_id": str(request_id)},
        )
        client.force_authenticate(user=user)
        response = client.get(_status_url(request_id))
        payload = response.json()["results"][0]["payload"]
        assert set(payload) == {"operation_id", "status"}
        assert "request_id" not in payload

    def test_invalid_limit_returns_error_envelope(self, client, user):
        request_id = _owned_range(user)
        client.force_authenticate(user=user)
        response = client.get(_status_url(request_id), {"limit": 0})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"

    def test_legacy_non_raes_range_returns_empty(self, client, user):
        request_id = _owned_range(user)  # no RAES rows seeded
        client.force_authenticate(user=user)
        response = client.get(_status_url(request_id))
        assert response.status_code == 200
        assert response.json()["results"] == []


class TestReceiptsAndSnapshotsRead:
    def test_owner_reads_receipts(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            record_kind=RaesOperationRecord.RecordKind.OPERATION_RECEIPT,
            payload={"operation_id": "op-1", "status": "accepted", "accepted": True},
        )
        client.force_authenticate(user=user)
        response = client.get(_receipts_url(request_id))
        assert response.status_code == 200
        assert response.json()["record_kind"] == "operation_receipt"
        assert response.json()["results"][0]["payload"]["accepted"] is True

    def test_owner_reads_snapshots(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            record_kind=RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
            payload={
                "operation_id": "op-1",
                "resources": [
                    {
                        "address": "node.web",
                        "resource_type": "node",
                        "status": "provisioned",
                    }
                ],
            },
        )
        client.force_authenticate(user=user)
        response = client.get(_snapshots_url(request_id))
        assert response.status_code == 200
        assert response.json()["record_kind"] == "runtime_snapshot"
        assert response.json()["results"][0]["payload"]["resources"] == [
            {"address": "node.web", "resource_type": "node", "status": "provisioned"}
        ]

    def test_snapshots_do_not_leak_other_users_range(self, client, user, other_user):
        request_id = _owned_range(other_user)
        client.force_authenticate(user=user)
        assert client.get(_snapshots_url(request_id)).status_code == 404

    def test_membership_removal_revokes_snapshot_read(self, client, user):
        request_id = _owned_range(user)
        _revoke_workspace_membership(user)
        client.force_authenticate(user=user)

        assert client.get(_snapshots_url(request_id)).status_code == 404


_CURRENT_RANGE_URL = "/api/v1/mission-control/range/"


class TestCurrentRangeRaesProjection:
    """The canonical current-range read carries an optional RAES projection (#1276)."""

    def test_projection_present_when_records_exist(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS,
            payload={"operation_id": "op-1", "status": "running", "status_reason": "provisioning"},
        )
        client.force_authenticate(user=user)
        body = client.get(_CURRENT_RANGE_URL).json()

        assert body["has_range"] is True
        projection = body["raes_projection"]
        assert projection is not None
        assert projection["status"] == "running"
        assert projection["status_label"] == "Operation running"
        # The Shifter lifecycle status is untouched by the RAES projection.
        assert body["range"]["status"] == "ready"

    def test_projection_null_for_legacy_range(self, client, user):
        _owned_range(user)  # no RAES sidecar rows
        client.force_authenticate(user=user)
        body = client.get(_CURRENT_RANGE_URL).json()

        assert body["has_range"] is True
        assert body["raes_projection"] is None

    def test_projection_absent_when_no_range(self, client, user):
        client.force_authenticate(user=user)
        body = client.get(_CURRENT_RANGE_URL).json()

        assert body["has_range"] is False
        assert body["raes_projection"] is None


class TestCurrentRangeRaesParticipantRuntime:
    """The canonical current-range read carries an optional participant/runtime
    projection (#1290), sibling to ``raes_projection`` (#1276)."""

    def test_participant_runtime_present_when_records_exist(self, client, user):
        request_id = _owned_range(user)
        _seed_participant_record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        client.force_authenticate(user=user)
        body = client.get(_CURRENT_RANGE_URL).json()

        assert body["has_range"] is True
        participant_runtime = body["raes_participant_runtime"]
        assert participant_runtime is not None
        assert participant_runtime["participants"][0]["participant_ref"] == "ctf-participant-1"
        assert participant_runtime["participants"][0]["runtime"]["status"] == "running"
        # Exactly one range-level backend_command channel, keyed by request_id.
        backend_commands = [c for c in participant_runtime["access_channels"] if c["channel"] == "backend_command"]
        assert len(backend_commands) == 1
        assert backend_commands[0]["target_ref"] == str(request_id)
        # Existing keys and the sibling raes_projection are unaffected.
        assert body["raes_projection"] is None
        assert body["range"]["status"] == "ready"

    def test_participant_runtime_null_for_legacy_range(self, client, user):
        _owned_range(user)  # no participant-runtime sidecar rows
        client.force_authenticate(user=user)
        body = client.get(_CURRENT_RANGE_URL).json()

        assert body["has_range"] is True
        assert body["raes_participant_runtime"] is None

    def test_participant_runtime_absent_when_no_range(self, client, user):
        client.force_authenticate(user=user)
        body = client.get(_CURRENT_RANGE_URL).json()

        assert body["has_range"] is False
        assert body["raes_participant_runtime"] is None
