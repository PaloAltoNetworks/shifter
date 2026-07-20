"""Behavior tests for create_aces_range() (ADR-031, ADR-032, ACES-native path).

Drives the real engine service against a real database: the serialized ACES
ProvisioningPlan is persisted as a ``Request`` + ``Range`` keyed by ``request_id``
(in the reused ``range_config`` column, self-describing via its ``kind`` -- no
cyberscript envelope, no Shifter-owned spec), an ``operation_receipt`` sidecar is
written, and the provisioner ``aces-range`` provision task is dispatched. ECS is
unconfigured so dispatch is a no-op needing no boundary mock; the failure test
mocks the ECS client at the ``boto3`` boundary. The cyberscript ``create_range()``
body is untouched (ADR-031-R2).
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from aces_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain
from django.contrib.auth import get_user_model

from engine.models import AcesContentDeliveryBinding, Range
from engine.services import AcesRangeRef, create_aces_range
from shared.aces.content_delivery import DeliveryBinding
from shared.aces.runtime_target import ACES_PROVISIONING_PLAN_KIND, serialize_provisioning_plan
from shared.cloud.exceptions import CloudTaskError
from shared.models import AcesOperationRecord

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_compiled_plan() -> dict:
    """Serialize a small real ACES ProvisioningPlan (1 network + 1 node)."""
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
    return User.objects.create_user(username="aces-range@example.com", email="aces-range@example.com")


class TestCreateAcesRange:
    @pytest.fixture(autouse=True)
    def _ecs_noop(self, settings):
        # No local provisioner and no ECS cluster: dispatch is a no-op (returns
        # None), so the created range stays PROVISIONING without a boundary mock.
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = ""
        settings.ENGINE_ECS_CLUSTER_ARN = ""

    def test_returns_accepted_ref(self, user):
        request_id = uuid4()
        result = create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())
        assert isinstance(result, AcesRangeRef)
        assert result.request_id == str(request_id)
        assert result.accepted is True
        assert result.status == Range.Status.PROVISIONING
        assert result.range_id

    def test_persists_range_with_serialized_plan_and_request(self, user):
        request_id = uuid4()
        plan = make_compiled_plan()
        create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=plan)

        range_obj = Range.objects.get()
        assert range_obj.user == user
        assert range_obj.cms_user_id == user.id
        assert range_obj.status == Range.Status.PROVISIONING
        assert range_obj.subnet_index is not None
        assert range_obj.subnet_index >= Range.SUBNET_INDEX_MIN
        assert str(range_obj.request.request_id) == str(request_id)
        # range_config is the serialized ACES plan, self-describing via its kind;
        # no cyberscript envelope, no Shifter-owned spec.
        assert range_obj.range_config == plan
        assert range_obj.range_config["kind"] == ACES_PROVISIONING_PLAN_KIND
        assert "provision.node.attacker" in range_obj.range_config["resources"]

    def test_writes_operation_receipt_sidecar(self, user):
        request_id = uuid4()
        create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())

        receipt = AcesOperationRecord.objects.get(
            request_id=request_id, record_kind=AcesOperationRecord.RecordKind.OPERATION_RECEIPT
        )
        assert receipt.operation_id == str(request_id)
        assert receipt.payload["accepted"] is True

    def test_idempotent_on_request_id(self, user):
        request_id = uuid4()
        plan = make_compiled_plan()
        first = create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=plan)
        second = create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=plan)

        assert second.range_id == first.range_id
        assert Range.objects.count() == 1


class TestCreateAcesRangeDeliveryBindings:
    """Delivery-binding persistence beside the ACES range (#1564).

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
            storage_key=f"aces-content/aa/{'a' * 64}",
            byte_count=1024,
        )

    def test_persists_one_row_per_binding(self, user):
        request_id = uuid4()
        binding = self.make_binding()
        create_aces_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=make_compiled_plan(),
            delivery_bindings=(binding,),
        )

        range_obj = Range.objects.get(request__request_id=request_id)
        rows = AcesContentDeliveryBinding.objects.filter(range=range_obj)
        assert rows.count() == 1
        row = rows.get()
        assert row.content_address == binding.content_address
        assert row.sha256 == binding.sha256
        assert row.storage_key == binding.storage_key
        assert row.byte_count == binding.byte_count
        assert row.binding_version == binding.binding_version

    def test_no_bindings_persists_none(self, user):
        request_id = uuid4()
        create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())

        range_obj = Range.objects.get(request__request_id=request_id)
        assert AcesContentDeliveryBinding.objects.filter(range=range_obj).count() == 0

    def test_idempotent_on_request_id_does_not_duplicate(self, user):
        request_id = uuid4()
        plan = make_compiled_plan()
        binding = self.make_binding()
        create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=plan, delivery_bindings=(binding,))
        create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=plan, delivery_bindings=(binding,))

        range_obj = Range.objects.get(request__request_id=request_id)
        assert AcesContentDeliveryBinding.objects.filter(range=range_obj).count() == 1

    def test_multiple_bindings_persist_multiple_rows(self, user):
        request_id = uuid4()
        first = self.make_binding("provision.node.attacker#file")
        second = self.make_binding("provision.node.victim#file")
        create_aces_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=make_compiled_plan(),
            delivery_bindings=(first, second),
        )

        range_obj = Range.objects.get(request__request_id=request_id)
        addresses = set(
            AcesContentDeliveryBinding.objects.filter(range=range_obj).values_list("content_address", flat=True)
        )
        assert addresses == {first.content_address, second.content_address}


@pytest.mark.django_db
class TestCreateAcesRangeDispatchFailure:
    def test_marks_range_failed_when_dispatch_fails(self, user, settings):
        settings.CLOUD_PROVIDER = "aws"
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
        ecs_client = MagicMock()
        ecs_client.run_task.return_value = {"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]}

        request_id = uuid4()
        compiled_plan = make_compiled_plan()
        with patch("boto3.client", return_value=ecs_client), pytest.raises(CloudTaskError):
            create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=compiled_plan)

        range_obj = Range.objects.get(request__request_id=request_id)
        assert range_obj.status == Range.Status.FAILED
        assert range_obj.error_message == "Provisioning dispatch failed"
