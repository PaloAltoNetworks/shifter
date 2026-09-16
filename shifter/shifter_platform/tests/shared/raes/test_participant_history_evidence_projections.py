"""Read-projection (redaction) tests for RAES participant history/evidence records (#1289)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from shared.models import RaesParticipantRuntimeRecord
from shared.raes.contracts import SHIFTER_BACKEND_PROFILE
from shared.raes.participant_runtime_projections import (
    RECORD_KIND_PARTICIPANT_BEHAVIOR_HISTORY,
    RECORD_KIND_PARTICIPANT_EVIDENCE,
    RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND,
    list_participant_runtime_records,
)
from shared.schemas.raes_participant_runtime import (
    PAYLOAD_KEYS_BY_RECORD_KIND,
    canonical_raes_payload_digest,
)

pytestmark = pytest.mark.django_db

_CONTRACT_VERSION = {
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_BEHAVIOR_HISTORY: "participant-behavior-history-v1",
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_EVIDENCE: "participant-evidence-v1",
}


def _record(request_id, *, record_kind, payload, participant_ref="ctf-participant-1"):
    now = timezone.now()
    return RaesParticipantRuntimeRecord.objects.create(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=f"{record_kind}:{participant_ref}:{now.isoformat()}",
        contract_kind=RaesParticipantRuntimeRecord.ContractKind.RAES,
        contract_version=_CONTRACT_VERSION[record_kind],
        contract_profile=SHIFTER_BACKEND_PROFILE,
        participant_runtime_profile="shifter-provisioning",
        record_kind=record_kind,
        source_timestamp=now,
        payload_digest=canonical_raes_payload_digest(payload),
        payload=payload,
    )


def test_new_kind_response_allowlists_are_subsets_and_exclude_request_id():
    for record_kind in (RECORD_KIND_PARTICIPANT_EVIDENCE, RECORD_KIND_PARTICIPANT_BEHAVIOR_HISTORY):
        response_keys = RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND[record_kind]
        assert response_keys <= PAYLOAD_KEYS_BY_RECORD_KIND[record_kind]
        assert "request_id" not in response_keys


def test_evidence_projection_redacts_request_id_from_payload():
    request_id = uuid4()
    payload = {
        "participant_ref": "ctf-participant-1",
        "request_id": str(request_id),
        "evidence_kind": "artifact_ref",
        "capture_profile": "reference_only",
        "provenance_source": "object_storage",
        "provenance_ref": "range-artifacts/p1/out.bin",
        "artifact_ref": "range-artifacts/p1/out.bin",
        "artifact_digest": "sha256:" + "a" * 64,
        "redaction_policy": "reference_only",
    }
    _record(request_id, record_kind=RECORD_KIND_PARTICIPANT_EVIDENCE, payload=payload)

    [proj] = list_participant_runtime_records(request_id, RECORD_KIND_PARTICIPANT_EVIDENCE)

    assert "request_id" not in proj.payload
    assert set(proj.payload) == {
        "participant_ref",
        "evidence_kind",
        "capture_profile",
        "provenance_source",
        "provenance_ref",
        "artifact_ref",
        "artifact_digest",
        "redaction_policy",
    }


def test_behavior_history_projection_redacts_request_id_from_payload():
    request_id = uuid4()
    payload = {
        "participant_ref": "ctf-participant-1",
        "request_id": str(request_id),
        "event_kind": "command_dispatched",
        "event_ref": "range-event-9f2c",
        "event_digest": "sha256:" + "b" * 64,
        "sequence": 2,
    }
    _record(request_id, record_kind=RECORD_KIND_PARTICIPANT_BEHAVIOR_HISTORY, payload=payload)

    [proj] = list_participant_runtime_records(request_id, RECORD_KIND_PARTICIPANT_BEHAVIOR_HISTORY)

    assert "request_id" not in proj.payload
    assert set(proj.payload) == {"participant_ref", "event_kind", "event_ref", "event_digest", "sequence"}


def test_projection_surfaces_retention_and_redaction_metadata():
    request_id = uuid4()
    payload = {
        "participant_ref": "ctf-participant-1",
        "evidence_kind": "artifact_ref",
        "capture_profile": "reference_only",
        "provenance_source": "object_storage",
        "provenance_ref": "range-artifacts/p1/out.bin",
        "artifact_ref": "range-artifacts/p1/out.bin",
        "artifact_digest": "sha256:" + "a" * 64,
        "redaction_policy": "reference_only",
    }
    _record(request_id, record_kind=RECORD_KIND_PARTICIPANT_EVIDENCE, payload=payload)

    [proj] = list_participant_runtime_records(request_id, RECORD_KIND_PARTICIPANT_EVIDENCE)

    assert proj.retention_class == "default"
    assert proj.redaction_state == "sanitized"
