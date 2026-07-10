"""Behavior tests for CmsAcesDispatchPort (ADR-031, ADR-032, ADR-024).

The concrete dispatch port hands a serialized ACES plan to the engine ACES range
service against a real database. ECS is unconfigured so dispatch is a no-op;
assertions are on the returned ``ShifterDispatchResult`` and the persisted
``Range``. The port imports only ``shared`` + the public ``engine.services``
facade (no ``aces_*`` packages, no cyberscript), keeping the SDL tooling confined
to ``shared.aces`` (ADR-024, ADR-031-R1). The persisted ``range_config`` is the
serialized ACES plan (self-describing via its ``kind``).
"""

from uuid import uuid4

import pytest
from aces_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain
from django.contrib.auth import get_user_model

from cms.aces.dispatch import CmsAcesDispatchPort
from engine.models import Range
from shared.aces.dispatch_port import ShifterDispatchResult, ShifterProvisioningDispatchPort
from shared.aces.runtime_target import ACES_PROVISIONING_PLAN_KIND, serialize_provisioning_plan

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_compiled_plan() -> dict:
    network = PlannedResource(
        address="net.default",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="network",
        payload={"name": "default", "spec": {"infrastructure": {"properties": {"cidr": "10.0.0.0/24"}}}},
    )
    node = PlannedResource(
        address="node.attacker",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="node",
        payload={
            "name": "attacker",
            "os_family": "linux",
            "spec": {
                "node": {"source": {"name": "kali"}, "resources": {"ram": 2147483648, "cpu": 2}},
                "infrastructure": {"networks": ["net.default"]},
            },
        },
    )
    plan = ProvisioningPlan(resources={network.address: network, node.address: node})
    return serialize_provisioning_plan(plan)


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cms-aces@example.com", email="cms-aces@example.com")


class TestCmsAcesDispatchPort:
    @pytest.fixture(autouse=True)
    def _ecs_noop(self, settings):
        # Dispatch is a no-op (no local provisioner, no ECS cluster) so realize()
        # accepts + persists the range without a cloud boundary mock.
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = ""
        settings.ENGINE_ECS_CLUSTER_ARN = ""

    def test_satisfies_dispatch_port_protocol(self, user):
        port = CmsAcesDispatchPort(user_id=user.id, request_id=str(uuid4()))
        assert isinstance(port, ShifterProvisioningDispatchPort)

    def test_realize_returns_accepted_result(self, user):
        request_id = uuid4()
        port = CmsAcesDispatchPort(user_id=user.id, request_id=str(request_id))

        result = port.realize(make_compiled_plan())

        assert isinstance(result, ShifterDispatchResult)
        assert result.request_id == str(request_id)
        assert result.accepted is True
        assert result.status == Range.Status.PROVISIONING
        assert result.range_id

    def test_realize_persists_range_with_serialized_plan(self, user):
        request_id = uuid4()
        port = CmsAcesDispatchPort(user_id=user.id, request_id=str(request_id))

        result = port.realize(make_compiled_plan())

        range_obj = Range.objects.get()
        assert str(range_obj.uuid) == result.range_id
        assert range_obj.user == user
        assert range_obj.status == Range.Status.PROVISIONING
        # Serialized ACES plan (self-describing via kind); no cyberscript envelope.
        assert range_obj.range_config["kind"] == ACES_PROVISIONING_PLAN_KIND
        assert range_obj.range_config["resources"]["node.attacker"]["resource_type"] == "node"
