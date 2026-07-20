"""Tests for handle_sd_replacement.py.

Run via the package's uv environment from the repo root:
    cd scripts/handle_sd_replacement && uv run pytest tests/ -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handle_sd_replacement import (
    _SD_SUFFIX_TO_OUTPUT_KEY,
    _address_suffix,
    _detect_sd_deletions,
    drain,
    restore,
)

# ---------------------------------------------------------------------------
# Test helpers — shared, not inline, to avoid OOM from hundreds of mock objects
# ---------------------------------------------------------------------------


def _plan_json(resource_changes: list[dict]) -> dict:
    """Build a minimal terraform show -json payload."""
    return {"resource_changes": resource_changes}


def _sd_change(
    address: str = "module.guacamole.aws_service_discovery_service.guacd",
    actions: list[str] | None = None,
    sd_service_id: str = "srv-abc123",
    resource_type: str = "aws_service_discovery_service",
) -> dict:
    """Build one resource_change entry for an SD service."""
    return {
        "address": address,
        "type": resource_type,
        "change": {
            "actions": actions if actions is not None else ["delete"],
            "before": {"id": sd_service_id},
        },
    }


def _ecs_response(
    service_name: str = "dev-portal-guacd",
    desired_count: int = 1,
    running_count: int = 0,
    status: str = "ACTIVE",
) -> dict:
    """Build an ECS describe-services payload."""
    return {
        "services": [
            {
                "serviceName": service_name,
                "status": status,
                "desiredCount": desired_count,
                "runningCount": running_count,
            }
        ]
    }


def _tf_outputs(
    cluster: str = "dev-portal-guacamole",
    guacd_service: str = "dev-portal-guacd",
    client_service: str = "dev-portal-guacamole-client",
) -> dict:
    """Build a terraform output -json payload."""
    return {
        "guacamole_ecs_cluster_name": {"value": cluster, "type": "string"},
        "guacd_service_name": {"value": guacd_service, "type": "string"},
        "guacamole_client_service_name": {"value": client_service, "type": "string"},
    }


def _no_sleep(_: float) -> None:
    return None


# ---------------------------------------------------------------------------
# Plan detection tests
# ---------------------------------------------------------------------------


def test_detect_sd_deletion_delete_action() -> None:
    """A resource_change with actions=['delete'] is detected as a deletion."""
    plan = _plan_json([_sd_change(actions=["delete"])])
    deletions = _detect_sd_deletions(plan)
    assert len(deletions) == 1
    assert deletions[0]["address"] == "module.guacamole.aws_service_discovery_service.guacd"


def test_detect_sd_deletion_replace_delete_create() -> None:
    """A replace cycle (actions=['delete','create']) also counts as a deletion."""
    plan = _plan_json([_sd_change(actions=["delete", "create"])])
    deletions = _detect_sd_deletions(plan)
    assert len(deletions) == 1


def test_detect_sd_deletion_replace_create_delete() -> None:
    """A replace cycle (actions=['create','delete']) also counts as a deletion."""
    plan = _plan_json([_sd_change(actions=["create", "delete"])])
    deletions = _detect_sd_deletions(plan)
    assert len(deletions) == 1


def test_detect_sd_deletion_absent_when_no_delete() -> None:
    """A resource_change with actions=['create'] only is NOT detected."""
    plan = _plan_json([_sd_change(actions=["create"])])
    deletions = _detect_sd_deletions(plan)
    assert deletions == []


def test_detect_sd_deletion_absent_when_no_sd_type() -> None:
    """A delete on a different resource type is not detected."""
    change = _sd_change(actions=["delete"], resource_type="aws_ecs_service")
    plan = _plan_json([change])
    deletions = _detect_sd_deletions(plan)
    assert deletions == []


def test_detect_sd_deletion_both_services() -> None:
    """Both guacd and guacamole_client deletions are detected when both are present."""
    plan = _plan_json(
        [
            _sd_change(
                address="module.guacamole.aws_service_discovery_service.guacd",
                actions=["delete"],
                sd_service_id="srv-guacd",
            ),
            _sd_change(
                address="module.guacamole.aws_service_discovery_service.guacamole_client",
                actions=["delete"],
                sd_service_id="srv-client",
            ),
        ]
    )
    deletions = _detect_sd_deletions(plan)
    assert len(deletions) == 2
    addresses = {d["address"] for d in deletions}
    assert "module.guacamole.aws_service_discovery_service.guacd" in addresses
    assert "module.guacamole.aws_service_discovery_service.guacamole_client" in addresses


def test_detect_sd_deletion_malformed_json_raises() -> None:
    """A plan payload without 'resource_changes' raises ValueError."""
    with pytest.raises(ValueError, match="resource_changes"):
        _detect_sd_deletions({"format_version": "1.0"})


# ---------------------------------------------------------------------------
# Address → service mapping tests
# ---------------------------------------------------------------------------


def test_address_suffix_guacd() -> None:
    """The guacd suffix maps to guacd_service_name output key."""
    address = "module.guacamole.aws_service_discovery_service.guacd"
    suffix = _address_suffix(address)
    assert suffix == "guacd"
    assert _SD_SUFFIX_TO_OUTPUT_KEY[suffix] == "guacd_service_name"


def test_address_suffix_guacamole_client() -> None:
    """The guacamole_client suffix maps to guacamole_client_service_name output key."""
    address = "module.guacamole.aws_service_discovery_service.guacamole_client"
    suffix = _address_suffix(address)
    assert suffix == "guacamole_client"
    assert _SD_SUFFIX_TO_OUTPUT_KEY[suffix] == "guacamole_client_service_name"


# ---------------------------------------------------------------------------
# Drain: desiredCount snapshot
# ---------------------------------------------------------------------------


def test_drain_writes_desired_count_snapshot(tmp_path: Path) -> None:
    """drain() writes the original desiredCount to the snapshot file."""
    plan = _plan_json([_sd_change(sd_service_id="srv-guacd")])
    snap = tmp_path / "snap.json"
    ecs_update = mock.Mock()

    rc = drain(
        tf_plan="tfplan",
        tf_outputs_from=tmp_path,
        terraform_show=mock.Mock(return_value=plan),
        terraform_outputs=mock.Mock(return_value=_tf_outputs()),
        ecs_describe=mock.Mock(return_value=_ecs_response(desired_count=2, running_count=0)),
        ecs_update=ecs_update,
        sd_list=mock.Mock(return_value={"Instances": []}),
        sleep=_no_sleep,
        max_attempts=1,
        sd_max_attempts=1,
        out_stream=mock.Mock(),
        snapshot_path=snap,
    )

    assert rc == 0
    data = json.loads(snap.read_text())
    assert data["cluster"] == "dev-portal-guacamole"
    assert data["dev-portal-guacd"] == 2
    # The scale-to-zero call is drain's primary side effect: assert it happened.
    ecs_update.assert_called_once_with("dev-portal-guacamole", "dev-portal-guacd", 0)


def test_drain_no_sd_deletion_writes_empty_snapshot(tmp_path: Path) -> None:
    """drain() with no SD deletion writes an empty snapshot and exits 0."""
    plan = _plan_json([])
    snap = tmp_path / "snap.json"
    out = mock.Mock()

    rc = drain(
        tf_plan="tfplan",
        tf_outputs_from=tmp_path,
        terraform_show=mock.Mock(return_value=plan),
        terraform_outputs=mock.Mock(return_value=_tf_outputs()),
        ecs_describe=mock.Mock(),
        ecs_update=mock.Mock(),
        sd_list=mock.Mock(),
        sleep=_no_sleep,
        max_attempts=1,
        sd_max_attempts=1,
        out_stream=out,
        snapshot_path=snap,
    )

    assert rc == 0
    data = json.loads(snap.read_text())
    assert data == {}


# ---------------------------------------------------------------------------
# Drain: ECS drain poll
# ---------------------------------------------------------------------------


def test_drain_polls_until_running_count_zero(tmp_path: Path) -> None:
    """drain() polls until runningCount reaches 0, sleeping between attempts."""
    plan = _plan_json([_sd_change(sd_service_id="srv-guacd")])
    snap = tmp_path / "snap.json"

    # First poll: still running; second poll: drained; SD poll: zero immediately
    ecs_describe = mock.Mock(
        side_effect=[
            _ecs_response(desired_count=1, running_count=1),  # initial describe
            _ecs_response(desired_count=0, running_count=1),  # poll 1
            _ecs_response(desired_count=0, running_count=0),  # poll 2 — drained
        ]
    )
    sleep = mock.Mock()
    ecs_update = mock.Mock()

    rc = drain(
        tf_plan="tfplan",
        tf_outputs_from=tmp_path,
        terraform_show=mock.Mock(return_value=plan),
        terraform_outputs=mock.Mock(return_value=_tf_outputs()),
        ecs_describe=ecs_describe,
        ecs_update=ecs_update,
        sd_list=mock.Mock(return_value={"Instances": []}),
        sleep=sleep,
        max_attempts=5,
        poll_interval=1.0,
        sd_max_attempts=1,
        sd_poll_interval=0.0,
        out_stream=mock.Mock(),
        snapshot_path=snap,
    )

    assert rc == 0
    # slept once between the two failed poll attempts
    assert sleep.call_count >= 1
    ecs_update.assert_called_once_with("dev-portal-guacamole", "dev-portal-guacd", 0)


def test_drain_timeout_on_ecs_drain_exits_nonzero(tmp_path: Path) -> None:
    """drain() exits non-zero when runningCount never reaches 0 within max_attempts."""
    plan = _plan_json([_sd_change(sd_service_id="srv-guacd")])
    snap = tmp_path / "snap.json"
    out = mock.Mock()

    # Initial describe + unlimited drain polls all show running tasks
    ecs_describe = mock.Mock(return_value=_ecs_response(desired_count=1, running_count=1))

    rc = drain(
        tf_plan="tfplan",
        tf_outputs_from=tmp_path,
        terraform_show=mock.Mock(return_value=plan),
        terraform_outputs=mock.Mock(return_value=_tf_outputs()),
        ecs_describe=ecs_describe,
        ecs_update=mock.Mock(),
        sd_list=mock.Mock(return_value={"Instances": []}),
        sleep=_no_sleep,
        max_attempts=3,
        sd_max_attempts=1,
        out_stream=out,
        snapshot_path=snap,
    )

    assert rc != 0
    written = "\n".join(call.args[0] for call in out.write.call_args_list)
    assert "::error::" in written
    assert "Timeout" in written or "timeout" in written.lower()


def test_drain_persists_snapshot_before_failure(tmp_path: Path) -> None:
    """A drain that fails after scaling down still leaves a durable restore snapshot.

    The service is scaled to 0 out of band, then the drain times out. Because
    aws_ecs_service.guacd ignores desired_count drift, the restore step is the
    only thing that brings it back, so the snapshot must already be on disk with
    the original count even though drain() returns non-zero.
    """
    plan = _plan_json([_sd_change(sd_service_id="srv-guacd")])
    snap = tmp_path / "snap.json"
    # Initial describe captures desiredCount=3; drain polls never reach 0.
    ecs_describe = mock.Mock(return_value=_ecs_response(desired_count=3, running_count=1))
    ecs_update = mock.Mock()

    rc = drain(
        tf_plan="tfplan",
        tf_outputs_from=tmp_path,
        terraform_show=mock.Mock(return_value=plan),
        terraform_outputs=mock.Mock(return_value=_tf_outputs()),
        ecs_describe=ecs_describe,
        ecs_update=ecs_update,
        sd_list=mock.Mock(return_value={"Instances": []}),
        sleep=_no_sleep,
        max_attempts=2,
        sd_max_attempts=1,
        out_stream=mock.Mock(),
        snapshot_path=snap,
    )

    assert rc != 0
    # The service was actually scaled down before the drain timed out.
    ecs_update.assert_called_once_with("dev-portal-guacamole", "dev-portal-guacd", 0)
    assert snap.exists()
    data = json.loads(snap.read_text())
    assert data["cluster"] == "dev-portal-guacamole"
    assert data["dev-portal-guacd"] == 3


# ---------------------------------------------------------------------------
# Drain: Cloud Map deregistration poll
# ---------------------------------------------------------------------------


def test_drain_polls_cloud_map_until_zero_instances(tmp_path: Path) -> None:
    """drain() polls Cloud Map until list-instances returns empty."""
    plan = _plan_json([_sd_change(sd_service_id="srv-guacd")])
    snap = tmp_path / "snap.json"

    # ECS drain completes immediately; Cloud Map has one instance then zero
    sd_list = mock.Mock(
        side_effect=[
            {"Instances": [{"Id": "i-1"}]},  # poll 1 — still registered
            {"Instances": []},  # poll 2 — deregistered
        ]
    )
    sleep = mock.Mock()
    ecs_update = mock.Mock()

    rc = drain(
        tf_plan="tfplan",
        tf_outputs_from=tmp_path,
        terraform_show=mock.Mock(return_value=plan),
        terraform_outputs=mock.Mock(return_value=_tf_outputs()),
        ecs_describe=mock.Mock(return_value=_ecs_response(desired_count=1, running_count=0)),
        ecs_update=ecs_update,
        sd_list=sd_list,
        sleep=sleep,
        max_attempts=1,
        sd_max_attempts=5,
        sd_poll_interval=1.0,
        out_stream=mock.Mock(),
        snapshot_path=snap,
    )

    assert rc == 0
    assert sd_list.call_count == 2
    ecs_update.assert_called_once_with("dev-portal-guacamole", "dev-portal-guacd", 0)


def test_drain_cloud_map_timeout_exits_nonzero(tmp_path: Path) -> None:
    """drain() exits non-zero when Cloud Map still has instances after sd_max_attempts."""
    plan = _plan_json([_sd_change(sd_service_id="srv-guacd")])
    snap = tmp_path / "snap.json"
    out = mock.Mock()

    # ECS drains immediately; Cloud Map never deregisters
    sd_list = mock.Mock(return_value={"Instances": [{"Id": "i-1"}]})

    rc = drain(
        tf_plan="tfplan",
        tf_outputs_from=tmp_path,
        terraform_show=mock.Mock(return_value=plan),
        terraform_outputs=mock.Mock(return_value=_tf_outputs()),
        ecs_describe=mock.Mock(return_value=_ecs_response(desired_count=1, running_count=0)),
        ecs_update=mock.Mock(),
        sd_list=sd_list,
        sleep=_no_sleep,
        max_attempts=1,
        sd_max_attempts=3,
        out_stream=out,
        snapshot_path=snap,
    )

    assert rc != 0
    written = "\n".join(call.args[0] for call in out.write.call_args_list)
    assert "::error::" in written
    assert "srv-guacd" in written


# ---------------------------------------------------------------------------
# Restore tests
# ---------------------------------------------------------------------------


def test_restore_scales_back_to_captured_counts(tmp_path: Path) -> None:
    """restore() reads the snapshot and calls ecs_update for each service."""
    snap = tmp_path / "snap.json"
    snap.write_text(
        json.dumps({"cluster": "dev-portal-guacamole", "dev-portal-guacd": 2}),
        encoding="utf-8",
    )
    ecs_update = mock.Mock()

    rc = restore(snapshot_path=snap, ecs_update=ecs_update)

    assert rc == 0
    ecs_update.assert_called_once_with("dev-portal-guacamole", "dev-portal-guacd", 2)


def test_restore_multiple_services(tmp_path: Path) -> None:
    """restore() calls ecs_update for each non-cluster key in the snapshot."""
    snap = tmp_path / "snap.json"
    snap.write_text(
        json.dumps(
            {
                "cluster": "dev-portal-guacamole",
                "dev-portal-guacd": 1,
                "dev-portal-guacamole-client": 1,
            }
        ),
        encoding="utf-8",
    )
    ecs_update = mock.Mock()

    rc = restore(snapshot_path=snap, ecs_update=ecs_update)

    assert rc == 0
    assert ecs_update.call_count == 2
    calls = {(c.args[1], c.args[2]) for c in ecs_update.call_args_list}
    assert ("dev-portal-guacd", 1) in calls
    assert ("dev-portal-guacamole-client", 1) in calls


def test_restore_noop_when_snapshot_missing(tmp_path: Path) -> None:
    """restore() is a no-op (exit 0) when the snapshot file does not exist."""
    ecs_update = mock.Mock()
    rc = restore(snapshot_path=tmp_path / "missing.json", ecs_update=ecs_update)
    assert rc == 0
    ecs_update.assert_not_called()


def test_restore_noop_when_snapshot_empty(tmp_path: Path) -> None:
    """restore() is a no-op (exit 0) when the snapshot is an empty dict."""
    snap = tmp_path / "snap.json"
    snap.write_text("{}", encoding="utf-8")
    ecs_update = mock.Mock()

    rc = restore(snapshot_path=snap, ecs_update=ecs_update)

    assert rc == 0
    ecs_update.assert_not_called()


# ---------------------------------------------------------------------------
# Sanitized diagnostics
# ---------------------------------------------------------------------------


def test_no_secrets_from_tf_outputs_in_drain_log(tmp_path: Path) -> None:
    """drain() must not echo sensitive TF output values into CI logs.

    The terraform output -json payload may contain sensitive outputs (e.g.
    database passwords). Our code reads only the specific output keys it needs
    and must never dump the full payload or any other output value.
    """
    plan = _plan_json([_sd_change(sd_service_id="srv-guacd")])
    snap = tmp_path / "snap.json"
    out = mock.Mock()

    # Inject a sensitive field into TF outputs — it must not appear in logs
    tf_outputs_with_secret = {
        **_tf_outputs(),
        "db_master_password": {"value": "super-secret-password-xyz", "type": "string"},
    }

    drain(
        tf_plan="tfplan",
        tf_outputs_from=tmp_path,
        terraform_show=mock.Mock(return_value=plan),
        terraform_outputs=mock.Mock(return_value=tf_outputs_with_secret),
        ecs_describe=mock.Mock(return_value=_ecs_response(desired_count=1, running_count=0)),
        ecs_update=mock.Mock(),
        sd_list=mock.Mock(return_value={"Instances": []}),
        sleep=_no_sleep,
        max_attempts=1,
        sd_max_attempts=1,
        out_stream=out,
        snapshot_path=snap,
    )

    written = "\n".join(call.args[0] for call in out.write.call_args_list)
    assert "super-secret-password-xyz" not in written
