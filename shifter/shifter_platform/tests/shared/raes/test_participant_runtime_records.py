"""Tests for RAES participant-runtime sidecar persistence (#1288)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from shared.models import RaesParticipantRuntimeRecord
from shared.raes.participant_runtime import (
    RaesParticipantRuntimeRecordConflict,
    RaesParticipantRuntimeRecordWrite,
    persist_participant_implementation_record,
    persist_participant_runtime_record,
    persist_raes_participant_runtime_record,
)
from shared.schemas.raes_participant_runtime import (
    RaesParticipantRuntimeRecordError,
    canonical_raes_payload_digest,
)

REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")
SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _persist(**overrides):
    fields = {
        "request_id": REQUEST_ID,
        "participant_ref": "ctf-participant-1",
        "idempotency_key": "participant_implementation:ctf-participant-1:impl-1",
        "record_kind": RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION,
        "contract_version": "participant-implementation-v1",
        "source_timestamp": SOURCE_TS,
        "payload": {"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1"},
        "diagnostic_refs": {},
    }
    fields.update(overrides)
    fields.setdefault("payload_digest", canonical_raes_payload_digest(fields["payload"]))
    return persist_raes_participant_runtime_record(RaesParticipantRuntimeRecordWrite(**fields))


@pytest.mark.django_db
def test_persist_participant_runtime_record_is_idempotent_for_same_source_event():
    first = _persist()
    second = _persist()

    assert first.id == second.id
    assert RaesParticipantRuntimeRecord.objects.count() == 1


@pytest.mark.django_db
def test_persist_participant_runtime_record_conflicts_when_replay_payload_drifts():
    _persist()
    changed_payload = {"participant_ref": "ctf-participant-1", "implementation_ref": "impl-2"}
    changed_digest = canonical_raes_payload_digest(changed_payload)

    with pytest.raises(RaesParticipantRuntimeRecordConflict, match="idempotency conflict"):
        _persist(payload=changed_payload, payload_digest=changed_digest)

    assert RaesParticipantRuntimeRecord.objects.count() == 1


@pytest.mark.django_db
def test_persist_participant_runtime_record_conflicts_when_replay_timestamp_drifts():
    _persist()
    changed_timestamp = SOURCE_TS + timedelta(seconds=1)

    with pytest.raises(RaesParticipantRuntimeRecordConflict, match="idempotency conflict"):
        _persist(source_timestamp=changed_timestamp)


@pytest.mark.django_db
def test_persist_participant_runtime_record_records_explicit_discriminators_and_projection_key():
    range_id = uuid4()
    range_instance_id = uuid4()
    row = _persist(
        range_id=range_id,
        range_instance_id=range_instance_id,
        record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
        contract_version="participant-runtime-v1",
        idempotency_key="participant_runtime:ctf-participant-1:2026-07-05T03:00:00+00:00",
        payload={"participant_ref": "ctf-participant-1", "status": "running"},
        diagnostic_refs={},
        retention_expires_at=SOURCE_TS + timedelta(days=7),
    )

    assert row.request_id == REQUEST_ID
    assert row.range_id == range_id
    assert row.range_instance_id == range_instance_id
    assert row.participant_ref == "ctf-participant-1"
    assert row.contract_kind == "raes"
    assert row.contract_version == "participant-runtime-v1"
    assert row.contract_profile == "provisioning-only"
    assert row.participant_runtime_profile == "shifter-provisioning"
    assert row.record_kind == "participant_runtime"
    assert row.source_timestamp == SOURCE_TS
    assert row.owner == "shared"
    assert row.retention_class == "default"
    assert row.redaction_state == "sanitized"
    assert row.retention_expires_at == SOURCE_TS + timedelta(days=7)


@pytest.mark.django_db
def test_persist_participant_runtime_record_rejects_unsupported_profile_before_write():
    with pytest.raises(RaesParticipantRuntimeRecordError, match="contract_profile"):
        _persist(contract_profile="orchestration")

    assert RaesParticipantRuntimeRecord.objects.count() == 0


@pytest.mark.django_db
def test_persist_participant_runtime_record_rejects_digest_mismatch_before_write():
    with pytest.raises(RaesParticipantRuntimeRecordError, match="payload_digest"):
        _persist(payload_digest="sha256:" + "f" * 64)

    assert RaesParticipantRuntimeRecord.objects.count() == 0


@pytest.mark.django_db
def test_persist_participant_runtime_record_rejects_secret_bearing_payload_before_write():
    with pytest.raises(RaesParticipantRuntimeRecordError, match="secret-bearing"):
        _persist(payload={"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1", "api_key": "x"})

    assert RaesParticipantRuntimeRecord.objects.count() == 0


@pytest.mark.django_db
def test_persist_participant_runtime_record_different_participants_do_not_collide():
    _persist(participant_ref="ctf-participant-1")
    _persist(participant_ref="ctf-participant-2")

    assert RaesParticipantRuntimeRecord.objects.count() == 2


def test_participant_runtime_record_model_uses_first_class_sidecar_table():
    assert RaesParticipantRuntimeRecord._meta.db_table == "shared_raes_participant_runtime_record"
    field_names = {field.name for field in RaesParticipantRuntimeRecord._meta.fields}

    assert {
        "request_id",
        "range_id",
        "range_instance_id",
        "participant_ref",
        "contract_kind",
        "contract_version",
        "contract_profile",
        "participant_runtime_profile",
        "record_kind",
        "idempotency_key",
        "source_timestamp",
        "payload_digest",
        "diagnostic_refs",
        "owner",
        "retention_class",
        "retention_expires_at",
        "redaction_state",
    } <= field_names


class TestTypedHelpers:
    @pytest.mark.django_db
    def test_persist_participant_implementation_record_builds_deterministic_key(self):
        payload = {"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1"}
        first = persist_participant_implementation_record(
            request_id=REQUEST_ID,
            participant_ref="ctf-participant-1",
            implementation_ref="impl-1",
            source_timestamp=SOURCE_TS,
            payload=payload,
        )
        second = persist_participant_implementation_record(
            request_id=REQUEST_ID,
            participant_ref="ctf-participant-1",
            implementation_ref="impl-1",
            source_timestamp=SOURCE_TS,
            payload=payload,
        )

        assert first.id == second.id
        assert first.record_kind == RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION
        assert first.owner == RaesParticipantRuntimeRecord.Owner.PROVISIONER

    @pytest.mark.django_db
    def test_persist_participant_runtime_record_builds_deterministic_key(self):
        payload = {"participant_ref": "ctf-participant-1", "status": "running"}
        first = persist_participant_runtime_record(
            request_id=REQUEST_ID,
            participant_ref="ctf-participant-1",
            source_timestamp=SOURCE_TS,
            payload=payload,
        )
        second = persist_participant_runtime_record(
            request_id=REQUEST_ID,
            participant_ref="ctf-participant-1",
            source_timestamp=SOURCE_TS,
            payload=payload,
        )

        assert first.id == second.id
        assert first.record_kind == RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME
        assert first.owner == RaesParticipantRuntimeRecord.Owner.ENGINE

    @pytest.mark.django_db
    def test_typed_helper_key_stays_within_column_for_long_refs(self):
        # A max-length participant_ref plus a long implementation_ref must not
        # produce an idempotency_key that overflows the 128-char column.
        long_participant = "p" * 256
        long_impl = "i" * 300
        row = persist_participant_implementation_record(
            request_id=REQUEST_ID,
            participant_ref=long_participant,
            implementation_ref=long_impl,
            source_timestamp=SOURCE_TS,
            payload={"participant_ref": long_participant, "implementation_ref": long_impl},
        )

        assert len(row.idempotency_key) <= 128
        assert row.idempotency_key.startswith("participant_implementation:")
        # Deterministic: identical inputs converge on the same row.
        again = persist_participant_implementation_record(
            request_id=REQUEST_ID,
            participant_ref=long_participant,
            implementation_ref=long_impl,
            source_timestamp=SOURCE_TS,
            payload={"participant_ref": long_participant, "implementation_ref": long_impl},
        )
        assert row.id == again.id
