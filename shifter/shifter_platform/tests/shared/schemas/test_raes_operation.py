"""Tests for RAES operation sidecar metadata validation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from shared.schemas.raes_operation import (
    RaesOperationRecordData,
    RaesOperationRecordError,
    canonical_raes_payload_digest,
    validate_raes_operation_record,
)

REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")
SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _record(**overrides):
    fields = {
        "request_id": REQUEST_ID,
        "operation_id": "op-12345678",
        "idempotency_key": "range-provisioned:event-1",
        "record_kind": "operation_receipt",
        "contract_kind": "raes",
        "contract_version": "operation-receipt-v1",
        "contract_profile": "provisioning-only",
        "source_timestamp": SOURCE_TS,
        "payload": {"operation_id": "op-12345678", "accepted": True},
        "diagnostic_refs": {"trace_ref": "traces/request-12345678"},
    }
    fields.update(overrides)
    fields.setdefault("payload_digest", canonical_raes_payload_digest(fields["payload"]))
    return RaesOperationRecordData(**fields)


@pytest.mark.parametrize(
    ("record_kind", "contract_version", "payload"),
    [
        ("operation_receipt", "operation-receipt-v1", {"operation_id": "op-1", "accepted": True}),
        ("operation_status", "operation-status-v1", {"operation_id": "op-1", "status": "running"}),
        (
            "runtime_snapshot",
            "runtime-snapshot-v1",
            {
                "operation_id": "op-1",
                "resources": [
                    {"address": "node.web", "resource_type": "node", "status": "provisioned"},
                    {
                        "address": "content.seed",
                        "resource_type": "content-placement",
                        "status": "verified",
                    },
                    {
                        "address": "provision.domain-controller.corp.dc",
                        "resource_type": "domain-controller-placement",
                        "status": "verified",
                    },
                ],
            },
        ),
        (
            "execution_plan_ref",
            "execution-plan-ref-v1",
            {"execution_plan_ref": "raes/plans/op-1.json", "execution_plan_digest": "sha256:" + "b" * 64},
        ),
    ],
)
def test_valid_supported_operation_records_pass(record_kind, contract_version, payload):
    result = validate_raes_operation_record(
        _record(record_kind=record_kind, contract_version=contract_version, payload=payload)
    )

    assert result.payload == payload
    assert result.diagnostic_refs == {"trace_ref": "traces/request-12345678"}


def test_unsupported_profile_rejected():
    record = _record(contract_profile="orchestration")
    with pytest.raises(RaesOperationRecordError, match="contract_profile"):
        validate_raes_operation_record(record)


def test_mismatched_record_kind_and_contract_version_rejected():
    record = _record(record_kind="operation_status", contract_version="runtime-snapshot-v1")
    with pytest.raises(RaesOperationRecordError, match="contract_version"):
        validate_raes_operation_record(record)


def test_payload_digest_must_match_canonical_payload():
    record = _record(payload_digest="sha256:" + "f" * 64)
    with pytest.raises(RaesOperationRecordError, match="payload_digest"):
        validate_raes_operation_record(record)


def test_secret_bearing_payload_key_rejected():
    record = _record(payload={"operation_id": "op-1", "access_token": "raw-token"})
    with pytest.raises(RaesOperationRecordError, match="secret-bearing"):
        validate_raes_operation_record(record)


def test_token_bearing_diagnostic_reference_rejected():
    record = _record(diagnostic_refs={"log_ref": "https://example.invalid/log?X-Amz-Signature=abc"})
    with pytest.raises(RaesOperationRecordError, match="secret-bearing"):
        validate_raes_operation_record(record)


def test_unknown_diagnostic_reference_key_rejected():
    record = _record(diagnostic_refs={"terraform_output": "s3://bucket/output"})
    with pytest.raises(RaesOperationRecordError, match="not an allowed"):
        validate_raes_operation_record(record)


def test_execution_plan_reference_rejects_embedded_plan_body():
    record = _record(
        record_kind="execution_plan_ref",
        contract_version="execution-plan-ref-v1",
        payload={"execution_plan_ref": "raes/plans/op-1.json", "step_refs": ["raes/plans/op-1.step-1.json"]},
    )
    with pytest.raises(RaesOperationRecordError, match="reference-only"):
        validate_raes_operation_record(record)


def _snapshot(resource: dict) -> RaesOperationRecordData:
    """Build a runtime_snapshot record whose single resource carries `resource`."""
    payload = {"operation_id": "op-1", "resources": [resource]}
    return _record(record_kind="runtime_snapshot", contract_version="runtime-snapshot-v1", payload=payload)


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "transcript",
        "prompt",
        "command",
        "generated_script",
        "ctf_flag",
        "package_body",
        "provider_dump",
        "raw_payload",
        "ssm_output",
        "ssh_output",
        "terraform_output",
        "bearer_token",
    ],
)
def test_runtime_snapshot_rejects_secret_bearing_nested_field(forbidden_key):
    # A snapshot must not become a store for transcripts/prompts/commands/
    # scripts/flags/provider dumps/package bodies even nested inside `resources`.
    record = _snapshot({"kind": "vm", forbidden_key: "should-not-persist"})
    with pytest.raises(RaesOperationRecordError, match="secret-bearing"):
        validate_raes_operation_record(record)


def test_runtime_snapshot_rejects_multiline_embedded_content():
    record = _snapshot({"kind": "vm", "detail": "line-1\nline-2"})
    with pytest.raises(RaesOperationRecordError, match="single-line"):
        validate_raes_operation_record(record)


def test_runtime_snapshot_rejects_private_key_material():
    # Assemble the PEM header at runtime so this test file does not itself trip
    # secret scanners (detect-private-key/gitleaks); the resolved value still
    # matches the write-boundary secret-value gate.
    pem_header = "-----BEGIN " + "RSA PRIVATE KEY-----"
    record = _snapshot({"kind": "vm", "note": pem_header})
    with pytest.raises(RaesOperationRecordError, match="secret-bearing"):
        validate_raes_operation_record(record)


def test_runtime_snapshot_rejects_oversized_payload():
    record = _snapshot({"kind": "vm", "note": "x" * 70000})
    with pytest.raises(RaesOperationRecordError, match="exceeds"):
        validate_raes_operation_record(record)


def test_runtime_snapshot_rejects_unknown_top_level_payload_key():
    payload = {"operation_id": "op-1", "resources": [{"kind": "vm"}], "captured_notes": "extra"}
    record = _record(record_kind="runtime_snapshot", contract_version="runtime-snapshot-v1", payload=payload)
    with pytest.raises(RaesOperationRecordError, match="not allowed"):
        validate_raes_operation_record(record)


@pytest.mark.parametrize(
    "resource",
    [
        {"address": "content.seed", "resource_type": "content-placement", "status": "provisioned"},
        {"address": "node.web", "resource_type": "node", "status": "verified"},
        {
            "address": "account.operator",
            "resource_type": "account-placement",
            "status": "verified",
            "username": "operator",
        },
        {"address": "feature.config", "resource_type": "unknown", "status": "verified"},
        {"address": 7, "resource_type": "node", "status": "provisioned"},
    ],
)
def test_runtime_snapshot_rejects_malformed_resource_contract(resource):
    record = _snapshot(resource)
    with pytest.raises(RaesOperationRecordError, match="runtime_snapshot resource"):
        validate_raes_operation_record(record)


def test_runtime_snapshot_rejects_duplicate_resource_addresses():
    resource = {"address": "content.seed", "resource_type": "content-placement", "status": "verified"}
    payload = {"operation_id": "op-1", "resources": [resource, dict(resource)]}
    record = _record(record_kind="runtime_snapshot", contract_version="runtime-snapshot-v1", payload=payload)
    with pytest.raises(RaesOperationRecordError, match="duplicate"):
        validate_raes_operation_record(record)
