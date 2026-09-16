"""RAES-native participant access reaches the portal (#1710).

Covers the three seams the feature needs end to end on the platform side:

* the immutable declaration persisted beside the plan at range create, and its
  idempotent-replay guard;
* the realized member/access projection applied from the authoritative result
  inbox into ``Range.provisioned_instances``, including the equality check
  against that declaration and the READY gate; and
* the portal reading per-channel logins from the applied projection.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.models import (
    OperationResultDisposition,
    OperationResultInbox,
    RaesParticipantAccessBinding,
    Range,
    Request,
)
from engine.services import RangeBindings, apply_pending_operation_results, create_raes_range
from shared.enums import ResourceStatus
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
from shared.operation_results import ResultStep, build_result_identity, result_kind_for
from shared.raes.participant_access import ParticipantAccessBinding
from shared.raes.status import RAES_STATE_SUCCEEDED

_WORKSPACE_ID = 1
_NODE = "provision.node.web"

pytestmark = pytest.mark.django_db


def _binding(target=_NODE, channel="ssh", account="provision.account.analyst"):
    return ParticipantAccessBinding(target_address=target, channel=channel, account_address=account)


def _member(channels=("ssh",), uuid=f"{_NODE}#0", usernames=None, sftp_root_directory=None):
    member = {
        "uuid": uuid,
        "name": "web",
        "os_type": "linux",
        "private_ip": "10.9.0.10",
        "instance_id": "shifter-r-7-lan-web",
        "subnet_name": "lan",
        "participant_access_channels": list(channels),
        "participant_access_usernames": usernames or dict.fromkeys(channels, "analyst"),
    }
    if "ssh" in channels:
        member["ssh_key_secret_arn"] = "projects/p/secrets/ssh"
    if "rdp" in channels:
        member["rdp_password_secret_arn"] = "projects/p/secrets/rdp"
    if sftp_root_directory is not None:
        member["sftp_root_directory"] = sftp_root_directory
    return member


class _Fixture:
    """An RAES range with a live operation generation and declared access."""

    def __init__(self, *, declarations=(_NODE,), status=ResourceStatus.PROVISIONING.value):
        self.operation = "provision"
        self.operation_id = uuid4()
        self.request_id = uuid4()
        self.user = get_user_model().objects.create_user(username=f"{self.request_id}@example.com")
        self.request = Request.objects.create(request_id=self.request_id, request_type="range", user=self.user)
        self.range = Range.objects.create(
            workspace_id=_WORKSPACE_ID,
            request=self.request,
            user=self.user,
            status=status,
            provisioner_operation_id=self.operation_id,
        )
        for target in declarations:
            RaesParticipantAccessBinding.objects.create(
                range=self.range,
                target_address=target,
                channel="ssh",
                account_address="provision.account.analyst",
                binding_version=1,
            )

    def seed(self, step: ResultStep, payload: dict) -> OperationResultInbox:
        envelope = build_operation_envelope(
            operation_id=self.operation_id,
            request_id=self.request_id,
            resource="raes-range",
            operation=self.operation,
            payload=payload,
        )
        digest = canonical_payload_digest(envelope["payload"])
        return OperationResultInbox.objects.create(
            operation_id=self.operation_id,
            request_id=self.request_id,
            resource="raes-range",
            operation=self.operation,
            contract_version="1",
            result_kind=result_kind_for("raes-range", self.operation, step=step),
            result_step=step,
            result_identity=build_result_identity(operation_id=self.operation_id, step=step, digest=digest),
            payload_digest=digest,
            envelope=envelope,
        )


class TestDeclarationPersistence:
    def test_create_persists_the_declaration_beside_the_plan(self):
        user = get_user_model().objects.create_user(username="declare@example.com")
        request_id = uuid4()
        create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan={"kind": "raes_provisioning_plan", "resources": {}},
            workspace_id=_WORKSPACE_ID,
            bindings=RangeBindings(participant_access=(_binding(),)),
        )
        rows = RaesParticipantAccessBinding.objects.all()
        assert [(row.target_address, row.channel, row.account_address) for row in rows] == [
            (_NODE, "ssh", "provision.account.analyst")
        ]

    def test_replay_with_different_access_intent_is_rejected(self):
        """The declaration is what realized access is later compared against."""
        user = get_user_model().objects.create_user(username="replay@example.com")
        request_id = uuid4()
        plan = {"kind": "raes_provisioning_plan", "resources": {}}
        create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=plan,
            workspace_id=_WORKSPACE_ID,
            bindings=RangeBindings(participant_access=(_binding(),)),
        )
        replay_bindings = RangeBindings(participant_access=(_binding(channel="rdp"),))
        with pytest.raises(ValueError, match="participant access intent"):
            create_raes_range(
                request_id=request_id,
                user_id=user.id,
                compiled_plan=plan,
                workspace_id=_WORKSPACE_ID,
                bindings=replay_bindings,
            )

    def test_replay_with_identical_access_intent_is_idempotent(self):
        user = get_user_model().objects.create_user(username="idem@example.com")
        request_id = uuid4()
        plan = {"kind": "raes_provisioning_plan", "resources": {}}
        first = create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=plan,
            workspace_id=_WORKSPACE_ID,
            bindings=RangeBindings(participant_access=(_binding(),)),
        )
        second = create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=plan,
            workspace_id=_WORKSPACE_ID,
            bindings=RangeBindings(participant_access=(_binding(),)),
        )
        assert first.range_id == second.range_id
        assert RaesParticipantAccessBinding.objects.count() == 1


def _ready(members):
    """The terminal-ready payload carrying this generation's realized access."""
    return {"raes_status": RAES_STATE_SUCCEEDED, "members": members}


class TestRealizedProjection:
    def test_ready_applies_the_projection_and_transitions_in_one_result(self):
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member()]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        instance = fx.range.provisioned_instances[0]
        assert instance["participant_access_channels"] == ["ssh"]
        assert instance["participant_access_usernames"] == {"ssh": "analyst"}
        assert instance["ssh_key_secret_arn"] == "projects/p/secrets/ssh"
        # Realized state and lifecycle move together, in one generation.
        assert fx.range.status == ResourceStatus.READY.value

    def test_ready_projects_the_realized_sftp_root_directory(self):
        """A realized member's SFTP root is persisted for the connection layer (#375)."""
        fx = _Fixture()
        fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member(sftp_root_directory="/home/kali")]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert fx.range.provisioned_instances[0]["sftp_root_directory"] == "/home/kali"

    def test_ready_omits_sftp_root_directory_when_absent(self):
        """No declared root persists no key rather than an empty guess (#375)."""
        fx = _Fixture()
        fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member()]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert "sftp_root_directory" not in fx.range.provisioned_instances[0]

    def test_malformed_sftp_root_directory_is_rejected(self):
        """A traversal root fails the closed transport parse and never applies (#375)."""
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member(sftp_root_directory="/home/../etc")]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) != OperationResultDisposition.APPLIED
        assert not fx.range.provisioned_instances

    def test_realized_access_beyond_the_declaration_is_rejected(self):
        """A member claiming an undeclared endpoint must not become authorizable."""
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member(channels=("ssh", "rdp"))]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) != OperationResultDisposition.APPLIED
        assert not fx.range.provisioned_instances
        assert fx.range.status != ResourceStatus.READY.value

    def test_declaration_with_no_realized_endpoint_is_rejected(self):
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member(channels=())]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) != OperationResultDisposition.APPLIED
        assert not fx.range.provisioned_instances

    def test_a_second_instance_may_not_satisfy_a_declared_endpoint(self):
        """An interactive target materializes exactly one instance: only #0."""
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member(uuid=f"{_NODE}#1")]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) != OperationResultDisposition.APPLIED
        assert not fx.range.provisioned_instances

    def test_an_invented_instance_suffix_is_rejected(self):
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member(uuid=f"{_NODE}#99")]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) != OperationResultDisposition.APPLIED
        assert not fx.range.provisioned_instances

    def test_two_members_claiming_one_declared_endpoint_are_rejected(self):
        """Set equality alone would collapse these into a single matching pair."""
        fx = _Fixture()
        row = fx.seed(
            ResultStep.RAES_TERMINAL_READY,
            _ready([_member(), _member(uuid=f"{_NODE}#1")]),
        )

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) != OperationResultDisposition.APPLIED
        assert not fx.range.provisioned_instances


class TestReadyGate:
    def test_ready_carrying_no_members_for_a_declared_range_is_refused(self):
        """A declared range must not go READY with nothing for the portal to dial."""
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) != OperationResultDisposition.APPLIED
        assert fx.range.status != ResourceStatus.READY.value

    def test_ready_without_declared_access_is_unaffected(self):
        """A scenario authoring no interactive access keeps its existing path."""
        fx = _Fixture(declarations=())
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, _ready([_member(channels=())]))

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.READY.value


def _disposition(row: OperationResultInbox) -> str:
    row.refresh_from_db()
    return row.disposition
