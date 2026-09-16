"""Forward/reverse proof for the RAES model and physical-schema cutover."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [
    ("cms", "0040_workspace_binding_required"),
    ("engine", "0047_revoke_residual_grants_from_provisioner"),
    ("shared", "0007_capacity_notification_and_audit_choices"),
]
AFTER = [
    ("cms", "0041_raes_hard_cutover"),
    ("engine", "0048_raes_hard_cutover"),
    ("shared", "0009_raes_hard_cutover_cleanup"),
]
CUTOVER_SCHEMA = [
    ("cms", "0041_raes_hard_cutover"),
    ("engine", "0048_raes_hard_cutover"),
    ("shared", "0008_raes_hard_cutover"),
]

pytestmark = [pytest.mark.django_db(transaction=True)]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


@pytest.fixture
def historical():
    apps = _migrate(BEFORE)
    try:
        yield apps
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


def _seed_historical_rows(apps):
    user = apps.get_model("auth", "User").objects.create(username="raes-cutover")
    source = apps.get_model("cms", "AcesPackageSource").objects.create(
        scenario_id="historical-pack",
        source_kind="repo",
        contract_kind="aces",
        contract_profile="shifter",
        package_ref="historical/pack",
        package_version="1",
        package_digest=f"sha256:{'a' * 64}",
        conformance_status="passed",
        provenance={"tool": "aces", "tool_version": "0.25.0"},
        registered_by_id=user.pk,
    )
    mapping = apps.get_model("engine", "AcesImageMapping").objects.create(
        provider="aws",
        source_name="historical-image",
        image_ref="ami-0123456789abcdef0",
    )
    record = apps.get_model("shared", "AcesOperationRecord").objects.create(
        request_id=uuid4(),
        operation_id="historical-operation",
        idempotency_key="historical-operation",
        contract_kind="aces",
        contract_version="operation-status-v1",
        contract_profile="shifter",
        record_kind="operation_status",
        source_timestamp=datetime(2026, 7, 1, tzinfo=UTC),
        payload_digest=f"sha256:{'b' * 64}",
        payload={},
    )
    participant = apps.get_model("shared", "AcesParticipantRuntimeRecord").objects.create(
        request_id=uuid4(),
        participant_ref="historical-participant",
        idempotency_key="historical-participant",
        contract_kind="aces",
        contract_version="participant-implementation-v1",
        contract_profile="shifter",
        participant_runtime_profile="shifter-provisioning",
        record_kind="participant_implementation",
        source_timestamp=datetime(2026, 7, 1, tzinfo=UTC),
        payload_digest=f"sha256:{'c' * 64}",
        payload={},
    )

    request_id = uuid4()
    operation_id = uuid4()
    request = apps.get_model("engine", "Request").objects.create(
        request_id=request_id,
        request_type="range",
        user_id=user.pk,
    )
    plan = {
        "kind": "aces_provisioning_plan",
        "contract_version": "aces-provisioning-plan-v1",
        "aces_sdl_version": "0.25.0",
        "resources": {
            "provision.node.historical": {
                "resource_type": "node",
                "payload": {
                    "notes": "aces-range",
                    "authored": {"aces_sdl_version": "opaque authored value"},
                },
            }
        },
    }
    range_row = apps.get_model("engine", "Range").objects.create(
        user_id=user.pk,
        request_id=request.pk,
        workspace_id=1,
        status="destroyed",
        provisioner_operation="aces-range:provision",
        provisioner_operation_id=operation_id,
        range_config=plan,
    )
    instance = apps.get_model("engine", "Instance").objects.create(
        request_id=request.pk,
        status="destroyed",
        role="victim",
        os_type="ubuntu",
        provisioner_operation="aces-range:provision",
        provisioner_operation_id=operation_id,
    )
    launch = apps.get_model("engine", "ProvisionerLaunchIntent").objects.create(
        operation_id=operation_id,
        idempotency_key="historical-launch",
        payload={
            "version": 1,
            "resource": "aces-range",
            "operation": "provision",
            "request_id": str(request_id),
            "operation_id": str(operation_id),
        },
        status="SUCCEEDED",
        next_attempt_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    operation_input = apps.get_model("engine", "OperationInput").objects.create(
        operation_id=operation_id,
        request_id=request_id,
        resource="aces-range",
        operation="provision",
        contract_version="1",
        envelope={
            "contract_version": "1",
            "operation_id": str(operation_id),
            "request_id": str(request_id),
            "resource": "aces-range",
            "operation": "provision",
            "payload": {"plan": plan},
        },
    )

    result_ids = []
    result_steps = (
        ("aces_provision_running", "provision", {"aces_status": "running"}),
        ("aces_provision_snapshot", "provision", {"resources": []}),
        ("aces_destroy_running", "destroy", {"aces_status": "running"}),
        ("aces_terminal_ready", "provision", {"aces_status": "succeeded"}),
        ("aces_terminal_destroyed", "destroy", {"aces_status": "succeeded"}),
        ("aces_terminal_failed", "provision", {"reason_code": "internal_error", "diagnostic": ""}),
    )
    for step, operation, payload in result_steps:
        result_operation_id = uuid4()
        digest = _digest(payload)
        result = apps.get_model("engine", "OperationResultInbox").objects.create(
            operation_id=result_operation_id,
            request_id=request_id,
            resource="aces-range",
            operation=operation,
            contract_version="1",
            result_kind="RESOURCE_STATE",
            result_step=step,
            result_identity=f"{result_operation_id}:{step}:{digest}",
            payload_digest=digest,
            envelope={
                "contract_version": "1",
                "operation_id": str(result_operation_id),
                "request_id": str(request_id),
                "resource": "aces-range",
                "operation": operation,
                "payload": payload,
            },
            disposition="VALIDATED",
        )
        result_ids.append(result.pk)

    event_ids = []
    for event_type, payload in (
        ("range.aces.operation", {"event_type": "range.aces.operation", "aces_status": "running"}),
        ("range.aces.snapshot", {"event_type": "range.aces.snapshot", "resources": []}),
    ):
        event = apps.get_model("engine", "RangeEventOutbox").objects.create(
            event_id=uuid4(),
            event_type=event_type,
            payload=payload,
            status="PUBLISHED",
            next_attempt_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        event_ids.append(event.pk)

    return {
        "source": source.pk,
        "mapping": mapping.pk,
        "record": record.pk,
        "participant": participant.pk,
        "range": range_row.pk,
        "instance": instance.pk,
        "launch": launch.pk,
        "input": operation_input.pk,
        "results": result_ids,
        "events": event_ids,
    }


def _digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_forward_cutover_renames_schema_removes_retired_contract_rows_and_preserves_opaque_history(historical):
    rows = _seed_historical_rows(historical)

    apps = _migrate(AFTER)

    tables = set(connection.introspection.table_names())
    assert {
        "cms_raespackagesource",
        "engine_raes_image_mapping",
        "engine_raes_content_delivery_binding",
        "shared_raes_operation_record",
        "shared_raes_participant_runtime_record",
    } <= tables
    assert (
        not {
            "cms_acespackagesource",
            "engine_aces_image_mapping",
            "engine_aces_content_delivery_binding",
            "shared_aces_operation_record",
            "shared_aces_participant_runtime_record",
        }
        & tables
    )
    assert not apps.get_model("cms", "RaesPackageSource").objects.filter(pk=rows["source"]).exists()
    assert apps.get_model("engine", "RaesImageMapping").objects.filter(pk=rows["mapping"]).exists()
    assert not apps.get_model("shared", "RaesOperationRecord").objects.filter(pk=rows["record"]).exists()
    assert not apps.get_model("shared", "RaesParticipantRuntimeRecord").objects.filter(pk=rows["participant"]).exists()

    range_row = apps.get_model("engine", "Range").objects.get(pk=rows["range"])
    assert range_row.provisioner_operation == "aces-range:provision"
    assert range_row.range_config == {
        "kind": "aces_provisioning_plan",
        "contract_version": "aces-provisioning-plan-v1",
        "aces_sdl_version": "0.25.0",
        "resources": {
            "provision.node.historical": {
                "resource_type": "node",
                "payload": {
                    "notes": "aces-range",
                    "authored": {"aces_sdl_version": "opaque authored value"},
                },
            }
        },
    }
    launch = apps.get_model("engine", "ProvisionerLaunchIntent").objects.get(pk=rows["launch"])
    assert launch.payload["resource"] == "aces-range"
    operation_input = apps.get_model("engine", "OperationInput").objects.get(pk=rows["input"])
    assert operation_input.resource == "aces-range"
    assert operation_input.envelope["resource"] == "aces-range"
    assert operation_input.envelope["payload"]["plan"] == range_row.range_config

    expected_steps = {
        "aces_provision_running",
        "aces_provision_snapshot",
        "aces_destroy_running",
        "aces_terminal_ready",
        "aces_terminal_destroyed",
        "aces_terminal_failed",
    }
    results = list(apps.get_model("engine", "OperationResultInbox").objects.filter(pk__in=rows["results"]))
    assert {result.resource for result in results} == {"aces-range"}
    assert {result.envelope["resource"] for result in results} == {"aces-range"}
    assert {result.result_step for result in results} == expected_steps
    for result in results:
        assert "raes_status" not in result.envelope["payload"]
        assert result.payload_digest == _digest(result.envelope["payload"])
        assert result.result_identity == f"{result.operation_id}:{result.result_step}:{result.payload_digest}"

    events = list(apps.get_model("engine", "RangeEventOutbox").objects.filter(pk__in=rows["events"]))
    assert {event.event_type for event in events} == {"range.aces.operation", "range.aces.snapshot"}
    assert {event.payload["event_type"] for event in events} == {"range.aces.operation", "range.aces.snapshot"}
    assert all("raes_status" not in event.payload for event in events)


def test_reverse_cutover_restores_historical_models_and_tables(historical):
    rows = _seed_historical_rows(historical)
    _migrate(AFTER)

    apps = _migrate(BEFORE)

    assert not apps.get_model("cms", "AcesPackageSource").objects.filter(pk=rows["source"]).exists()
    assert apps.get_model("engine", "AcesImageMapping").objects.filter(pk=rows["mapping"]).exists()
    assert not apps.get_model("shared", "AcesOperationRecord").objects.filter(pk=rows["record"]).exists()
    assert not apps.get_model("shared", "AcesParticipantRuntimeRecord").objects.filter(pk=rows["participant"]).exists()

    range_row = apps.get_model("engine", "Range").objects.get(pk=rows["range"])
    assert range_row.provisioner_operation == "aces-range:provision"
    assert range_row.range_config == {
        "kind": "aces_provisioning_plan",
        "contract_version": "aces-provisioning-plan-v1",
        "aces_sdl_version": "0.25.0",
        "resources": {
            "provision.node.historical": {
                "resource_type": "node",
                "payload": {
                    "notes": "aces-range",
                    "authored": {"aces_sdl_version": "opaque authored value"},
                },
            }
        },
    }
    launch = apps.get_model("engine", "ProvisionerLaunchIntent").objects.get(pk=rows["launch"])
    assert launch.payload["resource"] == "aces-range"
    operation_input = apps.get_model("engine", "OperationInput").objects.get(pk=rows["input"])
    assert operation_input.resource == "aces-range"
    assert operation_input.envelope["resource"] == "aces-range"
    assert operation_input.envelope["payload"]["plan"] == range_row.range_config

    expected_steps = {
        "aces_provision_running",
        "aces_provision_snapshot",
        "aces_destroy_running",
        "aces_terminal_ready",
        "aces_terminal_destroyed",
        "aces_terminal_failed",
    }
    results = list(apps.get_model("engine", "OperationResultInbox").objects.filter(pk__in=rows["results"]))
    assert {result.resource for result in results} == {"aces-range"}
    assert {result.envelope["resource"] for result in results} == {"aces-range"}
    assert {result.result_step for result in results} == expected_steps
    for result in results:
        assert "raes_status" not in result.envelope["payload"]
        assert result.payload_digest == _digest(result.envelope["payload"])
        assert result.result_identity == f"{result.operation_id}:{result.result_step}:{result.payload_digest}"

    events = list(apps.get_model("engine", "RangeEventOutbox").objects.filter(pk__in=rows["events"]))
    assert {event.event_type for event in events} == {"range.aces.operation", "range.aces.snapshot"}
    assert {event.payload["event_type"] for event in events} == {"range.aces.operation", "range.aces.snapshot"}
    assert all("raes_status" not in event.payload for event in events)


def test_cutover_refuses_undrained_retired_work(historical):
    rows = _seed_historical_rows(historical)
    historical.get_model("engine", "Range").objects.filter(pk=rows["range"]).update(status="provisioning")
    historical.get_model("engine", "Instance").objects.filter(pk=rows["instance"]).update(status="provisioning")
    historical.get_model("engine", "ProvisionerLaunchIntent").objects.filter(pk=rows["launch"]).update(status="PENDING")
    historical.get_model("engine", "OperationResultInbox").objects.filter(pk=rows["results"][0]).update(
        disposition="PENDING"
    )
    historical.get_model("engine", "RangeEventOutbox").objects.filter(pk=rows["events"][0]).update(status="PENDING")

    with pytest.raises(RuntimeError, match="requires all retired provisioning work to be drained"):
        _migrate(AFTER)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    apps = executor.loader.project_state(CUTOVER_SCHEMA).apps
    assert apps.get_model("cms", "RaesPackageSource").objects.filter(pk=rows["source"]).exists()
    assert apps.get_model("shared", "RaesOperationRecord").objects.filter(pk=rows["record"]).exists()
    assert apps.get_model("shared", "RaesParticipantRuntimeRecord").objects.filter(pk=rows["participant"]).exists()

    historical.get_model("engine", "Range").objects.filter(pk=rows["range"]).update(status="destroyed")
    historical.get_model("engine", "Instance").objects.filter(pk=rows["instance"]).update(status="destroyed")
    historical.get_model("engine", "ProvisionerLaunchIntent").objects.filter(pk=rows["launch"]).update(
        status="SUCCEEDED"
    )
    historical.get_model("engine", "OperationResultInbox").objects.filter(pk=rows["results"][0]).update(
        disposition="VALIDATED"
    )
    historical.get_model("engine", "RangeEventOutbox").objects.filter(pk=rows["events"][0]).update(status="PUBLISHED")
