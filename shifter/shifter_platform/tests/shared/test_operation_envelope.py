"""Contract tests for the provisioner operation transport envelope (#1834)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from shared.operation_envelope import (
    ACCEPTED_CONTRACT_VERSIONS,
    CONTRACT_VERSION,
    MAX_ENVELOPE_BYTES,
    OperationEnvelopeError,
    build_operation_envelope,
    canonical_payload_digest,
    validate_operation_envelope,
)

OID = str(uuid4())
RID = str(uuid4())


def _valid(**overrides):
    base = {
        "contract_version": CONTRACT_VERSION,
        "operation_id": OID,
        "request_id": RID,
        "resource": "range",
        "operation": "provision",
        "payload": {"spec": "x"},
    }
    base.update(overrides)
    return base


class TestValidateOperationEnvelope:
    def test_round_trips_a_valid_envelope(self):
        env = validate_operation_envelope(_valid())
        assert env == _valid()
        assert CONTRACT_VERSION in ACCEPTED_CONTRACT_VERSIONS

    def test_build_helper_normalizes_uuid_objects(self):
        env = build_operation_envelope(
            operation_id=uuid4(), request_id=uuid4(), resource="ngfw", operation="deprovision", payload={}
        )
        assert env["resource"] == "ngfw"
        assert env["operation"] == "deprovision"

    def test_rejects_unexpected_key(self):
        candidate = {**_valid(), "extra": 1}
        with pytest.raises(OperationEnvelopeError, match="unexpected"):
            validate_operation_envelope(candidate)

    def test_rejects_missing_key(self):
        bad = _valid()
        del bad["payload"]
        with pytest.raises(OperationEnvelopeError, match="missing"):
            validate_operation_envelope(bad)

    @pytest.mark.parametrize("field", ["operation_id", "request_id"])
    def test_rejects_non_uuid_correlation(self, field):
        candidate = _valid(**{field: "not-a-uuid"})
        with pytest.raises(OperationEnvelopeError, match="UUID"):
            validate_operation_envelope(candidate)

    def test_rejects_unknown_resource(self):
        candidate = _valid(resource="database")
        with pytest.raises(OperationEnvelopeError, match="resource"):
            validate_operation_envelope(candidate)

    def test_rejects_unknown_operation(self):
        candidate = _valid(operation="exec")
        with pytest.raises(OperationEnvelopeError, match="operation"):
            validate_operation_envelope(candidate)

    def test_rejects_unknown_contract_version(self):
        candidate = _valid(contract_version="999")
        with pytest.raises(OperationEnvelopeError, match="contract_version"):
            validate_operation_envelope(candidate)

    def test_rejects_non_object_payload(self):
        candidate = _valid(payload=["not", "an", "object"])
        with pytest.raises(OperationEnvelopeError, match="payload"):
            validate_operation_envelope(candidate)

    def test_rejects_oversized_envelope(self):
        candidate = _valid(payload={"blob": "x" * (MAX_ENVELOPE_BYTES + 1)})
        with pytest.raises(OperationEnvelopeError, match="exceeds"):
            validate_operation_envelope(candidate)


class TestCanonicalPayloadDigest:
    def test_is_order_independent(self):
        assert canonical_payload_digest({"a": 1, "b": 2}) == canonical_payload_digest({"b": 2, "a": 1})

    def test_changes_with_content(self):
        assert canonical_payload_digest({"a": 1}) != canonical_payload_digest({"a": 2})

    def test_is_sha256_prefixed(self):
        digest = canonical_payload_digest({"a": 1})
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64
