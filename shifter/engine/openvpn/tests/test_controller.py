"""The pool server's client policy (#2480): admit, scope, revoke, fail closed."""

from __future__ import annotations

import pytest

from shifter_openvpn.controller import RETRY_SECONDS, Controller
from shifter_openvpn.management import ClientEvent
from shifter_openvpn.portal import Grant, PortalRefused, PortalUnavailable


class FakeManagement:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def allow(self, cid, kid, config_lines):
        self.calls.append(("allow", cid, kid, tuple(config_lines)))

    def allow_unchanged(self, cid, kid):
        self.calls.append(("allow_unchanged", cid, kid))

    def deny(self, cid, kid, reason):
        self.calls.append(("deny", cid, kid, reason))

    def kill(self, cid):
        self.calls.append(("kill", cid))


class FakePortal:
    def __init__(self) -> None:
        self.authorize_result: Grant | Exception = Grant("s-1", "10.50.3.3", (22, 3389), 15)
        self.heartbeat_result: tuple[set[str], int] | Exception = (set(), 15)
        self.reported: list[list[str]] = []
        self.ended: list[str] = []

    def authorize(self, common_name, client_id, client_address):
        if isinstance(self.authorize_result, Exception):
            raise self.authorize_result
        return self.authorize_result

    def heartbeat(self, sessions):
        self.reported.append(sessions)
        if isinstance(self.heartbeat_result, Exception):
            raise self.heartbeat_result
        return self.heartbeat_result

    def end(self, session):
        self.ended.append(session)


class FakeFirewall:
    def __init__(self, *, fail: bool = False) -> None:
        self.allowed: set[tuple] = set()
        self.fail = fail

    def allow(self, client, target, ports):
        if self.fail:
            raise RuntimeError("nft failed")
        self.allowed.add((client, target, ports))

    def revoke(self, client, target, ports):
        self.allowed.discard((client, target, ports))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def parts():
    management, portal, firewall, clock = FakeManagement(), FakePortal(), FakeFirewall(), Clock()
    controller = Controller(management, portal, firewall, grace_seconds=90, clock=clock, log=lambda _m: None)
    # Authorization normally runs on a pool; run it inline so the test is deterministic.
    controller._authorizers.submit = lambda fn, *args: fn(*args)  # type: ignore[method-assign]
    return controller, management, portal, firewall, clock


def _connect(cid=7, kid=1):
    return ClientEvent("CONNECT", cid, kid, {"common_name": "participant-x", "untrusted_ip": "198.51.100.2"})


def _established(cid=7, address="100.96.0.2"):
    return ClientEvent("ESTABLISHED", cid, None, {"ifconfig_pool_remote_ip": address})


def test_an_authorized_client_reaches_only_its_target_ports(parts):
    controller, management, _portal, firewall, _clock = parts

    controller.handle(_connect())
    controller.handle(_established())

    assert management.calls == [("allow", 7, 1, ('push "route 10.50.3.3 255.255.255.255"',))]
    assert firewall.allowed == {("100.96.0.2", "10.50.3.3", (22, 3389))}


@pytest.mark.parametrize(
    ("result", "reason"),
    [(PortalRefused("vpn.access_revoked"), "vpn.access_revoked"), (PortalUnavailable("timeout"), "portal unavailable")],
)
def test_a_refused_or_unanswered_connection_is_denied(parts, result, reason):
    controller, management, portal, firewall, _clock = parts
    portal.authorize_result = result

    controller.handle(_connect())

    assert management.calls == [("deny", 7, 1, reason)]
    assert controller.session_count() == 0
    assert firewall.allowed == set()


def test_disconnect_removes_the_allowance_and_tells_the_portal(parts):
    controller, _management, portal, firewall, _clock = parts
    controller.handle(_connect())
    controller.handle(_established())

    controller.handle(ClientEvent("DISCONNECT", 7))

    assert firewall.allowed == set()
    assert portal.ended == ["s-1"]
    assert controller.session_count() == 0


def test_an_unknown_or_addressless_establishment_is_killed(parts):
    controller, management, _portal, firewall, _clock = parts
    controller.handle(_established(cid=99))
    controller.handle(_connect(cid=8))
    controller.handle(_established(cid=8, address=""))

    assert ("kill", 99) in management.calls and ("kill", 8) in management.calls
    assert firewall.allowed == set()


def test_a_firewall_failure_kills_the_session_rather_than_leaving_it_half_open(parts):
    controller, management, _portal, _firewall, _clock = parts
    controller._firewall = FakeFirewall(fail=True)
    controller.handle(_connect())
    controller.handle(_established())
    assert management.calls[-1] == ("kill", 7)


def test_renegotiation_keeps_a_known_session_and_refuses_an_unknown_one(parts):
    controller, management, *_ = parts
    controller.handle(_connect())

    controller.handle(ClientEvent("REAUTH", 7, 2))
    controller.handle(ClientEvent("REAUTH", 8, 2))

    assert management.calls[-2:] == [("allow_unchanged", 7, 2), ("deny", 8, 2, "unknown session")]


def test_the_heartbeat_reports_live_sessions_and_kills_revoked_ones(parts):
    controller, management, portal, _firewall, _clock = parts
    controller.handle(_connect())
    portal.heartbeat_result = ({"s-1"}, 15)

    assert controller.heartbeat() == 15
    assert portal.reported == [["s-1"]]
    assert management.calls[-1] == ("kill", 7)


def test_unconfirmed_revocation_ends_every_session_after_the_grace_period(parts):
    controller, management, portal, _firewall, clock = parts
    controller.handle(_connect())
    portal.heartbeat_result = PortalUnavailable("down")

    clock.now = 60
    assert controller.heartbeat() == RETRY_SECONDS
    assert ("kill", 7) not in management.calls

    clock.now = 91
    controller.heartbeat()
    assert management.calls[-1] == ("kill", 7)
