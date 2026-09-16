"""Fail-closed join of the participant-access sidecar to provisioning truth (#1710)."""

from __future__ import annotations

import pytest

from raes_access import RaesAccessError, join_participant_access
from raes_composition import RaesPlanAccount
from raes_identity import RESERVED_MANAGEMENT_LOGIN
from raes_plan_types import RaesPlan, RaesPlanNode

_WEB = "provision.node.web"
_DC = "provision.node.dc"


def _node(address=_WEB, name="web", count=1, os_family="linux"):
    return RaesPlanNode(
        address=address,
        name=name,
        os_family=os_family,
        count=count,
        network_addresses=("provision.network.lan",),
    )


def _account(
    address="provision.account.analyst",
    username="analyst",
    target=_WEB,
    auth_method="key",
    disabled=False,
    domain_ref=None,
    domain_id=None,
):
    return RaesPlanAccount(
        username=username,
        target_address=target,
        address=address,
        auth_method=auth_method,
        disabled=disabled,
        domain_ref=domain_ref,
        domain_id=domain_id,
    )


def _plan(nodes=None, accounts=None):
    return RaesPlan(
        raes_version="3.5.0",
        nodes=tuple(nodes if nodes is not None else (_node(),)),
        networks=(),
        accounts=tuple(accounts if accounts is not None else (_account(),)),
    )


def _transport(target=_WEB, channel="ssh", account="provision.account.analyst"):
    return {
        "target_address": target,
        "channel": channel,
        "account_address": account,
        "binding_version": 1,
    }


class TestJoin:
    def test_empty_sidecar_joins_to_nothing(self):
        assert join_participant_access([], _plan()) == ()

    def test_ssh_binding_resolves_key_account(self):
        joined = join_participant_access([_transport()], _plan())
        assert len(joined) == 1
        binding = joined[0]
        assert (binding.target_address, binding.channel) == (_WEB, "ssh")
        assert (binding.username, binding.auth_method) == ("analyst", "key")

    def test_rdp_binding_resolves_password_account(self):
        plan = _plan(
            nodes=(_node(os_family="windows"),),
            accounts=(_account(auth_method="password", username="operator"),),
        )
        joined = join_participant_access([_transport(channel="rdp")], plan)
        assert (joined[0].username, joined[0].auth_method) == ("operator", "password")

    def test_ssh_and_rdp_may_name_different_accounts(self):
        """Per-channel logins must not be conflated into one username."""
        plan = _plan(
            nodes=(_node(os_family="windows"),),
            accounts=(
                _account(address="provision.account.a", username="sshuser", auth_method="key"),
                _account(address="provision.account.b", username="rdpuser", auth_method="password"),
            ),
        )
        joined = join_participant_access(
            [
                _transport(channel="ssh", account="provision.account.a"),
                _transport(channel="rdp", account="provision.account.b"),
            ],
            plan,
        )
        assert {(item.channel, item.username) for item in joined} == {("ssh", "sshuser"), ("rdp", "rdpuser")}


class TestFailClosed:
    def test_dangling_target_is_rejected(self):
        transports = [_transport(target=_DC)]
        plan = _plan()
        with pytest.raises(RaesAccessError, match="target"):
            join_participant_access(transports, plan)

    def test_multi_instance_target_is_rejected(self):
        """count > 1 has no authored instance selector; picking #0 invents semantics."""
        transports = [_transport()]
        plan = _plan(nodes=(_node(count=2),))
        with pytest.raises(RaesAccessError, match="exactly one instance"):
            join_participant_access(transports, plan)

    def test_unknown_account_is_rejected(self):
        transports = [_transport(account="provision.account.ghost")]
        plan = _plan()
        with pytest.raises(RaesAccessError, match="account"):
            join_participant_access(transports, plan)

    def test_account_on_another_node_is_rejected(self):
        plan = _plan(nodes=(_node(), _node(address=_DC, name="dc")), accounts=(_account(target=_DC),))
        transports = [_transport()]
        with pytest.raises(RaesAccessError, match="target"):
            join_participant_access(transports, plan)

    def test_disabled_account_is_rejected(self):
        transports = [_transport()]
        plan = _plan(accounts=(_account(disabled=True),))
        with pytest.raises(RaesAccessError, match="disabled"):
            join_participant_access(transports, plan)

    @pytest.mark.parametrize("domain", [{"domain_ref": "corp"}, {"domain_id": "corp.local"}])
    def test_domain_account_is_rejected(self, domain):
        """Directory accounts have no bounded broker contract yet."""
        transports = [_transport()]
        plan = _plan(accounts=(_account(**domain),))
        with pytest.raises(RaesAccessError, match="local"):
            join_participant_access(transports, plan)

    def test_ssh_against_password_account_is_rejected(self):
        """Never silently add a second auth method to an authored account."""
        transports = [_transport()]
        plan = _plan(accounts=(_account(auth_method="password"),))
        with pytest.raises(RaesAccessError, match="auth method"):
            join_participant_access(transports, plan)

    def test_rdp_against_key_account_is_rejected(self):
        transports = [_transport(channel="rdp")]
        plan = _plan()
        with pytest.raises(RaesAccessError, match="auth method"):
            join_participant_access(transports, plan)

    def test_duplicate_endpoint_is_rejected(self):
        transports = [_transport(), _transport()]
        plan = _plan()
        with pytest.raises(RaesAccessError, match="duplicate"):
            join_participant_access(transports, plan)

    def test_unknown_channel_is_rejected(self):
        transports = [_transport(channel="vnc")]
        plan = _plan()
        with pytest.raises(RaesAccessError):
            join_participant_access(transports, plan)

    def test_smuggled_transport_field_is_rejected(self):
        """A locator or credential must not reach realization through the sidecar."""
        tampered = {**_transport(), "credential_ref": "projects/p/secrets/s"}
        plan = _plan()
        with pytest.raises(RaesAccessError):
            join_participant_access([tampered], plan)

    def test_blank_account_address_is_rejected(self):
        """An omitted account must never fall back to the reserved management user."""
        transports = [_transport(account="")]
        plan = _plan()
        with pytest.raises(RaesAccessError):
            join_participant_access(transports, plan)


class TestManagementBoundary:
    """The provisioner's own management seat is never a participant seat."""

    @pytest.mark.parametrize(
        ("channel", "auth_method"),
        [("ssh", "key"), ("rdp", "password")],
    )
    def test_account_resolving_to_the_management_login_is_rejected(self, channel, auth_method):
        # A scenario author may name any local account, including one whose
        # login collides with the provisioner's management seat. Brokering it
        # would install a participant credential on the account the provisioner
        # uses for bootstrap/verification/teardown.
        plan = _plan(
            nodes=(_node(os_family="windows"),),
            accounts=(_account(username=RESERVED_MANAGEMENT_LOGIN, auth_method=auth_method),),
        )
        transports = [_transport(channel=channel)]
        with pytest.raises(RaesAccessError, match="reserved management login"):
            join_participant_access(transports, plan)

    def test_a_differently_named_account_is_still_brokered(self):
        joined = join_participant_access([_transport()], _plan())
        assert joined[0].username != RESERVED_MANAGEMENT_LOGIN
