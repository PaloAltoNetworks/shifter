"""Integration tests for the provision-task interrupt convergence (#277).

Drives the *real* path end to end -- ``cancel_range_by_request`` records the
interrupt, ``drain_due_interrupts`` verifies + stops the task through the real
GCP task runner, and the canonical destroy is enqueued through the real
launch-intent path. Only the external ``kubernetes`` library is mocked (via
``sys.modules``), per ADR-019-R1; every assertion is on observable database
state.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine import cancel_range_by_request
from engine.launch_intents import command_from_payload, enqueue_provisioner_launch
from engine.launch_interrupt import drain_due_interrupts
from engine.models import InterruptState, ProvisionerLaunchIntent, ProvisionerLaunchStatus, Range, Request
from tests.shared.cloud.test_gcp_task_runner import _ApiException, _make_fake_k8s_client, _observed_job

_WORKSPACE_ID = 1
_IMAGE = "provisioner:latest"
_SA = "shifter-provisioner"
pytestmark = pytest.mark.django_db

User = get_user_model()


def _plan() -> dict:
    return {
        "kind": "raes_provisioning_plan",
        "contract_version": "raes-provisioning-plan-v1",
        "raes_version": "2.0.0",
        "resources": {
            "net.lan": {
                "address": "net.lan",
                "resource_type": "network",
                "payload": {"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.9.0.0/24"}}}},
            },
            "node.web": {
                "address": "node.web",
                "resource_type": "node",
                "payload": {
                    "name": "web",
                    "os_family": "linux",
                    "spec": {"node": {"source": "kali"}, "infrastructure": {"networks": ["net.lan"]}},
                },
            },
        },
    }


@pytest.fixture
def gcp_engine(settings):
    settings.CLOUD_PROVIDER = "gcp"
    settings.ENGINE_TASK_CLUSTER = "shifter-platform"
    settings.ENGINE_TASK_DEFINITION = _IMAGE
    settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = _SA
    return settings


def _cancelled_launch(*, status=ProvisionerLaunchStatus.SUCCEEDED):
    """A DESTROYING RAES range whose provision generation is cancelled (real path)."""
    rid = uuid4()
    user = User.objects.create_user(username=f"intr-{rid}@example.com")
    request = Request.objects.create(request_id=rid, request_type="range", user=user)
    Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        status=Range.Status.PROVISIONING,
        range_config=_plan(),
        range_backend="gce",
        instantiation_purpose="training",
    )
    ref = enqueue_provisioner_launch(["raes-range", "provision", "--request-id", str(rid)])
    intent = ProvisionerLaunchIntent.objects.get(intent_id=ref)
    intent.status = status
    intent.save(update_fields=["status"])
    assert cancel_range_by_request(rid) is True  # real cancel records the interrupt
    intent.refresh_from_db()
    assert intent.interrupt_state == InterruptState.REQUESTED
    return rid, intent


def _observed_for(intent, *, image=_IMAGE):
    command = command_from_payload({**intent.payload, "operation_id": str(intent.operation_id)})
    return _observed_job(task_identity=str(intent.intent_id), image=image, command=command, service_account_name=_SA)


def _fake_kubernetes(batch, core):
    """A stand-in ``kubernetes`` module so the real GCP runner path executes.

    Mocking the library itself -- the external cloud boundary -- rather than any
    first-party helper keeps this ADR-019-R1 compliant.
    """
    client_ns = _make_fake_k8s_client()
    client_ns.BatchV1Api = lambda: batch
    client_ns.CoreV1Api = lambda: core
    client_ns.exceptions = SimpleNamespace(ApiException=_ApiException)
    client_ns.V1DeleteOptions = lambda **kw: SimpleNamespace(**kw)
    config_ns = SimpleNamespace(
        load_incluster_config=lambda: None,
        load_kube_config=lambda: None,
        config_exception=SimpleNamespace(ConfigException=Exception),
    )
    return SimpleNamespace(config=config_ns, client=client_ns)


def _patch_k8s(*, observed="absent", pods=0):
    batch = MagicMock()
    core = MagicMock()
    if observed == "absent":
        batch.read_namespaced_job.side_effect = _ApiException(404)
    else:
        batch.read_namespaced_job.return_value = observed
    core.list_namespaced_pod.return_value = SimpleNamespace(items=[SimpleNamespace() for _ in range(pods)])
    patcher = patch.dict(sys.modules, {"kubernetes": _fake_kubernetes(batch, core)})
    return patcher, batch


def _range_op(rid):
    return Range.objects.get(request__request_id=rid).provisioner_operation


class TestInterruptConvergence:
    def test_running_task_stopped_and_destroy_enqueued(self, gcp_engine):
        rid, intent = _cancelled_launch()
        patcher, batch = _patch_k8s(observed=_observed_for(intent), pods=0)
        with patcher:
            assert drain_due_interrupts(10) == 1

        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.DESTROY_ENQUEUED
        assert batch.delete_namespaced_job.call_count == 1
        # The canonical destroy generation was minted through the real path.
        assert _range_op(rid) == "raes-range:destroy"
        assert ProvisionerLaunchIntent.objects.count() == 2

    def test_pods_remaining_reports_stopping_without_destroy(self, gcp_engine):
        rid, intent = _cancelled_launch()
        patcher, batch = _patch_k8s(observed=_observed_for(intent), pods=1)
        with patcher:
            assert drain_due_interrupts(10) == 1

        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.STOPPING
        assert batch.delete_namespaced_job.call_count == 1
        assert _range_op(rid) == "raes-range:provision"  # no destroy yet
        assert ProvisionerLaunchIntent.objects.count() == 1

    def test_identity_mismatch_fails_closed(self, gcp_engine):
        rid, intent = _cancelled_launch()
        patcher, batch = _patch_k8s(observed=_observed_for(intent, image="attacker:evil"), pods=1)
        with patcher:
            assert drain_due_interrupts(10) == 1

        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.IDENTITY_MISMATCH
        batch.delete_namespaced_job.assert_not_called()  # never stop a foreign workload
        assert Range.objects.get(request__request_id=rid).status == Range.Status.DESTROYING
        assert ProvisionerLaunchIntent.objects.count() == 1  # no destroy on mismatch

    def test_absent_task_converges_to_destroy_without_stop(self, gcp_engine):
        rid, intent = _cancelled_launch()
        patcher, batch = _patch_k8s(observed="absent", pods=0)
        with patcher:
            assert drain_due_interrupts(10) == 1

        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.DESTROY_ENQUEUED
        batch.delete_namespaced_job.assert_not_called()
        assert _range_op(rid) == "raes-range:destroy"

    def test_pending_intent_observes_absence_then_destroys(self, gcp_engine):
        # PENDING still reserved a provider identity, so absence is observed (a
        # PENDING retry after an ambiguous dispatch could have created a task).
        rid, intent = _cancelled_launch(status=ProvisionerLaunchStatus.PENDING)
        patcher, batch = _patch_k8s(observed="absent", pods=0)
        with patcher:
            assert drain_due_interrupts(10) == 1

        batch.read_namespaced_job.assert_called_once()  # absence was observed
        batch.delete_namespaced_job.assert_not_called()  # nothing to stop
        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.DESTROY_ENQUEUED
        assert _range_op(rid) == "raes-range:destroy"

    def test_running_status_is_actively_converged(self, gcp_engine):
        # A RUNNING+REQUESTED row must be settled here, not left ownerless.
        rid, intent = _cancelled_launch(status=ProvisionerLaunchStatus.RUNNING)
        patcher, batch = _patch_k8s(observed=_observed_for(intent), pods=0)
        with patcher:
            assert drain_due_interrupts(10) == 1

        batch.delete_namespaced_job.assert_called_once()
        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.DESTROY_ENQUEUED
        assert _range_op(rid) == "raes-range:destroy"

    def test_no_reserved_identity_converges_without_provider_call(self, gcp_engine):
        # Only a never-reserved provider identity may skip terminal-absence observation.
        rid, intent = _cancelled_launch(status=ProvisionerLaunchStatus.PENDING)
        ProvisionerLaunchIntent.objects.filter(pk=intent.pk).update(task_ref="")
        patcher, batch = _patch_k8s()
        with patcher:
            assert drain_due_interrupts(10) == 1

        batch.read_namespaced_job.assert_not_called()
        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.DESTROY_ENQUEUED
        assert _range_op(rid) == "raes-range:destroy"

    def test_deadline_exceeded_exhausts_fail_closed(self, gcp_engine):
        rid, intent = _cancelled_launch()
        # Past the bounded deadline while the task is still stopping.
        ProvisionerLaunchIntent.objects.filter(pk=intent.pk).update(
            interrupt_deadline=timezone.now() - timedelta(seconds=1)
        )
        patcher, _batch = _patch_k8s(observed=_observed_for(intent), pods=1)  # -> STOPPING
        with patcher:
            assert drain_due_interrupts(10) == 1

        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.EXHAUSTED
        assert intent.interrupt_last_error  # operator signal recorded
        # Fail closed: never destroyed when absence was not confirmed.
        assert Range.objects.get(request__request_id=rid).status == Range.Status.DESTROYING
        assert _range_op(rid) == "raes-range:provision"

    def test_terminal_state_not_reclaimed(self, gcp_engine):
        _rid, _intent = _cancelled_launch(status=ProvisionerLaunchStatus.PENDING)
        patcher, _batch = _patch_k8s()
        with patcher:
            drain_due_interrupts(10)  # -> DESTROY_ENQUEUED
            # A second sweep must not re-claim the terminal interrupt.
            assert drain_due_interrupts(10) == 0
