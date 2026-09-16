"""End-to-end tests for the Mission Control RAES participant-runtime read APIs (#1288).

Drives the real DRF endpoints with ``APIClient`` against real ``RangeInstance``
/ ``Request`` rows and seeded ``RaesParticipantRuntimeRecord`` sidecar rows.
Covers authorized session + token reads, forbidden/fail-closed cases,
ownership 404s (no enumeration), response redaction, bounded limit,
participant-ref filtering, and empty-range behavior -- same pattern as
``tests/mission_control/test_raes_api.py`` for operation records.
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
from shared.models import RaesParticipantRuntimeRecord
from shared.raes.contracts import SHIFTER_BACKEND_PROFILE
from shared.schemas.raes_participant_runtime import canonical_raes_payload_digest

pytestmark = pytest.mark.django_db

_CONTRACT_VERSION = {
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION: "participant-implementation-v1",
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME: "participant-runtime-v1",
}


def _implementations_url(request_id) -> str:
    return f"/api/v1/mission-control/range/{request_id}/raes/participant-implementations/"


def _runtimes_url(request_id) -> str:
    return f"/api/v1/mission-control/range/{request_id}/raes/participant-runtimes/"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="raes-pr-mc@example.com", email="raes-pr-mc@example.com")


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        username="raes-pr-other@example.com", email="raes-pr-other@example.com"
    )


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


def _seed_record(request_id, *, participant_ref, record_kind, payload, source_timestamp=None):
    ts = source_timestamp or timezone.now()
    return RaesParticipantRuntimeRecord.objects.create(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=f"{record_kind}:{participant_ref}:{ts.isoformat()}",
        contract_kind=RaesParticipantRuntimeRecord.ContractKind.RAES,
        contract_version=_CONTRACT_VERSION[record_kind],
        contract_profile=SHIFTER_BACKEND_PROFILE,
        participant_runtime_profile="shifter-provisioning",
        record_kind=record_kind,
        source_timestamp=ts,
        payload_digest=canonical_raes_payload_digest(payload),
        payload=payload,
    )


def _token(user, *granted_scopes: str) -> str:
    _, raw = ApiToken.create_token(name="raes-pr-mc", created_by=user, scopes=list(granted_scopes))
    return raw


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


class TestParticipantRuntimeRead:
    def test_session_owner_reads_runtime(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        client.force_authenticate(user=user)
        response = client.get(_runtimes_url(request_id))
        assert response.status_code == 200
        body = response.json()
        assert body["record_kind"] == "participant_runtime"
        assert body["request_id"] == str(request_id)
        assert len(body["results"]) == 1
        assert body["results"][0]["payload"]["status"] == "running"

    def test_token_with_range_read_scope_reads_runtime(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "ready"},
        )
        _bearer(client, _token(user, scopes.MISSION_CONTROL_RANGE_READ))
        response = client.get(_runtimes_url(request_id))
        assert response.status_code == 200
        assert response.json()["results"][0]["payload"]["status"] == "ready"

    def test_anonymous_is_rejected(self, client, user):
        request_id = _owned_range(user)
        response = client.get(_runtimes_url(request_id))
        assert response.status_code in (401, 403)

    def test_token_without_range_read_scope_is_forbidden(self, client, user):
        request_id = _owned_range(user)
        _bearer(client, _token(user, scopes.MISSION_CONTROL_UPLOAD_WRITE))
        response = client.get(_runtimes_url(request_id))
        assert response.status_code == 403

    def test_malformed_bearer_fails_closed_over_session(self, client, user):
        request_id = _owned_range(user)
        # A real session login plus a malformed bearer: ApiTokenAuthentication
        # runs first and must fail closed (401), never fall through to session.
        client.force_login(user)
        _bearer(client, "shf_missing.invalid")
        response = client.get(_runtimes_url(request_id))
        assert response.status_code == 401

    def test_other_users_range_is_not_found(self, client, user, other_user):
        request_id = _owned_range(other_user)
        _seed_record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        client.force_authenticate(user=user)
        response = client.get(_runtimes_url(request_id))
        assert response.status_code == 404

    def test_membership_removal_revokes_runtime_read(self, client, user):
        request_id = _owned_range(user)
        _revoke_workspace_membership(user)
        client.force_authenticate(user=user)

        assert client.get(_runtimes_url(request_id)).status_code == 404

    def test_unknown_request_id_is_not_found(self, client, user):
        client.force_authenticate(user=user)
        response = client.get(_runtimes_url(uuid4()))
        assert response.status_code == 404

    def test_response_redacts_non_allowlisted_payload_keys(self, client, user):
        request_id = _owned_range(user)
        # ``request_id`` is a valid persisted payload key but not in the
        # response allowlist; the API must not echo it inside ``payload``.
        _seed_record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running", "request_id": str(request_id)},
        )
        client.force_authenticate(user=user)
        response = client.get(_runtimes_url(request_id))
        payload = response.json()["results"][0]["payload"]
        assert set(payload) == {"participant_ref", "status"}
        assert "request_id" not in payload

    def test_invalid_limit_returns_error_envelope(self, client, user):
        request_id = _owned_range(user)
        client.force_authenticate(user=user)
        response = client.get(_runtimes_url(request_id), {"limit": 0})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"

    def test_empty_range_returns_empty(self, client, user):
        request_id = _owned_range(user)  # no participant-runtime rows seeded
        client.force_authenticate(user=user)
        response = client.get(_runtimes_url(request_id))
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_participant_ref_filters_results(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        _seed_record(
            request_id,
            participant_ref="ctf-participant-2",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-2", "status": "accepted"},
        )
        client.force_authenticate(user=user)
        response = client.get(_runtimes_url(request_id), {"participant_ref": "ctf-participant-2"})
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["payload"]["status"] == "accepted"


class TestParticipantImplementationRead:
    def test_owner_reads_implementations(self, client, user):
        request_id = _owned_range(user)
        _seed_record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION,
            payload={"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1"},
        )
        client.force_authenticate(user=user)
        response = client.get(_implementations_url(request_id))
        assert response.status_code == 200
        assert response.json()["record_kind"] == "participant_implementation"
        assert response.json()["results"][0]["payload"]["implementation_ref"] == "impl-1"

    def test_implementations_do_not_leak_other_users_range(self, client, user, other_user):
        request_id = _owned_range(other_user)
        client.force_authenticate(user=user)
        assert client.get(_implementations_url(request_id)).status_code == 404

    def test_membership_removal_revokes_implementation_read(self, client, user):
        request_id = _owned_range(user)
        _revoke_workspace_membership(user)
        client.force_authenticate(user=user)

        assert client.get(_implementations_url(request_id)).status_code == 404
