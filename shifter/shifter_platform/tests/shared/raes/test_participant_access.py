"""Participant interactive-access projection tests (#1710, ADR-032-R10).

Covers the one place Shifter lowers participant-domain authored intent into the
bounded sidecar that rides beside the serialized ProvisioningPlan: the closed
value object, its transport round-trip, and the fail-closed projection from the
compiled ``RuntimeModel.participant_behaviors``.
"""

from __future__ import annotations

import pytest
from raes_processor.models.behavior_resources import (
    ParticipantBehaviorRuntime,
    ParticipantInteractiveAccessRuntime,
)

from shared.raes.participant_access import (
    ACCESS_BINDING_VERSION,
    MAX_ACCESS_BINDINGS,
    ParticipantAccessBinding,
    ParticipantAccessError,
    project_participant_access,
)

_NODES = frozenset({"provision.node.web", "provision.node.dc"})


def _access(target="provision.node.web", channel="ssh", account="participant.account.analyst", access_id="a1"):
    return ParticipantInteractiveAccessRuntime(
        access_id=access_id,
        target_ref="web",
        target_address=target,
        channel=channel,
        account_ref="analyst",
        account_address=account,
    )


def _behavior(name, *accesses):
    return ParticipantBehaviorRuntime(
        address=f"participant.behavior.{name}",
        name=name,
        spec={},
        participant_name=name,
        interactive_access=tuple(accesses),
    )


def _model(*behaviors):
    return {behavior.participant_name: behavior for behavior in behaviors}


class TestProjection:
    def test_no_participants_projects_nothing(self):
        assert project_participant_access({}, node_addresses=_NODES) == ()

    def test_participant_without_access_projects_nothing(self):
        assert project_participant_access(_model(_behavior("red")), node_addresses=_NODES) == ()

    def test_single_participant_projects_sorted_bindings(self):
        model = _model(
            _behavior(
                "red",
                _access(channel="rdp", target="provision.node.dc", access_id="b"),
                _access(channel="ssh", access_id="a"),
            )
        )
        bindings = project_participant_access(model, node_addresses=_NODES)
        assert bindings == (
            ParticipantAccessBinding("provision.node.dc", "rdp", "participant.account.analyst"),
            ParticipantAccessBinding("provision.node.web", "ssh", "participant.account.analyst"),
        )
        assert all(binding.binding_version == ACCESS_BINDING_VERSION for binding in bindings)

    def test_invariant_participants_project_one_binding_set(self):
        """Two participants declaring the same access are unambiguous."""
        model = _model(_behavior("red", _access()), _behavior("blue", _access()))
        assert project_participant_access(model, node_addresses=_NODES) == (
            ParticipantAccessBinding("provision.node.web", "ssh", "participant.account.analyst"),
        )


class TestFailClosed:
    def test_divergent_participant_policies_are_ambiguous(self):
        model = _model(
            _behavior("red", _access(channel="ssh")),
            _behavior("blue", _access(channel="rdp", target="provision.node.dc")),
        )
        with pytest.raises(ParticipantAccessError, match="participant-invariant"):
            project_participant_access(model, node_addresses=_NODES)

    def test_access_bearing_participant_beside_empty_participant_is_ambiguous(self):
        """The empty set is a policy too; unioning would widen 'blue' to red's access."""
        model = _model(_behavior("red", _access()), _behavior("blue"))
        with pytest.raises(ParticipantAccessError, match="participant-invariant"):
            project_participant_access(model, node_addresses=_NODES)

    def test_unknown_channel_is_rejected(self):
        model = _model(_behavior("red", _access(channel="vnc")))
        with pytest.raises(ParticipantAccessError, match="channel"):
            project_participant_access(model, node_addresses=_NODES)

    def test_dangling_target_address_is_rejected(self):
        model = _model(_behavior("red", _access(target="provision.node.absent")))
        with pytest.raises(ParticipantAccessError, match="target"):
            project_participant_access(model, node_addresses=_NODES)

    def test_unresolved_target_address_is_rejected(self):
        model = _model(_behavior("red", _access(target="")))
        with pytest.raises(ParticipantAccessError, match="target"):
            project_participant_access(model, node_addresses=_NODES)

    def test_omitted_account_is_rejected(self):
        """An omitted account must never fall back to the reserved management user."""
        model = _model(_behavior("red", _access(account="")))
        with pytest.raises(ParticipantAccessError, match="account"):
            project_participant_access(model, node_addresses=_NODES)

    def test_duplicate_target_channel_is_rejected(self):
        model = _model(
            _behavior(
                "red",
                _access(access_id="a", account="participant.account.analyst"),
                _access(access_id="b", account="participant.account.other"),
            )
        )
        with pytest.raises(ParticipantAccessError, match="duplicate"):
            project_participant_access(model, node_addresses=_NODES)

    def test_oversize_binding_set_is_rejected(self):
        nodes = frozenset(f"provision.node.n{index}" for index in range(MAX_ACCESS_BINDINGS + 1))
        model = _model(
            _behavior(
                "red",
                *[
                    _access(target=f"provision.node.n{index}", access_id=f"a{index}")
                    for index in range(MAX_ACCESS_BINDINGS + 1)
                ],
            )
        )
        with pytest.raises(ParticipantAccessError, match="bounded"):
            project_participant_access(model, node_addresses=nodes)


class TestTransport:
    def test_round_trip_preserves_identity(self):
        binding = ParticipantAccessBinding("provision.node.web", "ssh", "participant.account.analyst")
        assert ParticipantAccessBinding.from_transport(binding.to_transport()) == binding

    def test_transport_carries_only_identity_fields(self):
        transport = ParticipantAccessBinding("provision.node.web", "ssh", "participant.account.analyst").to_transport()
        assert set(transport) == {"target_address", "channel", "account_address", "binding_version"}

    @pytest.mark.parametrize(
        "mutation",
        [
            {"credential_ref": "projects/p/secrets/s"},
            {"address": "10.0.0.5"},
            {"port": 22},
        ],
    )
    def test_unknown_transport_keys_are_rejected(self, mutation):
        """A smuggled locator or credential field must not ride along."""
        raw = ParticipantAccessBinding("provision.node.web", "ssh", "participant.account.analyst").to_transport()
        with pytest.raises(ParticipantAccessError):
            ParticipantAccessBinding.from_transport({**raw, **mutation})

    def test_unsupported_version_is_rejected(self):
        raw = ParticipantAccessBinding("provision.node.web", "ssh", "participant.account.analyst").to_transport()
        with pytest.raises(ParticipantAccessError):
            ParticipantAccessBinding.from_transport({**raw, "binding_version": 99})

    @pytest.mark.parametrize("field", ["target_address", "channel", "account_address"])
    def test_blank_identity_fields_are_rejected(self, field):
        raw = ParticipantAccessBinding("provision.node.web", "ssh", "participant.account.analyst").to_transport()
        with pytest.raises(ParticipantAccessError):
            ParticipantAccessBinding.from_transport({**raw, field: ""})

    def test_unsupported_transport_channel_is_rejected(self):
        raw = ParticipantAccessBinding("provision.node.web", "ssh", "participant.account.analyst").to_transport()
        with pytest.raises(ParticipantAccessError):
            ParticipantAccessBinding.from_transport({**raw, "channel": "vnc"})
