"""Behavior tests for CmsRaesDispatchPort (ADR-031, ADR-032, ADR-024).

The concrete dispatch port hands a serialized RAES plan to the engine RAES range
service against a real database. ECS is unconfigured so dispatch is a no-op;
assertions are on the returned ``ShifterDispatchResult`` and the persisted
``Range``. The port imports only ``shared`` + the public ``engine.services``
facade (no ``raes_*`` packages, no cyberscript), keeping the SDL tooling confined
to ``shared.raes`` (ADR-024, ADR-031-R1). The persisted ``range_config`` is the
serialized RAES plan (self-describing via its ``kind``).
"""

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from raes_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain

from cms.raes.dispatch import CmsRaesDispatchPort
from engine.models import RaesParticipantAccessBinding, Range
from shared.raes.dispatch_port import ShifterDispatchResult, ShifterProvisioningDispatchPort
from shared.raes.participant_access import ParticipantAccessBinding
from shared.raes.runtime_target import RAES_PROVISIONING_PLAN_KIND, serialize_provisioning_plan

# Opaque #1325 workspace scope binding; this suite does not exercise tenancy.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_compiled_plan() -> dict:
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
                "node": {"source": {"name": "kali"}, "resources": {"ram": 2147483648, "cpu": 2}},
                "infrastructure": {"networks": ["provision.network.default"]},
            },
        },
    )
    plan = ProvisioningPlan(resources={network.address: network, node.address: node})
    return serialize_provisioning_plan(plan)


def _compiled_plan_with_source_backed_content() -> dict:
    """A serialized plan carrying one source-backed content placement (#1564)."""
    node = PlannedResource(
        address="provision.node.web",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="node",
        payload={
            "name": "web",
            "os_family": "linux",
            "spec": {
                "node": {"source": {"name": "base-linux"}, "resources": {"ram": 2147483648, "cpu": 2}},
                "infrastructure": {"networks": []},
            },
        },
    )
    content = PlannedResource(
        address="provision.content.flag",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="content-placement",
        payload={
            "content_name": "flag",
            "target_address": "provision.node.web",
            "spec": {"type": "file", "path": "/opt/flag", "source": {"name": "flag-pkg", "version": "1.0.0"}},
        },
    )
    plan = ProvisioningPlan(resources={node.address: node, content.address: content})
    return serialize_provisioning_plan(plan)


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cms-raes@example.com", email="cms-raes@example.com")


class TestCmsRaesDispatchPort:
    @pytest.fixture(autouse=True)
    def _ecs_noop(self, settings):
        # Dispatch is a no-op (no local provisioner, no ECS cluster) so realize()
        # accepts + persists the range without a cloud boundary mock.
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = ""
        settings.ENGINE_ECS_CLUSTER_ARN = ""

    def test_satisfies_dispatch_port_protocol(self, user):
        port = CmsRaesDispatchPort(user_id=user.id, workspace_id=_WORKSPACE_ID, request_id=str(uuid4()))
        assert isinstance(port, ShifterProvisioningDispatchPort)

    def test_realize_returns_accepted_result(self, user):
        request_id = uuid4()
        port = CmsRaesDispatchPort(user_id=user.id, workspace_id=_WORKSPACE_ID, request_id=str(request_id))

        result = port.realize(make_compiled_plan())

        assert isinstance(result, ShifterDispatchResult)
        assert result.request_id == str(request_id)
        assert result.accepted is True
        assert result.status == Range.Status.PROVISIONING
        assert result.range_id

    def test_realize_persists_range_with_serialized_plan(self, user):
        request_id = uuid4()
        port = CmsRaesDispatchPort(user_id=user.id, workspace_id=_WORKSPACE_ID, request_id=str(request_id))

        result = port.realize(make_compiled_plan())

        range_obj = Range.objects.get()
        assert str(range_obj.uuid) == result.range_id
        assert range_obj.user == user
        assert range_obj.status == Range.Status.PROVISIONING
        # Serialized RAES plan (self-describing via kind); no cyberscript envelope.
        assert range_obj.range_config["kind"] == RAES_PROVISIONING_PLAN_KIND
        assert range_obj.range_config["resources"]["provision.node.attacker"]["resource_type"] == "node"

    def test_realize_persists_delivery_bindings_for_source_backed_content(self, user, monkeypatch, tmp_path, settings):
        # A plan with source-backed content threads pack_root through the port; the
        # prepared byte-free bindings are persisted beside the plan (#1564).
        import shared.cloud as cloud_module
        import shared.raes.content_delivery_prep as prep
        from engine.models import RaesContentDeliveryBinding
        from shared.raes.content_delivery import DeliveryBinding

        digest = "a" * 64
        binding = DeliveryBinding(
            content_address="provision.content.flag",
            sha256=digest,
            storage_key=f"raes/content-delivery/{digest[:2]}/{digest}",
            byte_count=15,
        )

        # A distinct sentinel (not a real ObjectStorage impl) so the assertion below
        # proves _prepare_delivery threads through *this specific* storage object
        # rather than merely something with the right shape.
        storage_sentinel = object()
        monkeypatch.setattr(cloud_module, "get_object_storage", lambda: storage_sentinel)
        mock_prepare = MagicMock(return_value=(binding,))
        monkeypatch.setattr(prep, "prepare_content_delivery", mock_prepare)

        request_id = uuid4()
        port = CmsRaesDispatchPort(
            user_id=user.id, workspace_id=_WORKSPACE_ID, request_id=str(request_id), pack_root=tmp_path
        )
        compiled_plan = _compiled_plan_with_source_backed_content()
        result = port.realize(compiled_plan)

        assert result.accepted is True
        # _prepare_delivery must thread the live pack root, the serialized plan, and
        # the configured storage identity through to prepare_content_delivery -- a
        # regression here (wrong pack_root, wrong bucket/prefix/limit) would silently
        # break delivery without failing any other test in the diff.
        mock_prepare.assert_called_once_with(
            pack_root=tmp_path,
            serialized_plan=compiled_plan,
            target=prep.DeliveryTarget(
                storage=storage_sentinel,
                bucket=settings.STORAGE_BUCKET_NAME,
                prefix=settings.RAES_CONTENT_DELIVERY_PREFIX,
                max_payload_bytes=settings.RAES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES,
            ),
        )
        rows = list(RaesContentDeliveryBinding.objects.all())
        assert len(rows) == 1
        assert rows[0].content_address == "provision.content.flag"
        assert rows[0].sha256 == digest
        assert rows[0].storage_key == binding.storage_key
        assert rows[0].byte_count == 15
        # The binding carries no bytes / bucket / url; range_config never holds them.
        assert "sha256" not in str(
            Range.objects.get().range_config.get("resources", {}).get("provision.content.flag", {})
        )


class TestParticipantAccessSidecar:
    """The #1710 sidecar rides beside the plan through this port (ADR-032-R10)."""

    @staticmethod
    def _binding(channel: str = "ssh") -> ParticipantAccessBinding:
        return ParticipantAccessBinding(
            target_address="provision.node.attacker",
            channel=channel,
            account_address="provision.account.analyst",
        )

    def test_declared_access_is_persisted_beside_the_range(self, user):
        request_id = uuid4()
        port = CmsRaesDispatchPort(user_id=user.id, workspace_id=_WORKSPACE_ID, request_id=str(request_id))

        port.realize(make_compiled_plan(), (self._binding(),))

        range_obj = Range.objects.get(request__request_id=request_id)
        rows = RaesParticipantAccessBinding.objects.filter(range=range_obj)
        assert [(row.target_address, row.channel, row.account_address) for row in rows] == [
            ("provision.node.attacker", "ssh", "provision.account.analyst")
        ]

    def test_no_declared_access_persists_no_rows(self, user):
        request_id = uuid4()
        port = CmsRaesDispatchPort(user_id=user.id, workspace_id=_WORKSPACE_ID, request_id=str(request_id))

        port.realize(make_compiled_plan())

        range_obj = Range.objects.get(request__request_id=request_id)
        assert not RaesParticipantAccessBinding.objects.filter(range=range_obj).exists()

    def test_the_sidecar_never_enters_the_persisted_plan(self, user):
        request_id = uuid4()
        port = CmsRaesDispatchPort(user_id=user.id, workspace_id=_WORKSPACE_ID, request_id=str(request_id))

        port.realize(make_compiled_plan(), (self._binding(),))

        range_obj = Range.objects.get(request__request_id=request_id)
        assert "account_address" not in json.dumps(range_obj.range_config)
