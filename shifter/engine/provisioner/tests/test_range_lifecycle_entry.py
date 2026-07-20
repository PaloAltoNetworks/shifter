"""Unit tests for _build_range_lifecycle_entry dispatch (issue #779 burndown)."""

import pytest

from range_ops import _build_range_lifecycle_entry


def test_aws_entry_with_instance_id():
    state = {"cloud_provider": "aws", "aws_instance_id": "i-123"}
    entry = _build_range_lifecycle_entry(
        "req-1",
        "uuid-1",
        state,
        "victim",
        "vm1",
    )
    assert entry == {
        "uuid": "uuid-1",
        "name": "vm1",
        "role": "victim",
        "cloud_provider": "aws",
        "asset_type": "vm_runtime_vm",
        "state": state,
        "operation_mode": "aws",
        "aws_instance_id": "i-123",
    }


def test_aws_entry_missing_instance_id_is_skipped():
    entry = _build_range_lifecycle_entry("req-1", "uuid-1", {"cloud_provider": "aws"}, "victim", None)
    assert entry is None


def test_gcp_vm_runtime_entry():
    state = {"cloud_provider": "gcp", "asset_type": "vm_runtime_vm"}
    entry = _build_range_lifecycle_entry(
        "req-1",
        "uuid-2",
        state,
        "attacker",
        "vm2",
    )
    assert entry == {
        "uuid": "uuid-2",
        "name": "vm2",
        "role": "attacker",
        "cloud_provider": "gcp",
        "asset_type": "vm_runtime_vm",
        "state": state,
        "operation_mode": "gdc_vm_runtime",
    }


def test_gcp_gce_vm_entry():
    state = {"cloud_provider": "gcp", "asset_type": "gce_vm"}
    entry = _build_range_lifecycle_entry(
        "req-1",
        "uuid-4",
        state,
        "attacker",
        "vm4",
    )
    assert entry == {
        "uuid": "uuid-4",
        "name": "vm4",
        "role": "attacker",
        "cloud_provider": "gcp",
        "asset_type": "gce_vm",
        "state": state,
        "operation_mode": "gce_vm",
    }


def test_gcp_scenario_pod_entry():
    state = {"cloud_provider": "gcp", "asset_type": "scenario_pod"}
    entry = _build_range_lifecycle_entry(
        "req-1",
        "uuid-3",
        state,
        "victim",
        "pod1",
    )
    assert entry == {
        "uuid": "uuid-3",
        "name": "pod1",
        "role": "victim",
        "cloud_provider": "gcp",
        "asset_type": "scenario_pod",
        "state": state,
        "operation_mode": "gdc_scenario_pod",
    }


def test_unsupported_target_raises():
    with pytest.raises(ValueError, match="Unsupported range lifecycle target"):
        _build_range_lifecycle_entry("req-9", "uuid-9", {"cloud_provider": "azure", "asset_type": "vm"}, "victim", "x")


def test_non_dict_state_defaults_to_aws():
    # A non-dict state falls back to the aws default provider and is skipped
    # without an aws_instance_id.
    assert _build_range_lifecycle_entry("req-1", "uuid-1", None, "victim", None) is None
