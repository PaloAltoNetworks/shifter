"""Tests for _run_terraform_destroy and run_range_terraform failure handling.

Covers:
- _run_terraform_destroy allows destroying failed ranges (not just destroyed)
- run_range_terraform auto-cleanup passes variables on provision failure
- provision-failure compensation reuses the canonical teardown (#408)
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from shared.remote_access import build_openvpn_capability

sys.path.insert(0, str(Path(__file__).parent.parent))


def _install_destroy_fakes(monkeypatch, *, status="ready", variables=None):
    mock_get_data = MagicMock(return_value={"status": status})
    mock_tf_runner = MagicMock()
    mock_build_vars = MagicMock(return_value=variables or {})
    mock_update_status = MagicMock()
    mock_mark = MagicMock()
    monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", mock_get_data)
    monkeypatch.setattr("terraform_ops.range_terraform_runner", mock_tf_runner)
    monkeypatch.setattr("terraform_ops.build_range_variables", mock_build_vars)
    monkeypatch.setattr("terraform_ops.update_range_status", mock_update_status)
    monkeypatch.setattr("range_subnet_allocation.mark_range_instances_destroyed", mock_mark)
    monkeypatch.setattr("terraform_ops.get_vpn_secret_ops", MagicMock())
    monkeypatch.setattr("terraform_ops.cleanup_openvpn_access", MagicMock())
    return mock_get_data, mock_tf_runner, mock_build_vars, mock_update_status, mock_mark


class TestRunTerraformDestroySkipsOnlyDestroyed:
    """_run_terraform_destroy should only skip 'destroyed' ranges, not 'failed'."""

    def test_skips_destroyed_status(self, monkeypatch):
        """Destroyed ranges should be skipped."""
        from terraform_ops import RangeOperation, _run_terraform_destroy

        _mock_get_data, mock_tf_runner, _mock_build_vars, mock_publish, _mock_mark = _install_destroy_fakes(
            monkeypatch, status="destroyed"
        )

        _run_terraform_destroy(RangeOperation("req-1", 80, 20, {}))

        mock_tf_runner.destroy_range.assert_not_called()
        mock_publish.assert_not_called()

    def test_does_not_skip_failed_status(self, monkeypatch):
        """Failed ranges should NOT be skipped - they may have orphaned resources."""
        from terraform_ops import RangeOperation, _run_terraform_destroy

        _mock_get_data, mock_tf_runner, _mock_build_vars, mock_publish, _mock_mark = _install_destroy_fakes(
            monkeypatch, status="failed"
        )

        _run_terraform_destroy(RangeOperation("req-1", 80, 20, {}))

        mock_tf_runner.destroy_range.assert_called_once()
        mock_publish.assert_called_once()

    def test_proceeds_for_ready_status(self, monkeypatch):
        """Ready (active) ranges should proceed with destroy."""
        from terraform_ops import RangeOperation, _run_terraform_destroy

        _mock_get_data, mock_tf_runner, _mock_build_vars, _mock_publish, _mock_mark = _install_destroy_fakes(
            monkeypatch, status="ready"
        )

        _run_terraform_destroy(RangeOperation("req-1", 80, 20, {}))

        mock_tf_runner.destroy_range.assert_called_once()

    def test_destroy_passes_variables_to_destroy_range(self, monkeypatch):
        """_run_terraform_destroy must pass variables to destroy_range."""
        from terraform_ops import RangeOperation, _run_terraform_destroy

        fake_vars = {"range_id": 80, "user_id": 20, "request_uuid": "req-1", "vpc_id": "vpc-123"}
        _mock_get_data, mock_tf_runner, _mock_build_vars, _mock_publish, _mock_mark = _install_destroy_fakes(
            monkeypatch, status="ready", variables=fake_vars
        )
        range_spec = {"subnets": []}

        _run_terraform_destroy(RangeOperation("req-1", 80, 20, range_spec))

        mock_tf_runner.destroy_range.assert_called_once_with("req-1", variables=fake_vars, backend=None)


class TestAutoCleanupPassesVariables:
    """run_range_terraform auto-cleanup should pass tf variables on provision failure."""

    @pytest.fixture(autouse=True)
    def _stub_teardown_db_boundaries(self, monkeypatch):
        """Explicitly stub the DB-touching teardown boundaries the shared
        _teardown_owned_range_resources reaches on the compensation path (#408).

        These tests exercise compensation through run_range_terraform('up', ...);
        hermeticity must not depend on ambient DB env being unset for
        _maybe_pause_user_ngfw / _post_destroy_cleanup to no-op.
        """
        monkeypatch.setattr("terraform_ops._maybe_pause_user_ngfw", MagicMock())
        monkeypatch.setattr("terraform_ops._post_destroy_cleanup", MagicMock())

    def test_cleanup_passes_variables_to_destroy(self, monkeypatch):
        """Auto-cleanup should rebuild variables and pass them to destroy_range."""
        from terraform_ops import run_range_terraform
        from terraform_vars import RangeVariableContext

        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.delenv("GCP_RANGE_BACKEND", raising=False)

        mock_get_data = MagicMock(
            return_value={
                "range_id": 80,
                "user_id": 20,
                "spec": {"ngfw": False, "subnets": []},
            }
        )
        mock_tf_runner = MagicMock()
        fake_vars = {"range_id": 80, "user_id": 20, "request_uuid": "req-1"}
        mock_build_vars = MagicMock(return_value=fake_vars)
        monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", mock_get_data)
        monkeypatch.setattr(
            "terraform_ops._run_terraform_provision", MagicMock(side_effect=RuntimeError("NGFW config failed"))
        )
        monkeypatch.setattr("terraform_ops.range_terraform_runner", mock_tf_runner)
        monkeypatch.setattr("terraform_ops.build_range_variables", mock_build_vars)
        monkeypatch.setattr("terraform_ops.update_range_status", MagicMock())

        with pytest.raises(RuntimeError, match="NGFW config failed"):
            run_range_terraform("up", "req-1")

        mock_build_vars.assert_called_once_with(
            "req-1",
            80,
            20,
            {"ngfw": False, "subnets": []},
            RangeVariableContext(
                scenario_artifact=None, backend=None, remote_access_capability=None, egress_mode="status-quo"
            ),
        )
        mock_tf_runner.destroy_range.assert_called_once_with("req-1", variables=fake_vars, backend=None)

    def test_cleanup_forwards_the_pinned_none_egress_mode(self, monkeypatch):
        """The pinned per-range egress posture rides the cleanup path, not a hardcoded default."""
        from terraform_ops import run_range_terraform
        from terraform_vars import RangeVariableContext

        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.delenv("GCP_RANGE_BACKEND", raising=False)

        mock_get_data = MagicMock(
            return_value={
                "range_id": 80,
                "user_id": 20,
                "spec": {"ngfw": False, "subnets": []},
                "egress_mode": "none",
            }
        )
        mock_tf_runner = MagicMock()
        fake_vars = {"range_id": 80, "user_id": 20, "request_uuid": "req-1"}
        mock_build_vars = MagicMock(return_value=fake_vars)
        monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", mock_get_data)
        monkeypatch.setattr(
            "terraform_ops._run_terraform_provision", MagicMock(side_effect=RuntimeError("NGFW config failed"))
        )
        monkeypatch.setattr("terraform_ops.range_terraform_runner", mock_tf_runner)
        monkeypatch.setattr("terraform_ops.build_range_variables", mock_build_vars)
        monkeypatch.setattr("terraform_ops.update_range_status", MagicMock())

        with pytest.raises(RuntimeError, match="NGFW config failed"):
            run_range_terraform("up", "req-1")

        assert mock_build_vars.call_args.args[4] == RangeVariableContext(
            scenario_artifact=None, backend=None, remote_access_capability=None, egress_mode="none"
        )

    def test_cleanup_failure_logged_not_swallowed(self, monkeypatch, caplog):
        """When compensation fails, it is bounded-logged (error, no raw diagnostics), not swallowed."""
        import logging

        from terraform_ops import run_range_terraform

        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.delenv("GCP_RANGE_BACKEND", raising=False)

        monkeypatch.setattr(
            "terraform_ops.get_range_data_by_request_id",
            MagicMock(
                return_value={
                    "range_id": 80,
                    "user_id": 20,
                    "spec": {"ngfw": False, "subnets": []},
                }
            ),
        )
        monkeypatch.setattr(
            "terraform_ops._run_terraform_provision",
            MagicMock(side_effect=RuntimeError("provision failed")),
        )
        monkeypatch.setattr("terraform_ops.range_terraform_runner", MagicMock())
        monkeypatch.setattr(
            "terraform_ops.build_range_variables",
            MagicMock(side_effect=ValueError("NGFW missing")),
        )
        monkeypatch.setattr("terraform_ops.update_range_status", MagicMock())

        with pytest.raises(RuntimeError, match="provision failed"), caplog.at_level(logging.ERROR):
            run_range_terraform("up", "req-1")

        comp_records = [r for r in caplog.records if "Compensation destroy FAILED" in r.getMessage()]
        assert comp_records
        for record in comp_records:
            # Bounded classification only: the raw exception message must not leak,
            # and no traceback surface is attached (ADR-043-R5).
            assert "NGFW missing" not in record.getMessage()
            assert "NGFW missing" not in (record.exc_text or "")
            assert record.exc_info is None

    def test_no_cleanup_on_destroy_failure(self, monkeypatch):
        """Auto-cleanup should only run for 'up' operations, not 'destroy'."""
        from terraform_ops import run_range_terraform

        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.delenv("GCP_RANGE_BACKEND", raising=False)

        mock_get_data = MagicMock(
            return_value={
                "range_id": 80,
                "user_id": 20,
                "spec": {},
            }
        )
        mock_tf_runner = MagicMock()
        monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", mock_get_data)
        monkeypatch.setattr("terraform_ops.range_terraform_runner", mock_tf_runner)
        mock_destroy = MagicMock()
        monkeypatch.setattr("terraform_ops._run_terraform_destroy", mock_destroy)
        monkeypatch.setattr("terraform_ops.update_range_status", MagicMock())
        mock_destroy.side_effect = RuntimeError("destroy failed")

        with pytest.raises(RuntimeError, match="destroy failed"):
            run_range_terraform("destroy", "req-1")

        # destroy_range on the terraform_runner should NOT be called for cleanup
        mock_tf_runner.destroy_range.assert_not_called()


class TestRemoteAccessAdmission:
    def test_capability_rejects_an_unconfigured_adapter_before_dispatch(self, monkeypatch):
        from cloud.exceptions import CloudError
        from terraform_ops import run_range_terraform

        target_ref = "11111111-1111-4111-8111-111111111111"
        capability = build_openvpn_capability(target_ref, datetime.now(UTC) + timedelta(days=5))
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        for name in (
            "RANGE_VPN_EDGE_SUBNET_ID",
            "RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN",
            "RANGE_VPN_PROVIDER_ENDPOINT_SECURITY_GROUP_ID",
            "PORTAL_NETWORK_CIDRS",
            "PORTAL_VPC_CIDR",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(
            "terraform_ops.get_range_data_by_request_id",
            MagicMock(
                return_value={
                    "range_id": 80,
                    "user_id": 20,
                    "spec": {"subnets": [{"instances": [{"uuid": target_ref}]}]},
                    "remote_access_capability": capability,
                }
            ),
        )
        dispatch = MagicMock()
        monkeypatch.setattr("terraform_ops._dispatch_terraform_operation", dispatch)
        monkeypatch.setattr("terraform_ops.update_range_status", MagicMock())

        with pytest.raises(CloudError, match="not configured"):
            run_range_terraform("up", "req-1")

        dispatch.assert_not_called()

    def test_kali_topology_without_capability_does_not_activate_vpn_admission(self, monkeypatch):
        from terraform_ops import run_range_terraform

        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.setattr(
            "terraform_ops.get_range_data_by_request_id",
            MagicMock(
                return_value={
                    "range_id": 80,
                    "user_id": 20,
                    "spec": {"subnets": [{"instances": [{"role": "attacker", "os_type": "kali"}]}]},
                    "remote_access_capability": None,
                }
            ),
        )
        dispatch = MagicMock()
        monkeypatch.setattr("terraform_ops._dispatch_terraform_operation", dispatch)

        run_range_terraform("up", "req-1")

        dispatch.assert_called_once()


@pytest.fixture
def compensation_fakes(monkeypatch):
    """Boundary fakes for driving run_range_terraform('up', ...) into
    provision-failure compensation (#408).

    Provision fails immediately; every teardown boundary the compensation destroy
    reaches is mocked so the test can assert the *algorithm* (realized CIDRs, NGFW
    detach, ownership-gated release, bounded diagnostics) without a real DB,
    Terraform, or cloud call.
    """
    monkeypatch.setenv("CLOUD_PROVIDER", "aws")
    monkeypatch.delenv("GCP_RANGE_BACKEND", raising=False)

    realized_spec = {"ngfw": False, "subnets": [{"name": "s1", "cidr": "10.1.0.0/28"}]}
    mocks = SimpleNamespace(
        get_data=MagicMock(
            return_value={
                "range_id": 80,
                "user_id": 20,
                "spec": {"ngfw": False, "subnets": [{"name": "s1"}]},
            }
        ),
        provision=MagicMock(side_effect=RuntimeError("provision boom")),
        tf_runner=MagicMock(),
        build_vars=MagicMock(return_value={"realized": True}),
        update_status=MagicMock(),
        realized_spec=realized_spec,
        realized=MagicMock(return_value=realized_spec),
        ngfw_detach=MagicMock(),
        post_destroy=MagicMock(),
        pause_ngfw=MagicMock(),
        vpn_cleanup=MagicMock(),
    )
    monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", mocks.get_data)
    monkeypatch.setattr("terraform_ops._run_terraform_provision", mocks.provision)
    monkeypatch.setattr("terraform_ops.range_terraform_runner", mocks.tf_runner)
    monkeypatch.setattr("terraform_ops.build_range_variables", mocks.build_vars)
    monkeypatch.setattr("terraform_ops.update_range_status", mocks.update_status)
    monkeypatch.setattr("terraform_ops._realized_range_spec_for_destroy", mocks.realized)
    monkeypatch.setattr("terraform_ops._remove_ngfw_attachments_for_destroy", mocks.ngfw_detach)
    monkeypatch.setattr("terraform_ops._post_destroy_cleanup", mocks.post_destroy)
    monkeypatch.setattr("terraform_ops._maybe_pause_user_ngfw", mocks.pause_ngfw)
    monkeypatch.setattr("terraform_ops._cleanup_openvpn_if_enabled", mocks.vpn_cleanup)
    return mocks


class TestCompensationReusesCanonicalTeardown:
    """Provision-failure compensation must follow the canonical teardown lifecycle (#408)."""

    def test_compensation_destroys_from_realized_cidrs(self, compensation_fakes):
        """Compensation destroys from the CIDRs the range actually holds, not authored intent."""
        from terraform_ops import run_range_terraform

        with pytest.raises(RuntimeError, match="provision boom"):
            run_range_terraform("up", "req-1")

        compensation_fakes.realized.assert_called_once()
        # The destroy variables are built from the realized spec, not authored intent.
        assert compensation_fakes.build_vars.call_args.args[3] == compensation_fakes.realized_spec

    def test_compensation_retains_ownership_when_destroy_fails(self, compensation_fakes):
        """A failed compensation destroy must not release ownership (orphans still occupy it).

        Ownership release (subnet reservations + child projection) is performed
        exclusively by ``_post_destroy_cleanup``, which the teardown helper gates
        behind a confirmed destroy; asserting it is not called proves ownership
        is retained for retry.
        """
        from terraform_ops import run_range_terraform

        compensation_fakes.tf_runner.destroy_range.side_effect = RuntimeError("destroy boom")

        with pytest.raises(RuntimeError, match="provision boom"):
            run_range_terraform("up", "req-1")

        compensation_fakes.post_destroy.assert_not_called()

    def test_compensation_revokes_vpn_generation_even_when_destroy_fails(self, compensation_fakes):
        """Issued remote-access credentials must be revoked even if the destroy fails (identity preserved).

        A failed compensation settles the range FAILED with possibly-surviving
        orphan resources; leaving the generation's credentials active would grant
        continued access to them.
        """
        from terraform_ops import run_range_terraform

        compensation_fakes.tf_runner.destroy_range.side_effect = RuntimeError("destroy boom")

        with pytest.raises(RuntimeError, match="provision boom"):
            run_range_terraform("up", "req-1")

        compensation_fakes.vpn_cleanup.assert_called_once_with(80, "req-1", delete_identity=False)

    def test_compensation_completes_cleanup_on_success(self, compensation_fakes):
        """A successful compensation detaches NGFW and releases ownership via _post_destroy_cleanup."""
        from terraform_ops import run_range_terraform

        with pytest.raises(RuntimeError, match="provision boom"):
            run_range_terraform("up", "req-1")

        compensation_fakes.ngfw_detach.assert_called_once()
        compensation_fakes.post_destroy.assert_called_once()

    def test_compensation_failure_does_not_leak_raw_diagnostics(self, compensation_fakes, caplog):
        """A compensation destroy failure is bounded-logged: no raw provider output, no traceback."""
        import logging

        from terraform_ops import run_range_terraform

        leak = "RAW_TF_STDERR_aws_access_key_LEAK"
        compensation_fakes.tf_runner.destroy_range.side_effect = RuntimeError(leak)

        with pytest.raises(RuntimeError, match="provision boom"), caplog.at_level(logging.ERROR):
            run_range_terraform("up", "req-1")

        for record in caplog.records:
            assert leak not in record.getMessage()
            assert leak not in (record.exc_text or "")
            # Compensation must not attach a raw-exception surface for its own failure.
            if record.name.endswith("terraform_ops") and "compensation destroy failed" in record.getMessage().lower():
                assert record.exc_info is None
