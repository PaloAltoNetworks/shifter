"""Validation tests for ACES participant behavior-history and evidence records (#1289).

These two reference record kinds extend the #1288 participant-runtime sidecar
family. They are append/reference oriented: they cite scripts, prompts, dispatch
receipts, transcripts, artifacts, and behavior events by storage ref + digest,
and the shared validators reject every prohibited payload class named by the
issue (presigned URLs, upload/Guacamole tokens, SSH keys, RDP passwords, CTF
flags, terminal streams, rendered commands, prompt/script/transcript bodies, and
provider diagnostics).
"""

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

_EVIDENCE_PAYLOAD = {
    "participant_ref": "ctf-participant-1",
    "evidence_kind": "artifact_ref",
    "capture_profile": "reference_only",
    "provenance_source": "object_storage",
    "provenance_ref": "range-artifacts/participant-1/output.bin",
    "artifact_ref": "range-artifacts/participant-1/output.bin",
    "artifact_digest": "sha256:" + "a" * 64,
    "redaction_policy": "reference_only",
}

_HISTORY_PAYLOAD = {
    "participant_ref": "ctf-participant-1",
    "event_kind": "command_dispatched",
    "event_ref": "range-event-9f2c",
    "event_digest": "sha256:" + "b" * 64,
    "sequence": 3,
}


def _evidence(*, payload=None, **overrides):
    fields = {
        "request_id": REQUEST_ID,
        "participant_ref": "ctf-participant-1",
        "idempotency_key": "participant_evidence:ctf-participant-1:artifact_ref",
        "record_kind": "participant_evidence",
        "contract_kind": "aces",
        "contract_version": "participant-evidence-v1",
        "contract_profile": "provisioning-only",
        "participant_runtime_profile": "shifter-provisioning",
        "source_timestamp": SOURCE_TS,
        "payload": dict(_EVIDENCE_PAYLOAD) if payload is None else payload,
        "diagnostic_refs": {},
    }
    fields.update(overrides)
    fields.setdefault("payload_digest", canonical_aces_payload_digest(fields["payload"]))
    return AcesParticipantRuntimeRecordData(**fields)


def _history(*, payload=None, **overrides):
    fields = {
        "request_id": REQUEST_ID,
        "participant_ref": "ctf-participant-1",
        "idempotency_key": "participant_behavior_history:ctf-participant-1:range-event-9f2c",
        "record_kind": "participant_behavior_history",
        "contract_kind": "aces",
        "contract_version": "participant-behavior-history-v1",
        "contract_profile": "provisioning-only",
        "participant_runtime_profile": "shifter-provisioning",
        "source_timestamp": SOURCE_TS,
        "payload": dict(_HISTORY_PAYLOAD) if payload is None else payload,
        "diagnostic_refs": {},
    }
    fields.update(overrides)
    fields.setdefault("payload_digest", canonical_aces_payload_digest(fields["payload"]))
    return AcesParticipantRuntimeRecordData(**fields)


# --- valid records -----------------------------------------------------------


def test_valid_evidence_record_passes():
    result = validate_aces_participant_runtime_record(_evidence())
    assert result.payload == _EVIDENCE_PAYLOAD
    assert result.diagnostic_refs == {}


def test_valid_behavior_history_record_passes():
    result = validate_aces_participant_runtime_record(_history())
    assert result.payload == _HISTORY_PAYLOAD


def test_evidence_operation_reference_fields_pass():
    payload = {
        "participant_ref": "ctf-participant-1",
        "evidence_kind": "dispatch_receipt",
        "capture_profile": "digest_only",
        "provenance_source": "operation_sidecar",
        "provenance_ref": "operation-record-1",
        "redaction_policy": "reference_only",
        "operation_id": "op-42",
        "operation_record_id": "b1c9e0f2-1111-2222-3333-444455556666",
        "receipt_ref": "operation-receipt-42",
    }
    result = validate_aces_participant_runtime_record(_evidence(payload=payload))
    assert result.payload["evidence_kind"] == "dispatch_receipt"


# --- contract / record-kind pairing -----------------------------------------


def test_evidence_record_kind_requires_evidence_contract_version():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="contract_version"):
        validate_aces_participant_runtime_record(_evidence(contract_version="participant-runtime-v1"))


def test_history_record_kind_requires_history_contract_version():
    with pytest.raises(AcesParticipantRuntimeRecordError, match="contract_version"):
        validate_aces_participant_runtime_record(_history(contract_version="participant-evidence-v1"))


# --- required fields ---------------------------------------------------------


@pytest.mark.parametrize("missing", ["evidence_kind", "capture_profile", "provenance_source", "redaction_policy"])
def test_evidence_missing_required_field_rejected(missing):
    payload = {k: v for k, v in _EVIDENCE_PAYLOAD.items() if k != missing}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="required"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


@pytest.mark.parametrize("missing", ["event_kind", "event_ref"])
def test_history_missing_required_field_rejected(missing):
    payload = {k: v for k, v in _HISTORY_PAYLOAD.items() if k != missing}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="required"):
        validate_aces_participant_runtime_record(_history(payload=payload))


# --- vocabulary validation ---------------------------------------------------


def test_unsupported_evidence_kind_rejected():
    payload = {**_EVIDENCE_PAYLOAD, "evidence_kind": "raw_dump"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="evidence_kind"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


def test_unsupported_capture_profile_rejected():
    payload = {**_EVIDENCE_PAYLOAD, "capture_profile": "full_copy"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="capture_profile"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


def test_unsupported_provenance_source_rejected():
    payload = {**_EVIDENCE_PAYLOAD, "provenance_source": "unknown_service"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="provenance_source"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


def test_unsupported_redaction_policy_rejected():
    payload = {**_EVIDENCE_PAYLOAD, "redaction_policy": "store_raw"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="redaction_policy"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


def test_unsupported_behavior_event_kind_rejected():
    payload = {**_HISTORY_PAYLOAD, "event_kind": "exfiltrate"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="event_kind"):
        validate_aces_participant_runtime_record(_history(payload=payload))


def test_malformed_artifact_digest_rejected():
    payload = {**_EVIDENCE_PAYLOAD, "artifact_digest": "not-a-digest"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="artifact_digest"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


def test_malformed_event_digest_rejected():
    payload = {**_HISTORY_PAYLOAD, "event_digest": "deadbeef"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="event_digest"):
        validate_aces_participant_runtime_record(_history(payload=payload))


def test_negative_sequence_rejected():
    payload = {**_HISTORY_PAYLOAD, "sequence": -1}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="sequence"):
        validate_aces_participant_runtime_record(_history(payload=payload))


def test_non_integer_sequence_rejected():
    payload = {**_HISTORY_PAYLOAD, "sequence": "3"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="sequence"):
        validate_aces_participant_runtime_record(_history(payload=payload))


def test_evidence_rejects_unallowed_key():
    payload = {**_EVIDENCE_PAYLOAD, "notes": "extra"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="not allowed"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


# --- bounded-ref validation on allowed ref fields (issue #1289 codex review) --


def test_empty_provenance_ref_rejected():
    payload = {**_EVIDENCE_PAYLOAD, "provenance_ref": "   "}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="provenance_ref"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


def test_overlong_provenance_ref_rejected():
    payload = {**_EVIDENCE_PAYLOAD, "provenance_ref": "r" * 513}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="provenance_ref"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


def test_empty_event_ref_rejected():
    payload = {**_HISTORY_PAYLOAD, "event_ref": ""}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="event_ref"):
        validate_aces_participant_runtime_record(_history(payload=payload))


def test_body_shaped_value_in_allowed_ref_field_rejected():
    # A prohibited body (multi-line transcript) placed in an ALLOWED ref field
    # must still be rejected, not only when placed under a disallowed key.
    payload = {**_EVIDENCE_PAYLOAD, "provenance_ref": "user: hi\nassistant: hello"}
    with pytest.raises(AcesParticipantRuntimeRecordError, match="single-line"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


# --- digest pinning for mutable external material -----------------------------


@pytest.mark.parametrize(
    "evidence_kind", ["script_input", "prompt_input", "transcript_ref", "artifact_ref", "terminal_session_ref"]
)
def test_mutable_evidence_kind_requires_artifact_digest(evidence_kind):
    payload = {k: v for k, v in _EVIDENCE_PAYLOAD.items() if k != "artifact_digest"}
    payload["evidence_kind"] = evidence_kind
    with pytest.raises(AcesParticipantRuntimeRecordError, match="artifact_digest is required"):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


@pytest.mark.parametrize("evidence_kind", ["dispatch_receipt", "manual_evidence"])
def test_non_mutable_evidence_kind_does_not_require_digest(evidence_kind):
    payload = {
        "participant_ref": "ctf-participant-1",
        "evidence_kind": evidence_kind,
        "capture_profile": "reference_only",
        "provenance_source": "operation_sidecar",
        "provenance_ref": "operation-record-1",
        "redaction_policy": "reference_only",
    }
    result = validate_aces_participant_runtime_record(_evidence(payload=payload))
    assert result.payload["evidence_kind"] == evidence_kind


# --- prohibited payload class regression (issue #1289 acceptance) ------------

# Each case is a payload fragment merged into a valid evidence record; every
# prohibited class named by the issue must be rejected before persistence.
PROHIBITED_PAYLOAD_CASES = [
    ("presigned_url", {"artifact_ref": "https://b.s3.amazonaws.com/k?X-Amz-Signature=deadbeefdeadbeef"}),
    ("upload_token", {"upload_token": "tok-abc123"}),
    ("guacamole_token_url", {"guacamole_token": "https://guac.example/#/client/xyz"}),
    ("ssh_private_key", {"provenance_ref": "-----BEGIN OPENSSH PRIVATE " + "KEY-----"}),
    ("rdp_password", {"rdp_password": "hunter2"}),
    ("ctf_flag", {"ctf_flag": "flag{p0wn3d}"}),
    ("terminal_stream", {"provenance_ref": "stdout-line-1\nstdout-line-2"}),
    ("rendered_command", {"rendered_command": "rm -rf /tmp/x"}),
    ("prompt_body", {"prompt_body": "You are a helpful assistant that ..."}),
    ("script_body", {"script_body": "import os"}),
    ("transcript_body", {"transcript_body": "user says hello"}),
    ("provider_diagnostics", {"provider_dump": "raw provider response json"}),
]


@pytest.mark.parametrize(
    "fragment", [case for _, case in PROHIBITED_PAYLOAD_CASES], ids=[name for name, _ in PROHIBITED_PAYLOAD_CASES]
)
def test_prohibited_payload_class_rejected(fragment):
    payload = {**_EVIDENCE_PAYLOAD, **fragment}
    with pytest.raises(AcesParticipantRuntimeRecordError):
        validate_aces_participant_runtime_record(_evidence(payload=payload))


@pytest.mark.parametrize(
    "fragment", [case for _, case in PROHIBITED_PAYLOAD_CASES], ids=[name for name, _ in PROHIBITED_PAYLOAD_CASES]
)
def test_prohibited_payload_class_rejected_in_behavior_history(fragment):
    payload = {**_HISTORY_PAYLOAD, **fragment}
    with pytest.raises(AcesParticipantRuntimeRecordError):
        validate_aces_participant_runtime_record(_history(payload=payload))
