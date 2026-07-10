"""Tests for ACES participant-runtime sidecar metadata validation (#1288)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from shared.schemas.aces_participant_runtime import (
    AcesParticipantRuntimeRecordData,
    AcesParticipantRuntimeRecordError,
    canonical_aces_payload_digest,
    validate_aces_participant_runtime_record,
)

REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")
SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _record(**overrides):
    fields = {
        "request_id": REQUEST_ID,
        "participant_ref": "ctf-participant-1",
        "idempotency_key": "participant_implementation:ctf-participant-1:impl-1",
        "record_kind": "participant_implementation",
        "contract_kind": "aces",
        "contract_version": "participant-implementation-v1",
        "contract_profile": "provisioning-only",
        "participant_runtime_profile": "shifter-provisioning",
        "source_timestamp": SOURCE_TS,
        "payload": {"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1"},
        "diagnostic_refs": {},
    }
    fields.update(overrides)
    fields.setdefault("payload_digest", canonical_aces_payload_digest(fields["payload"]))
    return AcesParticipantRuntimeRecordData(**fields)


@pytest.mark.parametrize(
    ("record_kind", "contract_version", "payload"),
    [
        (
            "participant_implementation",
            "participant-implementation-v1",
            {"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1"},
        ),
        (
            "participant_runtime",
            "participant-runtime-v1",
            {"participant_ref": "ctf-participant-1", "status": "running"},
        ),
    ],
)
def test_valid_supported_participant_runtime_records_pass(record_kind, contract_version, payload):
    result = validate_aces_participant_runtime_record(
        _record(record_kind=record_kind, contract_version=contract_version, payload=payload)
    )

    assert result.payload == payload
    assert result.diagnostic_refs == {}


def test_unsupported_contract_kind_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="contract_kind"):
        validate_aces_participant_runtime_record(_record(contract_kind="cyberscript"))


def test_unsupported_contract_profile_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="contract_profile"):
        validate_aces_participant_runtime_record(_record(contract_profile="orchestration"))


def test_unsupported_participant_runtime_profile_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="participant_runtime_profile"):
        validate_aces_participant_runtime_record(_record(participant_runtime_profile="gcp-provisioning"))


def test_mismatched_record_kind_and_contract_version_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="contract_version"):
        validate_aces_participant_runtime_record(
            _record(record_kind="participant_runtime", contract_version="participant-implementation-v1")
        )


def test_unknown_record_kind_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="record_kind must be one of"):
        validate_aces_participant_runtime_record(
            _record(record_kind="participant_access_channel", contract_version="participant-implementation-v1")
        )


def test_unsupported_owner_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="owner"):
        validate_aces_participant_runtime_record(_record(owner="engine-legacy"))


def test_owner_ctf_is_supported():
    result = validate_aces_participant_runtime_record(_record(owner="ctf"))
    assert result.payload["participant_ref"] == "ctf-participant-1"


def test_unsupported_retention_class_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="retention_class"):
        validate_aces_participant_runtime_record(_record(retention_class="extended"))


def test_unsupported_redaction_state_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="redaction_state"):
        validate_aces_participant_runtime_record(_record(redaction_state="raw"))


def test_participant_ref_is_required():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="participant_ref"):
        validate_aces_participant_runtime_record(_record(participant_ref=""))


def test_participant_ref_must_be_single_line():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="single-line"):
        validate_aces_participant_runtime_record(_record(participant_ref="ctf-participant-1\nmalicious"))


def test_naive_source_timestamp_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="timezone-aware"):
        validate_aces_participant_runtime_record(_record(source_timestamp=datetime(2026, 7, 5, 3, 0)))


def test_payload_digest_must_match_canonical_payload():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="payload_digest"):
        validate_aces_participant_runtime_record(_record(payload_digest="sha256:" + "f" * 64))


def test_implementation_payload_requires_implementation_ref():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="required"):
        validate_aces_participant_runtime_record(_record(payload={"participant_ref": "ctf-participant-1"}))


def test_runtime_payload_requires_status():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="required"):
        validate_aces_participant_runtime_record(
            _record(
                record_kind="participant_runtime",
                contract_version="participant-runtime-v1",
                payload={"participant_ref": "ctf-participant-1"},
            )
        )


def test_implementation_payload_rejects_unallowed_keys():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="not allowed"):
        validate_aces_participant_runtime_record(
            _record(
                payload={"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1", "unexpected_key": "x"}
            )
        )


def test_runtime_payload_rejects_unallowed_keys():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="not allowed"):
        validate_aces_participant_runtime_record(
            _record(
                record_kind="participant_runtime",
                contract_version="participant-runtime-v1",
                payload={"participant_ref": "ctf-participant-1", "status": "running", "unexpected_key": "x"},
            )
        )


def test_secret_bearing_payload_key_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="secret-bearing"):
        validate_aces_participant_runtime_record(
            _record(payload={"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1", "api_key": "x"})
        )


def test_secret_bearing_payload_value_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="secret-bearing"):
        validate_aces_participant_runtime_record(
            _record(
                payload={
                    "participant_ref": "ctf-participant-1",
                    # Assembled at runtime so the repo's detect-private-key hook does
                    # not flag this deliberate secret-rejection fixture; the joined
                    # value still matches the validator's private-key pattern.
                    "implementation_ref": "-----BEGIN RSA PRIVATE " + "KEY-----",
                }
            )
        )


def test_non_allowlisted_diagnostic_ref_key_rejected():
    # ``diagnostic_refs`` is reference-only: keys outside the shared allowlist
    # (including secret-shaped names like ``api_key``) are rejected, matching the
    # incumbent operation-record contract rather than accepting arbitrary JSON.
    with pytest.raises(AcesParticipantRuntimeRecordError, match="not an allowed reference key"):
        validate_aces_participant_runtime_record(_record(diagnostic_refs={"api_key": "x"}))


def test_arbitrary_nested_diagnostic_ref_rejected():
    # A non-allowlisted key carrying nested JSON must not be persisted verbatim.
    with pytest.raises(AcesParticipantRuntimeRecordError, match="not an allowed reference key"):
        validate_aces_participant_runtime_record(_record(diagnostic_refs={"details": {"nested": "value"}}))


def test_allowlisted_diagnostic_refs_pass():
    result = validate_aces_participant_runtime_record(
        _record(diagnostic_refs={"trace_ref": "trace-1", "error_class": "TimeoutError"})
    )
    assert result.diagnostic_refs == {"trace_ref": "trace-1", "error_class": "TimeoutError"}


def test_secret_bearing_diagnostic_ref_value_rejected():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="secret-bearing"):
        validate_aces_participant_runtime_record(_record(diagnostic_refs={"trace_ref": "bearer abc123"}))


def test_participant_ref_exceeding_column_length_rejected():
    # participant_ref is validated against the 256-char storage column so an
    # over-length value fails validation instead of the database.
    with pytest.raises(AcesParticipantRuntimeRecordError, match="participant_ref exceeds 256"):
        validate_aces_participant_runtime_record(_record(participant_ref="p" * 257))


def test_idempotency_key_exceeding_column_length_rejected():
    # idempotency_key is validated against its 128-char storage column.
    with pytest.raises(AcesParticipantRuntimeRecordError, match="idempotency_key exceeds 128"):
        validate_aces_participant_runtime_record(_record(idempotency_key="k" * 129))
