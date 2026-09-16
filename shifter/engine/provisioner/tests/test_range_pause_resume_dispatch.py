"""Tests for GCP range pause/resume dispatch and capability preflight (#614).

Covers the provisioner tier: VM Runtime / GCE power-op wiring, and the
fail-before-mutation capability preflight that refuses a range whose realized
asset mix (e.g. a scenario Pod) cannot be losslessly paused.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import gce_range_cell_power
import gdc_vmruntime_assets
import range_ops
from range_ops import _execute_instance_operation, run_range_pause, run_range_resume
from range_ops._pause_resume import UnsupportedRangeLifecycleError


def _entry(mode: str, provider: str, asset_type: str) -> dict:
    return {
        "uuid": "u1",
        "name": "guest",
        "role": "victim",
        "cloud_provider": provider,
        "asset_type": asset_type,
        "operation_mode": mode,
        "state": {"gdc_namespace": "ns", "gdc_vm_name": "vm", "gcp_project_id": "p", "gcp_zone": "z"},
    }


class TestExecuteInstanceOperation:
    def test_gdc_vm_runtime_pause_calls_stop(self, monkeypatch):
        calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: calls.append((op, state)))
        _uuid, ok, err = _execute_instance_operation(
            None, None, None, _entry("gdc_vm_runtime", "gcp", "vm_runtime_vm"), operation="pause"
        )
        assert (ok, err) == (True, None)
        assert calls[0][0] == "stop"

    def test_gdc_vm_runtime_resume_calls_start(self, monkeypatch):
        calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: calls.append((op, state)))
        _execute_instance_operation(
            None, None, None, _entry("gdc_vm_runtime", "gcp", "vm_runtime_vm"), operation="resume"
        )
        assert calls[0][0] == "start"

    def test_gce_vm_pause_calls_stop(self, monkeypatch):
        calls = []
        monkeypatch.setattr(gce_range_cell_power, "run_power_operation", lambda op, state: calls.append((op, state)))
        _uuid, ok, err = _execute_instance_operation(
            None, None, None, _entry("gce_vm", "gcp", "gce_vm"), operation="pause"
        )
        assert (ok, err) == (True, None)
        assert calls[0][0] == "stop"

    def test_scenario_pod_reports_failure(self):
        _uuid, ok, err = _execute_instance_operation(
            None, None, None, _entry("gdc_scenario_pod", "gcp", "scenario_pod"), operation="pause"
        )
        assert ok is False
        assert err


class TestCapabilityPreflight:
    def _stub_common(self, monkeypatch, instances, backend="gdc"):
        monkeypatch.setattr(
            range_ops, "get_range_data_by_request_id", lambda rid: {"status": "ready", "range_backend": backend}
        )
        monkeypatch.setattr(range_ops, "get_range_instance_ids", lambda rid: instances)
        appended: list = []
        monkeypatch.setattr(
            range_ops._pause_resume, "append_operation_step_result", lambda *a, **k: appended.append((a, k))
        )
        aws = MagicMock(name="AWSExecutor")
        monkeypatch.setattr(range_ops, "AWSExecutor", aws)
        return appended, aws

    def test_pause_with_scenario_pod_fails_before_mutation(self, monkeypatch):
        instances = [
            _entry("gdc_vm_runtime", "gcp", "vm_runtime_vm"),
            _entry("gdc_scenario_pod", "gcp", "scenario_pod"),
        ]
        appended, aws = self._stub_common(monkeypatch, instances)
        vm_calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: vm_calls.append(op))

        with pytest.raises(UnsupportedRangeLifecycleError):
            run_range_pause("req-1", operation_id="op-1")

        # No mutation: no VM power op, no AWS executor built.
        assert vm_calls == []
        aws.assert_not_called()
        # Reported an unsupported_capability terminal failure.
        payloads = [k["result_payload"] for a, k in appended if "result_payload" in k]
        assert any(p.get("reason_code") == "unsupported_capability" for p in payloads)

    def test_resume_with_scenario_pod_does_not_start_ngfw(self, monkeypatch):
        instances = [_entry("gdc_scenario_pod", "gcp", "scenario_pod")]
        self._stub_common(monkeypatch, instances)
        # A resume target is PAUSED; otherwise the idempotent no-op returns early.
        monkeypatch.setattr(
            range_ops, "get_range_data_by_request_id", lambda rid: {"status": "paused", "range_backend": "gdc"}
        )
        ngfw_calls = []
        monkeypatch.setattr(range_ops, "ensure_ngfw_running", lambda rid, ref=None: ngfw_calls.append(rid))

        with pytest.raises(UnsupportedRangeLifecycleError):
            run_range_resume("req-1", operation_id="op-1")

        # Capability check runs before the NGFW cascade.
        assert ngfw_calls == []

    def test_pause_supported_gdc_range_runs_power_op(self, monkeypatch):
        instances = [_entry("gdc_vm_runtime", "gcp", "vm_runtime_vm")]
        _appended, aws = self._stub_common(monkeypatch, instances)
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda rid, ref=None: None)
        vm_calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: vm_calls.append(op))

        run_range_pause("req-1", operation_id="op-1")

        assert vm_calls == ["stop"]
        aws.assert_not_called()  # GCP-only range does not build the AWS executor

    def test_resume_supported_gdc_range_runs_start(self, monkeypatch):
        instances = [_entry("gdc_vm_runtime", "gcp", "vm_runtime_vm")]
        self._stub_common(monkeypatch, instances)
        monkeypatch.setattr(
            range_ops, "get_range_data_by_request_id", lambda rid: {"status": "paused", "range_backend": "gdc"}
        )
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "ensure_ngfw_running", lambda rid, ref=None: None)
        vm_calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: vm_calls.append(op))

        run_range_resume("req-1", operation_id="op-1")

        assert vm_calls == ["start"]

    def test_pause_supported_gce_range_runs_stop(self, monkeypatch):
        instances = [_entry("gce_vm", "gcp", "gce_vm")]
        _appended, aws = self._stub_common(monkeypatch, instances, backend="gce")
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda rid, ref=None: None)
        gce_calls = []
        monkeypatch.setattr(gce_range_cell_power, "run_power_operation", lambda op, state: gce_calls.append(op))

        run_range_pause("req-1", operation_id="op-1")

        assert gce_calls == ["stop"]
        aws.assert_not_called()

    def test_pause_reports_terminal_failure_on_backend_error(self, monkeypatch):
        instances = [_entry("gdc_vm_runtime", "gcp", "vm_runtime_vm")]
        appended, _aws = self._stub_common(monkeypatch, instances)
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda rid, ref=None: None)

        def _boom(op, state):
            raise RuntimeError("kubectl virt stop failed")

        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", _boom)

        with pytest.raises(RuntimeError, match="Failed to pause"):
            run_range_pause("req-1", operation_id="op-1")

        payloads = [k["result_payload"] for a, k in appended if "result_payload" in k]
        assert any(p.get("reason_code") == "cloud_operation_failed" for p in payloads)
