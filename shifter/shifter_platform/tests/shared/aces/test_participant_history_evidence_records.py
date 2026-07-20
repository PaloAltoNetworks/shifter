"""Persistence tests for ACES participant behavior-history and evidence records (#1289)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from shared.aces.participant_runtime import (
    AcesParticipantRuntimeRecordConflict,
    ParticipantRecordWriteOptions,
    persist_participant_behavior_history_record,
    persist_participant_evidence_record,
)
from shared.models import AcesParticipantRuntimeRecord
from shared.schemas.aces_participant_runtime import AcesParticipantRuntimeRecordError

REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")
SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)

EVIDENCE_PAYLOAD = {
    "participant_ref": "ctf-participant-1",
    "evidence_kind": "artifact_ref",
    "capture_profile": "reference_only",
    "provenance_source": "object_storage",
    "provenance_ref": "range-artifacts/p1/out.bin",
    "artifact_ref": "range-artifacts/p1/out.bin",
    "artifact_digest": "sha256:" + "a" * 64,
    "redaction_policy": "reference_only",
}

HISTORY_PAYLOAD = {
    "participant_ref": "ctf-participant-1",
    "event_kind": "command_dispatched",
    "event_ref": "range-event-9f2c",
    "event_digest": "sha256:" + "b" * 64,
    "sequence": 1,
}


def _evidence(*, participant_ref="ctf-participant-1", source_timestamp=SOURCE_TS, payload=None, options=None):
    return persist_participant_evidence_record(
        request_id=REQUEST_ID,
        participant_ref=participant_ref,
        source_timestamp=source_timestamp,
        payload=dict(EVIDENCE_PAYLOAD) if payload is None else payload,
        options=options,
    )


def _history(*, participant_ref="ctf-participant-1", source_timestamp=SOURCE_TS, payload=None, options=None):
    return persist_participant_behavior_history_record(
        request_id=REQUEST_ID,
        participant_ref=participant_ref,
        source_timestamp=source_timestamp,
        payload=dict(HISTORY_PAYLOAD) if payload is None else payload,
        options=options,
    )


@pytest.mark.django_db
def test_persist_evidence_record_is_idempotent():
    first = _evidence()
    second = _evidence()

    assert first.id == second.id
    assert first.record_kind == AcesParticipantRuntimeRecord.RecordKind.PARTICIPANT_EVIDENCE
    assert first.contract_version == "participant-evidence-v1"
    assert first.owner == AcesParticipantRuntimeRecord.Owner.SHARED
    assert AcesParticipantRuntimeRecord.objects.count() == 1


@pytest.mark.django_db
def test_persist_evidence_record_conflicts_on_payload_drift():
    _evidence()
    drifted = {**EVIDENCE_PAYLOAD, "artifact_digest": "sha256:" + "c" * 64}

    with pytest.raises(AcesParticipantRuntimeRecordConflict, match="idempotency conflict"):
        _evidence(payload=drifted)

    assert AcesParticipantRuntimeRecord.objects.count() == 1


@pytest.mark.django_db
def test_persist_evidence_record_owner_override():
    row = _evidence(options=ParticipantRecordWriteOptions(owner=AcesParticipantRuntimeRecord.Owner.CTF))
    assert row.owner == AcesParticipantRuntimeRecord.Owner.CTF


@pytest.mark.django_db
def test_persist_evidence_distinct_provenance_refs_do_not_collide():
    ref_a = "range-artifacts/p1/a.bin"
    ref_b = "range-artifacts/p1/b.bin"
    _evidence(payload={**EVIDENCE_PAYLOAD, "provenance_ref": ref_a, "artifact_ref": ref_a})
    _evidence(payload={**EVIDENCE_PAYLOAD, "provenance_ref": ref_b, "artifact_ref": ref_b})
    assert AcesParticipantRuntimeRecord.objects.count() == 2


@pytest.mark.django_db
def test_persist_evidence_same_ref_distinct_sources_do_not_collide():
    # A provenance_ref is only meaningful inside its provenance_source namespace,
    # so two boundaries emitting the same local ref under different sources are
    # distinct evidence and must not collapse onto one row.
    same_ref = "shared-local-ref"
    _evidence(
        payload={
            **EVIDENCE_PAYLOAD,
            "provenance_source": "object_storage",
            "provenance_ref": same_ref,
            "artifact_ref": same_ref,
        }
    )
    _evidence(
        payload={
            **EVIDENCE_PAYLOAD,
            "provenance_source": "upload_inspection",
            "provenance_ref": same_ref,
            "artifact_ref": same_ref,
        }
    )
    assert AcesParticipantRuntimeRecord.objects.count() == 2


@pytest.mark.django_db
def test_persist_evidence_rejects_participant_ref_payload_mismatch():
    # participant_ref is the correlation column; a payload echoing a different
    # participant_ref would drift the row content from the key.
    with pytest.raises(AcesParticipantRuntimeRecordConflict, match="conflicts with identity"):
        _evidence(
            participant_ref="ctf-participant-1", payload={**EVIDENCE_PAYLOAD, "participant_ref": "ctf-participant-2"}
        )
    assert AcesParticipantRuntimeRecord.objects.count() == 0


@pytest.mark.django_db
def test_persist_evidence_missing_identity_field_raises():
    payload = {k: v for k, v in EVIDENCE_PAYLOAD.items() if k != "provenance_source"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="provenance_source"):
        _evidence(payload=payload)
    assert AcesParticipantRuntimeRecord.objects.count() == 0


@pytest.mark.django_db
def test_persist_behavior_history_record_is_idempotent():
    first = _history()
    second = _history()

    assert first.id == second.id
    assert first.record_kind == AcesParticipantRuntimeRecord.RecordKind.PARTICIPANT_BEHAVIOR_HISTORY
    assert first.contract_version == "participant-behavior-history-v1"
    assert AcesParticipantRuntimeRecord.objects.count() == 1


@pytest.mark.django_db
def test_persist_behavior_history_record_conflicts_on_payload_drift():
    _history()
    drifted = {**HISTORY_PAYLOAD, "event_digest": "sha256:" + "d" * 64}

    with pytest.raises(AcesParticipantRuntimeRecordConflict, match="idempotency conflict"):
        _history(payload=drifted)


@pytest.mark.django_db
def test_persist_behavior_history_rejects_participant_ref_payload_mismatch():
    with pytest.raises(AcesParticipantRuntimeRecordConflict, match="conflicts with identity"):
        _history(
            participant_ref="ctf-participant-1", payload={**HISTORY_PAYLOAD, "participant_ref": "ctf-participant-2"}
        )
    assert AcesParticipantRuntimeRecord.objects.count() == 0


@pytest.mark.django_db
def test_persist_behavior_history_distinct_events_do_not_collide():
    _history(payload={**HISTORY_PAYLOAD, "event_ref": "range-event-1"})
    _history(payload={**HISTORY_PAYLOAD, "event_ref": "range-event-2"})
    assert AcesParticipantRuntimeRecord.objects.count() == 2


@pytest.mark.django_db
def test_typed_helper_key_stays_within_column_for_long_refs():
    long_participant = "p" * 256
    long_ref = "r" * 400
    row = _evidence(
        participant_ref=long_participant,
        payload={
            **EVIDENCE_PAYLOAD,
            "participant_ref": long_participant,
            "provenance_ref": long_ref,
            "artifact_ref": long_ref,
        },
    )

    assert len(row.idempotency_key) <= 128
    assert row.idempotency_key.startswith("participant_evidence:")
