"""Tests for check_rds_pending_modifications.py.

Run via the package's uv environment from the repo root:
    cd scripts/check_rds_pending_modifications && uv run pytest tests/ -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_rds_pending_modifications import (
    InstanceCheck,
    check_instance,
    collect_instance_ids_from_tf_outputs,
    collect_instance_ids_from_tf_outputs_payload,
    main,
)


def _aws_response(
    pending_modified_values: dict | None = None,
    db_instance_status: str = "available",
    parameter_groups: list[dict] | None = None,
) -> dict:
    return {
        "DBInstances": [
            {
                "DBInstanceIdentifier": "ignored",
                "DBInstanceStatus": db_instance_status,
                "PendingModifiedValues": pending_modified_values or {},
                "DBParameterGroups": parameter_groups
                if parameter_groups is not None
                else [
                    {
                        "DBParameterGroupName": "default.postgres16",
                        "ParameterApplyStatus": "in-sync",
                    }
                ],
            }
        ]
    }


def _no_sleep(_: float) -> None:
    return None


def test_clean_instance_passes() -> None:
    """An RDS instance with no pending modifications passes the check."""
    aws = mock.Mock(return_value=_aws_response({}))
    result = check_instance("dev-portal-db", aws_describe=aws, sleep=_no_sleep)
    assert isinstance(result, InstanceCheck)
    assert result.instance_id == "dev-portal-db"
    assert result.pending == {}
    assert result.is_clean is True
    # First call already terminal; should not poll.
    assert aws.call_count == 1


def test_pending_class_change_on_terminal_status_fails() -> None:
    """An available instance with a pending class change is reported as failing.

    `available` is terminal, so we do not wait — the modify has either landed
    or been queued for the maintenance window.
    """
    aws = mock.Mock(return_value=_aws_response({"DBInstanceClass": "db.m5.xlarge"}, db_instance_status="available"))
    result = check_instance("dev-portal-guacamole-db", aws_describe=aws, sleep=_no_sleep)
    assert result.is_clean is False
    assert result.pending == {"DBInstanceClass": "db.m5.xlarge"}
    assert aws.call_count == 1


def test_modifying_then_available_clears_to_pass() -> None:
    """If the instance is mid-modify, we wait until it settles; clean = pass.

    This is the core fix for the false-positive failure when `apply_immediately`
    is true: `terraform apply` returns while RDS is still applying, so the
    first describe call still shows pending. After the change lands, pending
    clears and the gate passes.
    """
    sequence = [
        _aws_response({"DBInstanceClass": "db.m5.xlarge"}, db_instance_status="modifying"),
        _aws_response({"DBInstanceClass": "db.m5.xlarge"}, db_instance_status="modifying"),
        _aws_response({}, db_instance_status="available"),
    ]
    aws = mock.Mock(side_effect=sequence)
    sleep = mock.Mock()

    result = check_instance(
        "dev-portal-db",
        aws_describe=aws,
        sleep=sleep,
        max_attempts=5,
        poll_interval=1.0,
    )

    assert result.is_clean is True
    assert aws.call_count == 3
    # Slept twice (between attempts 1→2 and 2→3); the post-success attempt
    # does not sleep.
    assert sleep.call_count == 2


def test_stuck_modifying_times_out_as_failure() -> None:
    """If the instance never leaves the transitional state, fail with timeout."""
    aws = mock.Mock(return_value=_aws_response({"DBInstanceClass": "db.m5.xlarge"}, db_instance_status="modifying"))

    result = check_instance(
        "dev-portal-db",
        aws_describe=aws,
        sleep=_no_sleep,
        max_attempts=4,
        poll_interval=0.0,
    )

    assert result.is_clean is False
    assert result.error is not None
    assert "did not settle" in result.error
    assert aws.call_count == 4


def test_multiple_pending_fields_all_reported() -> None:
    """All pending fields surface, not just the first one."""
    aws = mock.Mock(
        return_value=_aws_response(
            {
                "DBInstanceClass": "db.m5.xlarge",
                "AllocatedStorage": 100,
                "EngineVersion": "16.3",
            }
        )
    )
    result = check_instance("dev-portal-db", aws_describe=aws, sleep=_no_sleep)
    assert result.is_clean is False
    assert set(result.pending.keys()) == {
        "DBInstanceClass",
        "AllocatedStorage",
        "EngineVersion",
    }


def test_missing_instance_fails_clearly() -> None:
    """If AWS returns no matching DBInstances, the check fails with a clear error."""
    aws = mock.Mock(return_value={"DBInstances": []})
    result = check_instance("does-not-exist", aws_describe=aws, sleep=_no_sleep)
    assert result.is_clean is False
    assert result.error is not None
    assert "not found" in result.error.lower()


def test_collect_instance_ids_from_tf_outputs_payload_picks_db_instance_id_keys() -> None:
    """Helper extracts every db_instance_id-style output value, ignoring everything else."""
    payload = {
        "db_instance_id": {"value": "dev-portal-db", "type": "string"},
        "guacamole_db_instance_id": {
            "value": "dev-portal-guacamole-db",
            "type": "string",
        },
        "db_instance_endpoint": {
            "value": "dev-portal-db.xxxx.rds.amazonaws.com:5432",
            "type": "string",
        },
        "vpc_id": {"value": "vpc-abc", "type": "string"},
    }
    ids = collect_instance_ids_from_tf_outputs_payload(payload)
    assert sorted(ids) == sorted(["dev-portal-db", "dev-portal-guacamole-db"])


def test_collect_instance_ids_from_tf_outputs_empty_when_none() -> None:
    """No db_instance_id outputs → empty list (helper does not invent IDs)."""
    payload = {"vpc_id": {"value": "vpc-abc"}}
    assert collect_instance_ids_from_tf_outputs_payload(payload) == []


def test_collect_instance_ids_from_tf_outputs_path_wrapper(tmp_path: Path) -> None:
    """The Path wrapper preserves the in-memory parser's behavior."""
    out_file = tmp_path / "outputs.json"
    out_file.write_text(json.dumps({"db_instance_id": {"value": "dev-portal-db", "type": "string"}}))
    assert collect_instance_ids_from_tf_outputs(out_file) == ["dev-portal-db"]


def test_main_succeeds_when_all_instances_clean() -> None:
    """End-to-end: every instance clean → exit 0."""
    aws = mock.Mock(side_effect=[_aws_response({}), _aws_response({})])
    rc = main(
        ["dev-portal-db", "dev-portal-guacamole-db"],
        aws_describe=aws,
        out_stream=mock.Mock(),
        sleep=_no_sleep,
        max_attempts=1,
    )
    assert rc == 0


def test_main_fails_when_any_instance_pending() -> None:
    """End-to-end: one clean + one pending → non-zero exit. Both reported."""
    out = mock.Mock()
    aws = mock.Mock(
        side_effect=[
            _aws_response({}),
            _aws_response({"DBInstanceClass": "db.m5.xlarge"}),
        ]
    )
    rc = main(
        ["dev-portal-db", "dev-portal-guacamole-db"],
        aws_describe=aws,
        out_stream=out,
        sleep=_no_sleep,
        max_attempts=1,
    )
    assert rc != 0
    written = "\n".join(call.args[0] for call in out.write.call_args_list)
    assert "dev-portal-guacamole-db" in written
    assert "DBInstanceClass" in written


def test_main_with_no_instance_ids_is_a_clear_error() -> None:
    """Calling main with an empty ID list is a misuse — should fail noisily."""
    rc = main([], aws_describe=mock.Mock(), out_stream=mock.Mock(), sleep=_no_sleep)
    assert rc != 0


@pytest.mark.parametrize(
    ("apply_status", "expected_clean"),
    [
        # Settled or in-flight states — not deploy-blocking.
        ("in-sync", True),
        ("applying", True),
        # Failure states — must surface as deploy-blocking. Static parameter
        # changes only show up here, never in PendingModifiedValues, so any
        # gap in this set is a silent-incomplete-deploy bug
        # (per the dev/terraform.md "RDS Change Application" contract).
        ("pending-reboot", False),
        ("failed-to-apply", False),
        ("error", False),
        ("pending-database-upgrade", False),
        ("removing", False),
    ],
)
def test_parameter_group_status_classification(apply_status: str, expected_clean: bool) -> None:
    aws = mock.Mock(
        return_value=_aws_response(
            pending_modified_values={},
            parameter_groups=[
                {
                    "DBParameterGroupName": "shifter-dev-portal-pg16",
                    "ParameterApplyStatus": apply_status,
                }
            ],
        )
    )
    result = check_instance("dev-portal-db", aws_describe=aws, sleep=_no_sleep)
    assert result.is_clean is expected_clean
    if not expected_clean:
        assert result.pending["DBParameterGroup[shifter-dev-portal-pg16]"] == apply_status


def test_main_redacts_master_user_password_from_log_output() -> None:
    """A pending master-password rotation must not echo the new password into logs.

    AWS surfaces `MasterUserPassword` in `PendingModifiedValues` while a password
    rotation is in flight (per the AWS RDS API reference). Anyone with read access
    to the deploy job logs would otherwise get the plaintext credential.
    """
    out = mock.Mock()
    aws = mock.Mock(
        return_value=_aws_response(
            {
                "MasterUserPassword": "hunter2-very-secret",
                "DBInstanceClass": "db.m5.xlarge",
            }
        )
    )
    rc = main(
        ["dev-portal-db"],
        aws_describe=aws,
        out_stream=out,
        sleep=_no_sleep,
        max_attempts=1,
    )
    written = "\n".join(call.args[0] for call in out.write.call_args_list)
    assert rc != 0
    assert "hunter2-very-secret" not in written
    assert "MasterUserPassword=<redacted>" in written
    assert "DBInstanceClass" in written
