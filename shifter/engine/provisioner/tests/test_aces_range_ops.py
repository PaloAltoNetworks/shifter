"""Tests for the ACES-native range lifecycle entry (ADR-031, ADR-032).

Exercises run_aces_range_provision/destroy: it reads the serialized ACES plan,
drives the GCE apply/destroy, and publishes range lifecycle status through the
neutral event seam. The GCE apply/destroy and the DB read are patched, so this
verifies the orchestration flow (status transitions, failure handling, resolver
wiring), not the cloud calls (covered by test_aces_gcp_apply).
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import aces_range_ops
from aces_plan import ACES_PROVISIONING_PLAN_CONTRACT_VERSION, AcesPlan, AcesPlanImage, AcesPlanNode
from config import GCERangeImageProfile


def _serialized_plan() -> dict:
    return {
        "kind": "aces_provisioning_plan",
        "contract_version": ACES_PROVISIONING_PLAN_CONTRACT_VERSION,
        "aces_sdl_version": "0.19.1",
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
                    "spec": {"node": {"source": "ubuntu"}, "infrastructure": {"networks": ["net.lan"]}},
                },
            },
        },
    }


_DELIVERY_BINDINGS = [
    {
        "content_address": "content.c",
        "sha256": "a" * 64,
        "storage_key": "aces/content-delivery/aa/" + "a" * 64,
        "byte_count": 5,
        "binding_version": 1,
    }
]


@pytest.fixture
def patched(monkeypatch):
    calls = SimpleNamespace(
        apply=MagicMock(),
        destroy=MagicMock(),
        status=MagicMock(),
        ready=MagicMock(),
        failed=MagicMock(),
        destroyed=MagicMock(),
        aces_operation=MagicMock(),
        aces_snapshot=MagicMock(),
        delivery_bindings=MagicMock(return_value=_DELIVERY_BINDINGS),
    )
    monkeypatch.setattr(
        aces_range_ops,
        "get_aces_range_data_by_request_id",
        lambda request_id: {"range_id": 7, "user_id": 3, "plan": _serialized_plan()},
    )
    monkeypatch.setattr(aces_range_ops, "get_aces_content_delivery_bindings_by_request_id", calls.delivery_bindings)
    monkeypatch.setattr(aces_range_ops, "apply_aces_range_cell", calls.apply)
    monkeypatch.setattr(aces_range_ops, "destroy_aces_range_cell", calls.destroy)
    monkeypatch.setattr(aces_range_ops, "publish_status_update", calls.status)
    monkeypatch.setattr(aces_range_ops, "publish_ready", calls.ready)
    monkeypatch.setattr(aces_range_ops, "publish_failed", calls.failed)
    monkeypatch.setattr(aces_range_ops, "publish_destroyed", calls.destroyed)
    monkeypatch.setattr(aces_range_ops, "publish_aces_operation", calls.aces_operation)
    monkeypatch.setattr(aces_range_ops, "publish_aces_snapshot", calls.aces_snapshot)
    return calls


class TestProvision:
    def test_publishes_provisioning_then_ready_and_applies(self, patched):
        aces_range_ops.run_aces_range_provision("req-1")
        patched.status.assert_called_once_with(request_id="req-1", range_id=7, user_id=3, new_status="provisioning")
        assert patched.apply.called
        request_id, range_id, aces_plan = patched.apply.call_args.args[:3]
        assert (request_id, range_id) == ("req-1", 7)
        # The *parsed* AcesPlan is forwarded to realization, not the raw range_config
        # dict -- a refactor that skipped parse_plan before dispatch must fail here.
        assert isinstance(aces_plan, AcesPlan)
        assert [n.address for n in aces_plan.nodes] == ["node.web"]
        patched.ready.assert_called_once_with(request_id="req-1", range_id=7, user_id=3)
        assert not patched.failed.called

    def test_reads_and_forwards_content_delivery_bindings(self, patched):
        # #1564: the delivery bindings are read once per provision and threaded
        # through to apply_aces_range_cell so it can gate + realize source-backed
        # content delivery.
        aces_range_ops.run_aces_range_provision("req-1")
        patched.delivery_bindings.assert_called_once_with("req-1")
        assert patched.apply.call_args.kwargs["delivery_bindings"] == _DELIVERY_BINDINGS

    def test_emits_aces_operation_and_snapshot_on_success(self, patched):
        aces_range_ops.run_aces_range_provision("req-1")
        statuses = [c.kwargs["status"] for c in patched.aces_operation.call_args_list]
        assert statuses == ["running", "succeeded"]
        assert patched.aces_operation.call_args_list[0].kwargs["operation_id"] == "req-1"
        # snapshot emitted with the bounded resources for the plan (1 network + 1 node).
        assert patched.aces_snapshot.called
        resources = patched.aces_snapshot.call_args.kwargs["resources"]
        assert {r["resource_type"] for r in resources} == {"network", "node"}

    def test_failure_publishes_failed_and_reraises(self, patched):
        patched.apply.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            aces_range_ops.run_aces_range_provision("req-1")
        assert patched.failed.called
        assert patched.failed.call_args.kwargs["error_message"].startswith("boom")
        assert not patched.ready.called
        # ACES operation ends 'failed'; no snapshot on failure.
        assert patched.aces_operation.call_args_list[-1].kwargs["status"] == "failed"
        assert not patched.aces_snapshot.called


class TestDestroy:
    def test_destroys_and_publishes_destroyed(self, patched):
        aces_range_ops.run_aces_range_destroy("req-1")
        assert patched.destroy.called
        request_id, range_id, aces_plan = patched.destroy.call_args.args[:3]
        assert (request_id, range_id) == ("req-1", 7)
        # Destroy receives the parsed AcesPlan too, not the raw range_config dict.
        assert isinstance(aces_plan, AcesPlan)
        assert [n.address for n in aces_plan.nodes] == ["node.web"]
        patched.destroyed.assert_called_once_with(request_id="req-1", range_id=7, user_id=3)

    def test_failure_publishes_failed_and_reraises(self, patched):
        patched.destroy.side_effect = RuntimeError("kaboom")
        with pytest.raises(RuntimeError, match="kaboom"):
            aces_range_ops.run_aces_range_destroy("req-1")
        assert patched.failed.called
        assert patched.failed.call_args.kwargs["error_message"].startswith("kaboom")


def _node(image: AcesPlanImage | None) -> AcesPlanNode:
    return AcesPlanNode(
        address="node.web", name="web", os_family="linux", count=1, network_addresses=("net.lan",), image=image
    )


class TestRegistryResolver:
    def test_resolver_wires_registry_candidates_to_policy(self, monkeypatch):
        candidates = [{"source_version": None, "image_ref": "projects/x/global/images/ubuntu-1"}]
        get_candidates = MagicMock(return_value=candidates)
        resolve = MagicMock(return_value=GCERangeImageProfile(source_image="projects/x/global/images/ubuntu-1"))
        monkeypatch.setattr(aces_range_ops, "get_aces_image_candidates", get_candidates)
        monkeypatch.setattr(aces_range_ops, "resolve_gce_image", resolve)

        node = _node(AcesPlanImage(name="ubuntu"))
        profile = aces_range_ops._registry_resolver()(node)

        get_candidates.assert_called_once_with("gce", "ubuntu")
        resolve.assert_called_once_with(node, candidates)
        assert profile.source_image == "projects/x/global/images/ubuntu-1"

    def test_resolver_uses_os_family_for_source_less_node(self, monkeypatch):
        # A source-less node looks up a base OS image by os_family (ADR-032).
        candidates = [{"source_version": "", "image_ref": "projects/x/global/images/ubuntu-base"}]
        get_candidates = MagicMock(return_value=candidates)
        resolve = MagicMock(return_value=GCERangeImageProfile())
        monkeypatch.setattr(aces_range_ops, "get_aces_image_candidates", get_candidates)
        monkeypatch.setattr(aces_range_ops, "resolve_gce_image", resolve)

        node = _node(None)  # os_family linux, no image
        aces_range_ops._registry_resolver()(node)

        get_candidates.assert_called_once_with("gce", "linux")
        resolve.assert_called_once_with(node, candidates)
