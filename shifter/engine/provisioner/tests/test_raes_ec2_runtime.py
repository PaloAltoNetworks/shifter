"""Immutable dispatch scope and cleanup stay independent of mutable plugin settings."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

import raes_ec2_runtime as runtime
from tests.test_raes_range_ops import _open_network_plan, _projection


@pytest.fixture
def configured(monkeypatch):
    for key, value in {
        "CLOUD_PROVIDER": "aws",
        "ENVIRONMENT": "test",
        "DEPLOYMENT_ENVIRONMENT": "test",
        "AWS_REGION": "us-east-2",
        "RANGE_VPC_ID": "vpc-" + "0" * 17,
        "RANGE_VPC_CIDR": "10.50.0.0/16",
        "RANGE_AVAILABILITY_ZONE": "us-east-2a",
        "RANGE_ROUTE_TABLE_ID": "rtb-" + "0" * 17,
        "PORTAL_NETWORK_CIDRS": "10.42.0.0/20",
        "ACCESS_NETWORK_CIDRS": "10.42.0.0/20",
        "MODEL_BROKER_GUEST_CIDRS": "10.42.0.25/32",
    }.items():
        monkeypatch.setenv(key, value)
    run = SimpleNamespace(
        request_id=str(UUID(int=1)),
        operation_id=str(UUID(int=2)),
        input=_projection(plan=_open_network_plan(), range_backend="ec2", resource_generation=str(UUID(int=3))),
    )
    ec2, secrets = Mock(), Mock()
    clients = Mock(side_effect=lambda scope: nullcontext((ec2, secrets)))
    reserve = Mock(return_value={"subnets": [{"uuid": "backend.ec2.network.default", "cidr": "10.50.1.0/28"}]})
    apply = Mock(return_value={"instances": []})
    monkeypatch.setattr(runtime, "_clients", clients)
    monkeypatch.setattr(runtime, "_reserve_range_subnet_cidrs", reserve)
    monkeypatch.setattr(runtime, "apply_raes_ec2_range", apply)
    return run, clients, reserve, apply, secrets


def test_dispatch_uses_current_operation_for_allocation_and_retained_epoch_for_cloud_ownership(configured):
    run, clients, reserve, apply, _ = configured
    runtime.provision_ec2_run(run)
    assert reserve.call_args.kwargs["operation_id"] == run.operation_id
    assert clients.call_args.args[0].generation == UUID(int=3)
    options = apply.call_args.args[4]
    assert options.generation == UUID(int=3)
    assert options.config.broker_cidrs == ()
    assert options.allocated_cidrs == {"backend.ec2.network.default": "10.50.1.0/28"}


def test_wrong_provider_cannot_allocate_or_open_cloud_clients(configured, monkeypatch):
    run, clients, reserve, _, _ = configured
    monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
    with pytest.raises(ValueError):
        runtime.provision_ec2_run(run)
    clients.assert_not_called()
    reserve.assert_not_called()


def test_model_enrollment_needs_an_exact_applied_listener_before_allocation(configured, monkeypatch):
    run, clients, reserve, _, _ = configured
    monkeypatch.setenv("MODEL_BROKER_GUEST_CIDRS", "10.42.0.0/20")
    with pytest.raises(ValueError):
        runtime.provision_ec2_run(run, enrollment=Mock())
    clients.assert_not_called()
    reserve.assert_not_called()


@pytest.mark.parametrize("outcome", ["VERIFIED_ABSENT", "RESIDUALS_FOUND", "INCOMPLETE"])
def test_cleanup_does_not_need_broker_settings_and_releases_only_after_absence(configured, monkeypatch, outcome):
    run, _clients, _, _, secrets = configured
    run = SimpleNamespace(**{**vars(run), "operation_id": str(UUID(int=4))})
    for key in ("MODEL_BROKER_GUEST_CIDRS", "PORTAL_NETWORK_CIDRS", "ACCESS_NETWORK_CIDRS", "RANGE_ROUTE_TABLE_ID"):
        monkeypatch.delenv(key)
    destroy = Mock(return_value={"outcome": outcome, "scope": {}, "residual_categories": []})
    release = Mock()
    monkeypatch.setattr(runtime, "destroy_ec2_resources", destroy)
    monkeypatch.setattr(runtime, "_release_subnet_allocations_best_effort", release)
    assert runtime.destroy_ec2_run(run)["outcome"] == outcome
    assert destroy.call_args.args[0].generation == UUID(int=3)
    assert release.called == (outcome == "VERIFIED_ABSENT")
    assert secrets.delete.called == (outcome == "VERIFIED_ABSENT")
    if release.called:
        assert release.call_args.kwargs["operation_id"] == str(UUID(int=4))


@pytest.mark.parametrize("outcome", ["VERIFIED_ABSENT", "RESIDUALS_FOUND", "INCOMPLETE"])
def test_failed_launch_releases_reservation_only_after_independent_absence(configured, monkeypatch, outcome):
    run, _, _, apply, secrets = configured
    failure = RuntimeError("guest verification failed")
    apply.side_effect = failure
    inventory = Mock(return_value={"outcome": outcome})
    release = Mock()
    monkeypatch.setattr(runtime, "inventory_ec2_resources", inventory, raising=False)
    monkeypatch.setattr(runtime, "_release_subnet_allocations_best_effort", release)
    with pytest.raises(RuntimeError) as caught:
        runtime.provision_ec2_run(run)
    assert caught.value is failure
    inventory.assert_called_once()
    assert inventory.call_args.args[0].generation == UUID(int=3)
    assert release.called == (outcome == "VERIFIED_ABSENT")
    assert secrets.delete.called == (outcome == "VERIFIED_ABSENT")
    if release.called:
        release.assert_called_once_with(run.request_id, operation_id=run.operation_id)


def test_client_construction_failure_cannot_reserve_capacity(configured):
    run, clients, reserve, apply, _ = configured
    clients.side_effect = RuntimeError("client unavailable")
    with pytest.raises(RuntimeError, match="client unavailable"):
        runtime.provision_ec2_run(run)
    reserve.assert_not_called()
    apply.assert_not_called()


def test_allowlist_is_rejected_before_allocation(configured):
    run, clients, reserve, apply, _ = configured
    run.input = _projection(
        plan=_open_network_plan(), range_backend="ec2", resource_generation=str(UUID(int=3)), egress_mode="allowlist"
    )
    with pytest.raises(ValueError, match="allowlist"):
        runtime.provision_ec2_run(run)
    clients.assert_not_called()
    reserve.assert_not_called()
    apply.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["inventory", "credentials"])
def test_failed_launch_cleanup_error_preserves_failure_and_reservation(configured, monkeypatch, failure_stage):
    run, _, _, apply, secrets = configured
    failure = RuntimeError("guest configuration failed")
    apply.side_effect = failure
    inventory = Mock(return_value={"outcome": "VERIFIED_ABSENT"})
    if failure_stage == "inventory":
        inventory.side_effect = RuntimeError("inventory unavailable")
    else:
        secrets.delete.side_effect = RuntimeError("credential retirement unavailable")
    release = Mock()
    monkeypatch.setattr(runtime, "inventory_ec2_resources", inventory)
    monkeypatch.setattr(runtime, "_release_subnet_allocations_best_effort", release)
    with pytest.raises(RuntimeError) as caught:
        runtime.provision_ec2_run(run)
    assert caught.value is failure
    release.assert_not_called()
