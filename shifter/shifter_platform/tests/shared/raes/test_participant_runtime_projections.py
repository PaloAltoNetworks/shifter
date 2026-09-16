"""Tests for the RAES participant-runtime read-projection seam (#1288).

Drives real ``RaesParticipantRuntimeRecord`` rows through
``list_participant_runtime_records`` and asserts the response allowlist
(redaction), ordering, bounds, and participant-ref filtering. Rows are
persisted through the model's own validating ``save()`` (valid canonical
payloads); the redaction test uses a payload key that is valid to persist but
excluded from the API response allowlist (``request_id`` inside the payload),
proving the read seam strips persisted-but-not-returned keys -- same pattern
as ``tests/shared/raes/test_projections.py`` for operation records.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from shared.models import RaesParticipantRuntimeRecord
from shared.raes.contracts import SHIFTER_BACKEND_PROFILE
from shared.raes.participant_runtime_projections import (
    RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND,
    list_participant_runtime_records,
)
from shared.raes.projections import DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT
from shared.schemas.raes_participant_runtime import canonical_raes_payload_digest

pytestmark = pytest.mark.django_db

_CONTRACT_VERSION = {
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION: "participant-implementation-v1",
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME: "participant-runtime-v1",
}


def _record(request_id, *, participant_ref, record_kind, payload, source_timestamp):
    """Persist one valid sidecar row through the model's validating save()."""
    return RaesParticipantRuntimeRecord.objects.create(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=f"{record_kind}:{participant_ref}:{source_timestamp.isoformat()}",
        contract_kind=RaesParticipantRuntimeRecord.ContractKind.RAES,
        contract_version=_CONTRACT_VERSION[record_kind],
        contract_profile=SHIFTER_BACKEND_PROFILE,
        participant_runtime_profile="shifter-provisioning",
        record_kind=record_kind,
        source_timestamp=source_timestamp,
        payload_digest=canonical_raes_payload_digest(payload),
        payload=payload,
    )


def _runtime_payload(status="running", **extra):
    return {"participant_ref": "ctf-participant-1", "status": status, **extra}


class TestListParticipantRuntimeRecords:
    def test_redacts_persisted_but_non_response_keys(self):
        request_id = uuid4()
        # ``request_id`` is a valid persisted participant_runtime payload key,
        # but it is NOT in the API response allowlist, so it must be stripped.
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=timezone.now(),
            payload=_runtime_payload(status_reason="provisioning subnet", request_id=str(request_id)),
        )
        [proj] = list_participant_runtime_records(
            request_id, RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME
        )
        assert set(proj.payload) == {"participant_ref", "status", "status_reason"}
        assert "request_id" not in proj.payload

    def test_response_allowlist_is_a_subset_of_persisted_allowlist(self):
        from shared.schemas.raes_participant_runtime import PAYLOAD_KEYS_BY_RECORD_KIND

        for record_kind, response_keys in RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND.items():
            assert response_keys <= PAYLOAD_KEYS_BY_RECORD_KIND[record_kind]
            assert "request_id" not in response_keys

    def test_orders_newest_first(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now - timedelta(minutes=5),
            payload=_runtime_payload(status="accepted"),
        )
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now,
            payload=_runtime_payload(status="running"),
        )
        projections = list_participant_runtime_records(
            request_id, RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME
        )
        assert [p.payload["status"] for p in projections] == ["running", "accepted"]

    def test_limit_is_clamped_to_max(self):
        request_id = uuid4()
        now = timezone.now()
        for i in range(MAX_HISTORY_LIMIT + 5):
            _record(
                request_id,
                participant_ref="ctf-participant-1",
                record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
                source_timestamp=now - timedelta(seconds=i),
                payload=_runtime_payload(),
            )
        results = list_participant_runtime_records(
            request_id, RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME, limit=10_000
        )
        assert len(results) == MAX_HISTORY_LIMIT

    def test_default_limit_applied(self):
        request_id = uuid4()
        now = timezone.now()
        for i in range(DEFAULT_HISTORY_LIMIT + 5):
            _record(
                request_id,
                participant_ref="ctf-participant-1",
                record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
                source_timestamp=now - timedelta(seconds=i),
                payload=_runtime_payload(),
            )
        results = list_participant_runtime_records(
            request_id, RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME
        )
        assert len(results) == DEFAULT_HISTORY_LIMIT

    def test_filters_by_record_kind_and_request_id(self):
        request_id = uuid4()
        other_request = uuid4()
        now = timezone.now()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now,
            payload=_runtime_payload(),
        )
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION,
            source_timestamp=now,
            payload={"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1"},
        )
        _record(
            other_request,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now,
            payload=_runtime_payload(),
        )
        results = list_participant_runtime_records(
            request_id, RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME
        )
        assert len(results) == 1
        assert results[0].request_id == request_id

    def test_filters_by_participant_ref(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now,
            payload=_runtime_payload(),
        )
        _record(
            request_id,
            participant_ref="ctf-participant-2",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now,
            payload={"participant_ref": "ctf-participant-2", "status": "running"},
        )
        results = list_participant_runtime_records(
            request_id,
            RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            participant_ref="ctf-participant-2",
        )
        assert len(results) == 1
        assert results[0].participant_ref == "ctf-participant-2"

    def test_filters_by_contract_profile(self):
        request_id = uuid4()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=timezone.now(),
            payload=_runtime_payload(),
        )
        assert (
            list_participant_runtime_records(
                request_id,
                RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
                contract_profile="some-other-profile",
            )
            == []
        )

    def test_empty_when_no_rows(self):
        assert (
            list_participant_runtime_records(uuid4(), RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME) == []
        )

    def test_unknown_record_kind_raises(self):
        request_id = uuid4()
        with pytest.raises(ValueError, match="record_kind must be one of"):
            list_participant_runtime_records(request_id, "participant_access_channel")
