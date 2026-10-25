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
from unittest import mock
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
        # regression here (wrong pack_root, wrong bucket/prefix) would silently
        # break delivery without failing any other test in the diff.
        mock_prepare.assert_called_once_with(
            pack_root=tmp_path,
            serialized_plan=compiled_plan,
            target=prep.DeliveryTarget(
                storage=storage_sentinel,
                bucket=settings.STORAGE_BUCKET_NAME,
                prefix=settings.RAES_CONTENT_DELIVERY_PREFIX,
            ),
            acquire_feature=mock.ANY,
        )
        # Unprojected feature sources resolve through the recipe-acquisition resolver (#2463).
        assert callable(mock_prepare.call_args.kwargs["acquire_feature"])
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


class TestOpenVpnAdmission:
    """The port admits participant OpenVPN against the launch's lease ceiling (#2030)."""

    _NODE = "provision.node.attacker"

    @pytest.fixture(autouse=True)
    def _ecs_noop(self, settings):
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = ""
        settings.ENGINE_ECS_CLUSTER_ARN = ""
        settings.RANGE_OPENVPN_ENABLED = True

    @staticmethod
    def _gce():
        from shared.range_instantiation_policy import BackendAdmission, InstantiationPurpose

        return BackendAdmission(True, "gce", InstantiationPurpose.LIVE_FIRE, "", "")

    def _launch(self, user, *, lease_ceiling, backend_admission) -> Range:
        from cms.models import RangeInstance, Request
        from shared.enums import RequestType

        request_id = uuid4()
        cms_request = Request.objects.create(
            request_id=request_id, request_type=RequestType.RANGE.value, user=user, workspace_id=_WORKSPACE_ID
        )
        RangeInstance.objects.create(
            request=cms_request,
            scenario_id="ctf-openvpn-test",
            user_id=user.id,
            workspace_id=_WORKSPACE_ID,
            range_source="ctf",
            range_spec=None,
            expires_at=lease_ceiling,
            maximum_expires_at=lease_ceiling,
        )
        port = CmsRaesDispatchPort(
            user_id=user.id,
            workspace_id=_WORKSPACE_ID,
            request_id=str(request_id),
            backend_admission=backend_admission,
        )
        access = (
            ParticipantAccessBinding(target_address=self._NODE, channel="rdp", account_address="provision.account.a"),
        )
        port.realize(make_compiled_plan(), access)
        return Range.objects.get(request__request_id=request_id)

    def test_an_admitted_launch_mints_vpn_bounded_by_the_lease_ceiling(self, user):
        from datetime import UTC, datetime, timedelta

        ceiling = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)
        range_obj = self._launch(user, lease_ceiling=ceiling, backend_admission=self._gce())

        assert range_obj.remote_access_capability["target_ref"] == f"{self._NODE}#0"
        assert range_obj.remote_access_capability["teardown_at"] == ceiling.isoformat().replace("+00:00", "Z")

    def test_a_launch_without_a_lease_ceiling_mints_nothing(self, user):
        range_obj = self._launch(user, lease_ceiling=None, backend_admission=self._gce())
        assert range_obj.remote_access_capability is None

    def test_the_deployment_must_opt_in(self, user, settings):
        from datetime import UTC, datetime, timedelta

        settings.RANGE_OPENVPN_ENABLED = False
        range_obj = self._launch(
            user, lease_ceiling=datetime.now(UTC) + timedelta(days=2), backend_admission=self._gce()
        )
        assert range_obj.remote_access_capability is None


class TestOpenVpnDeadline:
    """The admission decision itself, independent of a launch (#2030)."""

    @pytest.mark.parametrize(
        ("enabled", "local", "backend", "admitted"),
        [
            (True, None, "gce", True),
            (False, None, "gce", False),
            (True, "subprocess", "gce", False),
            (True, None, "ec2", False),
            (True, None, None, False),
        ],
    )
    def test_only_an_opted_in_gce_deployment_requests_vpn(self, settings, enabled, local, backend, admitted):
        from datetime import UTC, datetime, timedelta

        from cms.services._range_remote_access import openvpn_deadline

        settings.RANGE_OPENVPN_ENABLED = enabled
        settings.LOCAL_PROVISIONER = local
        ceiling = datetime.now(UTC) + timedelta(days=1)
        assert openvpn_deadline(backend, ceiling) == (ceiling if admitted else None)
