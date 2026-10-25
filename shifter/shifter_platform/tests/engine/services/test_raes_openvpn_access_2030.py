"""Participant OpenVPN access on the RAES path reaches the portal (#2030, ADR-039-R10).

Covers the Engine seams end to end:

* create-time minting against the persisted participant access, the GCE-only
  fail-closed gate, and the idempotent-replay guard;
* the warm-claim grant;
* the operation-input projection the provisioner realizes from;
* binding the owner-free realization from the terminal result to the range owner;
* profile delivery against the realized RAES member; and
* ownership transfer of a binding that never left platform custody.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.launch_intents import enqueue_provisioner_launch
from engine.models import (
    OperationInput,
    OperationResultDisposition,
    OperationResultInbox,
    RaesParticipantAccessBinding,
    Range,
    Request,
    WarmRangeGeneration,
)
from engine.services import (
    RangeBindings,
    apply_pending_operation_results,
    create_raes_range,
    grant_raes_remote_access,
    has_openvpn_profile,
    range_owner_reassignment_available_by_request,
)
from shared.enums import ResourceStatus
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
from shared.operation_results import ResultStep, build_result_identity, result_kind_for
from shared.raes.operation_input import parse_raes_operation_input
from shared.raes.participant_access import ParticipantAccessBinding
from shared.raes.status import RAES_STATE_SUCCEEDED
from shared.range_instantiation_policy import BackendAdmission, InstantiationPurpose
from shared.remote_access import bind_openvpn_realization, build_openvpn_capability

pytestmark = pytest.mark.django_db

_WORKSPACE_ID = 1
_NODE = "provision.node.kali"
_TARGET = f"{_NODE}#0"
_PLAN = {"kind": "raes_provisioning_plan", "resources": {}}


def _gce() -> BackendAdmission:
    return BackendAdmission(True, "gce", InstantiationPurpose.LIVE_FIRE, "", "")


def _deadline() -> datetime:
    return datetime.now(UTC) + timedelta(days=3)


def _access(target: str = _NODE) -> tuple[ParticipantAccessBinding, ...]:
    return (
        ParticipantAccessBinding(target_address=target, channel="ssh", account_address="provision.account.kali"),
        ParticipantAccessBinding(target_address=target, channel="rdp", account_address="provision.account.desktop"),
    )


def _create(*, deadline: datetime | None, access=None, backend: BackendAdmission | None = None, request_id=None):
    user = get_user_model().objects.create_user(username=f"{uuid4()}@example.com")
    request_id = request_id or uuid4()
    create_raes_range(
        request_id=request_id,
        user_id=user.id,
        compiled_plan=_PLAN,
        workspace_id=_WORKSPACE_ID,
        backend_admission=backend or _gce(),
        bindings=RangeBindings(
            participant_access=access if access is not None else _access(), openvpn_deadline=deadline
        ),
    )
    return Range.objects.get(request__request_id=request_id)


class TestCreateMinting:
    def test_an_admitted_launch_mints_the_sole_target(self):
        first = _create(deadline=_deadline())

        assert first.remote_access_capability["target_ref"] == _TARGET
        assert first.remote_access_capability["channel"] == "openvpn"

    @pytest.mark.parametrize(
        "access",
        [
            pytest.param((), id="no-participant-access"),
            pytest.param(_access() + _access("provision.node.other"), id="two-target-nodes"),
        ],
    )
    def test_a_launch_without_a_single_target_mints_nothing(self, access):
        range_obj = _create(deadline=_deadline(), access=access)
        assert range_obj.remote_access_capability is None

    def test_a_launch_without_a_deadline_mints_nothing(self):
        range_obj = _create(deadline=None)
        assert range_obj.remote_access_capability is None

    def test_a_requested_deadline_on_a_backend_without_a_gateway_fails_closed(self):
        request_id = uuid4()
        with pytest.raises(ValueError, match="not realized"):
            _create(
                deadline=_deadline(),
                backend=BackendAdmission(True, "ec2", InstantiationPurpose.LIVE_FIRE, "", ""),
                request_id=request_id,
            )
        assert not Range.objects.filter(request__request_id=request_id).exists()

    def test_replay_must_request_the_same_authority(self):
        deadline = _deadline()
        range_obj = _create(deadline=deadline)
        replay = {
            "request_id": range_obj.request.request_id,
            "user_id": range_obj.user_id,
            "compiled_plan": _PLAN,
            "workspace_id": _WORKSPACE_ID,
            "backend_admission": _gce(),
        }

        same = create_raes_range(
            **replay, bindings=RangeBindings(participant_access=_access(), openvpn_deadline=deadline)
        )
        assert same.range_id == str(range_obj.uuid)
        with pytest.raises(ValueError, match="OpenVPN authority"):
            create_raes_range(**replay, bindings=RangeBindings(participant_access=_access(), openvpn_deadline=None))


class TestWarmClaimGrant:
    def test_a_claimed_generation_receives_the_claimants_authority_once(self):
        range_obj = _create(deadline=None)

        assert grant_raes_remote_access(range_obj.request.request_id, _deadline()) is True
        range_obj.refresh_from_db()
        assert range_obj.remote_access_capability["target_ref"] == _TARGET
        with pytest.raises(ValueError, match="before its claim"):
            grant_raes_remote_access(range_obj.request.request_id, _deadline())

    def test_no_deadline_grants_nothing(self):
        assert grant_raes_remote_access(uuid4(), None) is False


class _Range:
    """A launched RAES range holding a capability and declared access."""

    def __init__(self, *, capability: bool = True, owner=None, status=ResourceStatus.PENDING.value):
        self.request_id = uuid4()
        self.operation_id = uuid4()
        self.user = owner or get_user_model().objects.create_user(username=f"{self.request_id}@example.com")
        self.request = Request.objects.create(request_id=self.request_id, request_type="range", user=self.user)
        self.range = Range.objects.create(
            workspace_id=_WORKSPACE_ID,
            request=self.request,
            user=self.user,
            status=status,
            range_config=_PLAN,
            range_backend="gce",
            provisioner_operation_id=self.operation_id,
            remote_access_capability=build_openvpn_capability(_TARGET, _deadline()) if capability else None,
        )
        for binding in _access():
            RaesParticipantAccessBinding.objects.create(
                range=self.range,
                target_address=binding.target_address,
                channel=binding.channel,
                account_address=binding.account_address,
                binding_version=1,
            )

    def input(self, operation: str = "provision"):
        enqueue_provisioner_launch(["raes-range", operation, "--request-id", str(self.request_id)])
        row = OperationInput.objects.get(request_id=self.request_id, operation=operation)
        return parse_raes_operation_input(row.envelope["payload"])

    def seed_ready(self, payload: dict) -> OperationResultInbox:
        step = ResultStep.RAES_TERMINAL_READY
        envelope = build_operation_envelope(
            operation_id=self.operation_id,
            request_id=self.request_id,
            resource="raes-range",
            operation="provision",
            payload=payload,
        )
        digest = canonical_payload_digest(envelope["payload"])
        return OperationResultInbox.objects.create(
            operation_id=self.operation_id,
            request_id=self.request_id,
            resource="raes-range",
            operation="provision",
            contract_version="1",
            result_kind=result_kind_for("raes-range", "provision", step=step),
            result_step=step,
            result_identity=build_result_identity(operation_id=self.operation_id, step=step, digest=digest),
            payload_digest=digest,
            envelope=envelope,
        )

    def realization(self, **overrides) -> dict:
        return {
            "generation": str(self.request_id),
            "target_ref": _TARGET,
            "endpoint": "34.1.2.3",
            "port": 1194,
            "secret_ref": "projects/p/secrets/profile",
            **overrides,
        }


def _member() -> dict:
    return {
        "uuid": _TARGET,
        "name": "kali",
        "os_type": "linux",
        "private_ip": "10.9.0.10",
        "instance_id": "shifter-r-7-lan-kali",
        "subnet_name": "lan",
        "participant_access_channels": ["rdp", "ssh"],
        "participant_access_usernames": {"rdp": "kali", "ssh": "kali"},
        "ssh_key_secret_arn": "projects/p/secrets/ssh",
        "rdp_password_secret_arn": "projects/p/secrets/rdp",
    }


def _ready(vpn_access: dict | None) -> dict:
    payload: dict = {"raes_status": RAES_STATE_SUCCEEDED, "members": [_member()]}
    if vpn_access is not None:
        payload["vpn_access"] = vpn_access
    return payload


def _disposition(row: OperationResultInbox) -> str:
    row.refresh_from_db()
    return row.disposition


class TestOperationInputProjection:
    def test_provision_and_destroy_carry_the_capability(self):
        fx = _Range()

        provision = fx.input("provision").remote_access
        assert provision.target_ref == _TARGET
        fx.range.status = ResourceStatus.DESTROYING.value
        fx.range.save(update_fields=["status"])
        assert fx.input("destroy").remote_access == provision

    def test_a_range_without_a_capability_projects_none(self):
        assert _Range(capability=False).input().remote_access is None

    def test_a_warm_prepare_provision_is_quarantined_without_vpn(self):
        fx = _Range()
        WarmRangeGeneration.objects.create(
            bucket_id="gce-example",
            compatibility_digest="sha256:" + "a" * 64,
            effective_policy_fingerprint="sha256:" + "f" * 64,
            backend="gce",
            range_source="mission-control",
            capacity_partition="default",
            capacity_scope_ref=uuid4(),
            capacity_draw_key=uuid4(),
            request_id=fx.request_id,
            state=WarmRangeGeneration.State.PROVISIONING,
            idle_deadline=timezone.now() + timedelta(hours=1),
        )
        payload = fx.input()
        assert payload.remote_access is None
        assert payload.access_bindings == ()


class TestRealizationBinding:
    def test_ready_binds_the_realization_to_the_range_owner(self):
        fx = _Range(status=ResourceStatus.PROVISIONING.value)
        row = fx.seed_ready(_ready(fx.realization()))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.READY.value
        assert fx.range.vpn_access_binding == bind_openvpn_realization(fx.realization(), fx.user.id)
        assert has_openvpn_profile(fx.user, fx.request_id) is True

    @pytest.mark.parametrize(
        ("capability", "overrides", "omit"),
        [
            pytest.param(True, {}, True, id="capability-without-realization"),
            pytest.param(False, {}, False, id="realization-without-capability"),
            pytest.param(True, {"target_ref": "provision.node.other#0"}, False, id="another-target"),
            pytest.param(True, {"generation": str(uuid4())}, False, id="another-generation"),
        ],
    )
    def test_a_realization_that_does_not_match_the_capability_is_refused(self, capability, overrides, omit):
        fx = _Range(capability=capability, status=ResourceStatus.PROVISIONING.value)
        row = fx.seed_ready(_ready(None if omit else fx.realization(**overrides)))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) != OperationResultDisposition.APPLIED
        assert fx.range.vpn_access_binding is None
        assert fx.range.status != ResourceStatus.READY.value


class TestProfileDelivery:
    def _ready_range(self, *, channels: list[str]) -> _Range:
        fx = _Range(status=ResourceStatus.READY.value)
        member = {**_member(), "participant_access_channels": channels, "role": "raes-node"}
        fx.range.provisioned_instances = [member]
        fx.range.vpn_access_binding = bind_openvpn_realization(fx.realization(), fx.user.id)
        fx.range.save(update_fields=["provisioned_instances", "vpn_access_binding"])
        return fx

    def test_a_realized_member_with_participant_access_is_deliverable(self):
        fx = self._ready_range(channels=["rdp", "ssh"])
        assert has_openvpn_profile(fx.user, fx.request_id) is True

    def test_a_target_without_participant_access_is_not_deliverable(self):
        fx = self._ready_range(channels=[])
        assert has_openvpn_profile(fx.user, fx.request_id) is False


class TestOwnershipTransfer:
    def _bound(self, owner) -> _Range:
        fx = _Range(owner=owner, status=ResourceStatus.READY.value)
        fx.range.vpn_access_binding = bind_openvpn_realization(fx.realization(), owner.id)
        fx.range.save(update_fields=["vpn_access_binding"])
        return fx

    def test_a_binding_held_by_a_managed_identity_may_move(self):
        managed = get_user_model().objects.create_user(username=f"spare-{uuid4()}", is_active=False)
        managed.set_unusable_password()
        managed.save(update_fields=["password"])
        assert range_owner_reassignment_available_by_request(self._bound(managed).request_id) is True

    def test_a_binding_an_interactive_owner_could_have_downloaded_may_not_move(self):
        interactive = get_user_model().objects.create_user(username=f"{uuid4()}@example.com", password="pw-123456")
        assert range_owner_reassignment_available_by_request(self._bound(interactive).request_id) is False
