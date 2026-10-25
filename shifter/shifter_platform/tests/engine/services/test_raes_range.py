"""Behavior tests for _create_raes_range() (ADR-031, ADR-032, RAES-native path).

Drives the real engine service against a real database: the serialized RAES
ProvisioningPlan is persisted as a ``Request`` + ``Range`` keyed by ``request_id``
(in the reused ``range_config`` column, self-describing via its ``kind`` -- no
cyberscript envelope, no Shifter-owned spec), an ``operation_receipt`` sidecar is
written, and the provisioner ``raes-range`` provision task is dispatched. ECS is
unconfigured so dispatch is a no-op needing no boundary mock. The cyberscript
``create_range()`` body is untouched (ADR-031-R2).
"""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from raes_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain

from engine.models import RaesContentDeliveryBinding, Range
from engine.services import RaesRangeRef, RangeBindings, create_raes_range
from shared.models import RaesOperationRecord
from shared.raes.artifact_binding import ArtifactBinding
from shared.raes.content_delivery import DeliveryBinding
from shared.raes.runtime_target import RAES_PROVISIONING_PLAN_KIND, serialize_provisioning_plan

# Opaque #1325 workspace scope binding. engine.services requires one on every
# range create (ADR-046-R3); these suites do not exercise tenancy, so a fixed
# scalar stands in for the value the CMS launch facade would resolve.
_WORKSPACE_ID = 1


def _create_raes_range(**kwargs):
    """Call the real seam, assembling the grouped bindings these suites pass by name."""
    kwargs.setdefault("workspace_id", _WORKSPACE_ID)
    bindings = RangeBindings(
        delivery=kwargs.pop("delivery_bindings", ()),
        participant_access=kwargs.pop("participant_access", ()),
        artifact=kwargs.pop("artifact_bindings", ()),
    )
    return create_raes_range(bindings=bindings, **kwargs)


pytestmark = pytest.mark.django_db

User = get_user_model()


def make_compiled_plan() -> dict:
    """Serialize a small real RAES ProvisioningPlan (1 network + 1 node)."""
    network = PlannedResource(
        address="provision.network.default",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="network",
        payload={"name": "default", "spec": {"infrastructure": {"properties": {"cidr": "10.0.0.0/24"}}}},
    )
    node = PlannedResource(
        address="provision.node.attacker",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="node",
        payload={
            "name": "attacker",
            "os_family": "linux",
            "spec": {
                "node": {"source": {"name": "kali", "version": "2024.1"}, "resources": {"ram": 2147483648, "cpu": 2}},
                "infrastructure": {"networks": ["provision.network.default"]},
            },
        },
    )
    plan = ProvisioningPlan(resources={network.address: network, node.address: node})
    return serialize_provisioning_plan(plan)


@pytest.fixture
def user(db):
    return User.objects.create_user(username="raes-range@example.com", email="raes-range@example.com")


class TestCreateRaesRange:
    @pytest.fixture(autouse=True)
    def _ecs_noop(self, settings):
        # No local provisioner and no ECS cluster: dispatch is a no-op (returns
        # None), so the created range stays PROVISIONING without a boundary mock.
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = ""
        settings.ENGINE_ECS_CLUSTER_ARN = ""

    def test_returns_accepted_ref(self, user):
        request_id = uuid4()
        result = _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())
        assert isinstance(result, RaesRangeRef)
        assert result.request_id == str(request_id)
        assert result.accepted is True
        assert result.status == Range.Status.PROVISIONING
        assert result.range_id

    def test_absent_dispatch_task_reference_is_not_persisted(self, user, monkeypatch):
        persist_calls = []
        monkeypatch.setattr("engine.services._raes_range.start_raes_range_provisioning", lambda _request_id: None)
        monkeypatch.setattr(
            "engine.services._raes_range._persist_task_arn",
            lambda *args: persist_calls.append(args),
        )

        _create_raes_range(request_id=uuid4(), user_id=user.id, compiled_plan=make_compiled_plan())

        assert persist_calls == []

    def test_persists_range_with_serialized_plan_and_request(self, user):
        request_id = uuid4()
        plan = make_compiled_plan()
        _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=plan)

        range_obj = Range.objects.get()
        assert range_obj.user == user
        assert range_obj.cms_user_id == user.id
        assert range_obj.status == Range.Status.PROVISIONING
        assert range_obj.subnet_index is not None
        assert range_obj.subnet_index >= Range.SUBNET_INDEX_MIN
        assert str(range_obj.request.request_id) == str(request_id)
        # range_config is the serialized RAES plan, self-describing via its kind;
        # no cyberscript envelope, no Shifter-owned spec.
        assert range_obj.range_config == plan
        assert range_obj.range_config["kind"] == RAES_PROVISIONING_PLAN_KIND
        assert "provision.node.attacker" in range_obj.range_config["resources"]

    def test_placement_zone_is_selected_from_the_pool_at_creation(self, user, monkeypatch):
        """#2029: the realized zone is chosen from RANGE_NETWORK_ZONES and stored at
        creation, so the provisioner reads it back and destroy targets it exactly."""
        monkeypatch.setenv("RANGE_NETWORK_ZONES", "us-central1-a,us-east4-a,us-east1-b")
        _create_raes_range(request_id=uuid4(), user_id=user.id, compiled_plan=make_compiled_plan())

        range_obj = Range.objects.get()
        zones = ("us-central1-a", "us-east4-a", "us-east1-b")
        assert range_obj.placement_zone == zones[(range_obj.subnet_index - 1) % len(zones)]

    def test_placement_zone_is_empty_without_a_pool(self, user, monkeypatch):
        """No pool configured -> single-zone placement; the range keeps the scalar
        RANGE_NETWORK_ZONE and stores no realized zone."""
        monkeypatch.delenv("RANGE_NETWORK_ZONES", raising=False)
        _create_raes_range(request_id=uuid4(), user_id=user.id, compiled_plan=make_compiled_plan())

        assert Range.objects.get().placement_zone == ""

    def test_writes_operation_receipt_sidecar(self, user):
        request_id = uuid4()
        _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())

        receipt = RaesOperationRecord.objects.get(
            request_id=request_id, record_kind=RaesOperationRecord.RecordKind.OPERATION_RECEIPT
        )
        assert receipt.operation_id == str(request_id)
        assert receipt.payload["accepted"] is True

    def test_idempotent_on_request_id(self, user):
        request_id = uuid4()
        plan = make_compiled_plan()
        first = _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=plan)
        second = _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=plan)

        assert second.range_id == first.range_id
        assert Range.objects.count() == 1


class TestCreateRaesRangeDeliveryBindings:
    """Delivery-binding persistence beside the RAES range (#1564).

    The engine slice: bindings are byte-free identity rows persisted in the
    same transaction as the Range, keyed by (range, content_address).
    """

    @pytest.fixture(autouse=True)
    def _ecs_noop(self, settings):
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = ""
        settings.ENGINE_ECS_CLUSTER_ARN = ""

    def make_binding(self, address="provision.node.attacker#file") -> DeliveryBinding:
        return DeliveryBinding(
            content_address=address,
            sha256="a" * 64,
            storage_key=f"raes-content/aa/{'a' * 64}",
            byte_count=1024,
        )

    def test_persists_one_row_per_binding(self, user):
        request_id = uuid4()
        binding = self.make_binding()
        _create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=make_compiled_plan(),
            delivery_bindings=(binding,),
        )

        range_obj = Range.objects.get(request__request_id=request_id)
        rows = RaesContentDeliveryBinding.objects.filter(range=range_obj)
        assert rows.count() == 1
        row = rows.get()
        assert row.content_address == binding.content_address
        assert row.sha256 == binding.sha256
        assert row.storage_key == binding.storage_key
        assert row.byte_count == binding.byte_count
        assert row.binding_version == binding.binding_version

    def test_no_bindings_persists_none(self, user):
        request_id = uuid4()
        _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())

        range_obj = Range.objects.get(request__request_id=request_id)
        assert RaesContentDeliveryBinding.objects.filter(range=range_obj).count() == 0

    def test_idempotent_on_request_id_does_not_duplicate(self, user):
        request_id = uuid4()
        plan = make_compiled_plan()
        binding = self.make_binding()
        _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=plan, delivery_bindings=(binding,))
        _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=plan, delivery_bindings=(binding,))

        range_obj = Range.objects.get(request__request_id=request_id)
        assert RaesContentDeliveryBinding.objects.filter(range=range_obj).count() == 1

    def test_multiple_bindings_persist_multiple_rows(self, user):
        request_id = uuid4()
        first = self.make_binding("provision.node.attacker#file")
        second = self.make_binding("provision.node.victim#file")
        _create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=make_compiled_plan(),
            delivery_bindings=(first, second),
        )

        range_obj = Range.objects.get(request__request_id=request_id)
        addresses = set(
            RaesContentDeliveryBinding.objects.filter(range=range_obj).values_list("content_address", flat=True)
        )
        assert addresses == {first.content_address, second.content_address}

    def test_persists_feature_binding_without_legacy_content_address(self, user):
        request_id = uuid4()
        binding = DeliveryBinding(
            content_address=None,
            sha256="b" * 64,
            storage_key=f"raes-content/bb/{'b' * 64}",
            byte_count=2048,
            binding_version=2,
            resource_type="feature-binding",
            resource_address="provision.feature.agent",
            payload_kind="file",
            install_policy="executable",
        )
        _create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=make_compiled_plan(),
            delivery_bindings=(binding,),
        )

        row = RaesContentDeliveryBinding.objects.get(range__request__request_id=request_id)
        assert row.content_address == ""
        assert row.resource_type == "feature-binding"
        assert row.resource_address == "provision.feature.agent"
        assert row.payload_kind == "file"
        assert row.install_policy == "executable"


@pytest.mark.django_db
class TestArtifactBindingPersistence:
    """create_raes_range persists each fenced artifact binding beside the Range (#1580)."""

    @pytest.fixture(autouse=True)
    def _ecs_noop(self, settings):
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = ""
        settings.ENGINE_ECS_CLUSTER_ARN = ""

    def make_binding(self, target="provision.node.web") -> ArtifactBinding:
        return ArtifactBinding(
            image_id="555",
            target=target,
            requirement_id="req-1",
            artifact_id="img-web",
            version="1.0.0",
            digest="sha256:" + "a" * 64,
            media_type="application/vnd.raes.image",
            mechanism="exact-artifact",
            acquisition="local-lookup",
            timing="backend-preparation",
            image_ref="projects/p/global/images/web",
            machine_type="e2-medium",
        )

    def test_persists_one_row_per_binding_with_faithful_fields(self, user):
        from engine.models import RaesArtifactSatisfactionBinding

        request_id = uuid4()
        binding = self.make_binding()
        _create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=make_compiled_plan(),
            artifact_bindings=(binding,),
        )

        row = RaesArtifactSatisfactionBinding.objects.get(range__request__request_id=request_id)
        assert row.target_address == binding.target
        assert row.digest == binding.digest
        assert row.image_ref == binding.image_ref
        assert row.image_id == "555"
        assert row.mechanism == "exact-artifact"
        assert row.artifact_version == "1.0.0"

    def test_no_bindings_persists_none(self, user):
        from engine.models import RaesArtifactSatisfactionBinding

        request_id = uuid4()
        _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())

        range_obj = Range.objects.get(request__request_id=request_id)
        assert RaesArtifactSatisfactionBinding.objects.filter(range=range_obj).count() == 0


# The old synchronous "provider dispatch failed -> range FAILED" path no
# longer exists: dispatch enqueues a launch intent and the drainer owns
# provider-dispatch failure (DLQ -> FAILED), covered by
# tests/engine/test_provisioner_launch_outbox.py (ADR-043-R2, #1833).


def test_ec2_allowlist_denied_before_engine_request_or_dispatch(user, monkeypatch):
    from unittest.mock import Mock

    from engine.models import Request
    from engine.services._common import EngineError
    from shared.range_instantiation_policy import InstantiationPurpose, evaluate_range_backend_admission

    dispatch = Mock(return_value=None)
    monkeypatch.setattr("engine.services._raes_range.start_raes_range_provisioning", dispatch)
    request_id = uuid4()
    with pytest.raises(EngineError, match="allowlist"):
        _create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=make_compiled_plan(),
            backend_admission=evaluate_range_backend_admission("ec2", InstantiationPurpose.LIVE_FIRE),
            egress_mode="allowlist",
        )
    assert not Request.objects.filter(request_id=request_id).exists()
    dispatch.assert_not_called()
