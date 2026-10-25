"""Connect-time authorization and leases for the shared OpenVPN pool (#2480).

Real Range and VpnSession rows; no first-party mocks. Each case is one
scenario the pool controller drives: admit, refuse, supersede, renew, revoke,
disconnect, and lease expiry after a server stops reporting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.models import Range, Request, VpnSession, VpnSessionEndReason, VpnSessionState
from engine.services import VpnSessionDenied, authorize_vpn_session, end_vpn_session, renew_vpn_sessions
from shared.remote_access import bind_openvpn_realization, build_openvpn_capability

pytestmark = pytest.mark.django_db

_TARGET = "provision.node.kali#0"


def _ready_range(*, target_ip: str = "10.50.3.3", channels=("ssh", "rdp"), days: int = 2) -> Range:
    user = get_user_model().objects.create_user(username=f"{uuid4()}@example.com")
    request = Request.objects.create(request_id=uuid4(), request_type="range", user=user)
    realization = {
        "generation": str(request.request_id),
        "target_ref": _TARGET,
        "endpoint": "203.0.113.7",
        "port": 1194,
        "secret_ref": "projects/p/secrets/profile",
    }
    return Range.objects.create(
        workspace_id=1,
        request=request,
        user=user,
        status=Range.Status.READY,
        range_backend="gce",
        remote_access_capability=build_openvpn_capability(_TARGET, datetime.now(UTC) + timedelta(days=days)),
        vpn_access_binding=bind_openvpn_realization(realization, user.id),
        provisioned_instances=[
            {
                "uuid": _TARGET,
                "role": "raes-node",
                "private_ip": target_ip,
                "participant_access_channels": list(channels),
            },
            {
                "uuid": "provision.node.dc#0",
                "role": "raes-node",
                "private_ip": "10.50.3.4",
                "participant_access_channels": [],
            },
        ],
    )


def _connect(range_obj: Range, *, server: str = "vpn-a", client_id: int = 1):
    return authorize_vpn_session(
        common_name=f"participant-{range_obj.request.request_id}",
        server=server,
        client_id=client_id,
        client_address="198.51.100.20",
    )


class TestAuthorize:
    def test_a_current_generation_reaches_only_its_target_and_declared_ports(self):
        range_obj = _ready_range()

        grant = _connect(range_obj)

        assert (grant.target_ip, grant.ports) == ("10.50.3.3", (22, 3389))
        session = VpnSession.objects.get(pk=grant.session_id)
        assert (session.state, session.server, session.client_id) == (VpnSessionState.ACTIVE, "vpn-a", 1)
        assert session.generation == range_obj.request.request_id
        assert session.lease_expires_at > timezone.now()

    def test_a_newer_connection_supersedes_the_older_one(self):
        range_obj = _ready_range()
        first = _connect(range_obj, server="vpn-a", client_id=1)

        second = _connect(range_obj, server="vpn-b", client_id=9)

        old = VpnSession.objects.get(pk=first.session_id)
        assert (old.state, old.end_reason) == (VpnSessionState.ENDED, VpnSessionEndReason.SUPERSEDED)
        assert VpnSession.objects.filter(range=range_obj, state=VpnSessionState.ACTIVE).get().pk == second.session_id
        # The old server learns of it on its next heartbeat.
        assert renew_vpn_sessions(server="vpn-a", session_ids=[str(first.session_id)]) == (first.session_id,)

    @pytest.mark.parametrize(
        "change",
        [
            pytest.param(
                lambda r: Range.objects.filter(pk=r.pk).update(status=Range.Status.DESTROYING), id="not-ready"
            ),
            pytest.param(
                lambda r: Range.objects.filter(pk=r.pk).update(
                    user=get_user_model().objects.create_user(username=f"{uuid4()}@example.com")
                ),
                id="new-owner",
            ),
            pytest.param(lambda r: Range.objects.filter(pk=r.pk).update(vpn_access_binding=None), id="no-binding"),
            pytest.param(lambda r: Range.objects.filter(pk=r.pk).update(provisioned_instances=[]), id="target-gone"),
        ],
    )
    def test_access_that_is_no_longer_current_is_refused(self, change):
        range_obj = _ready_range()
        change(range_obj)

        with pytest.raises(VpnSessionDenied) as denied:
            _connect(range_obj)

        assert denied.value.code == "vpn.access_revoked"
        assert not VpnSession.objects.exists()

    def test_an_expired_access_deadline_is_refused(self):
        range_obj = _ready_range()
        expired = build_openvpn_capability(_TARGET, datetime.now(UTC) + timedelta(days=1))
        expired["teardown_at"] = "2020-01-01T00:00:00Z"
        Range.objects.filter(pk=range_obj.pk).update(remote_access_capability=expired)

        with pytest.raises(VpnSessionDenied, match=r"vpn\.access_revoked"):
            _connect(range_obj)

    @pytest.mark.parametrize("target_ip", ["8.8.8.8", "not-an-ip"])
    def test_a_non_private_target_is_refused(self, target_ip):
        with pytest.raises(VpnSessionDenied, match=r"vpn\.access_revoked"):
            _connect(_ready_range(target_ip=target_ip))

    @pytest.mark.parametrize(
        ("kwargs", "code"),
        [
            ({"common_name": "participant-not-a-uuid"}, "vpn.unknown_client"),
            ({"common_name": f"participant-{uuid4()}"}, "vpn.unknown_client"),
            ({"server": "Bad_Name"}, "vpn.invalid_request"),
            ({"client_id": -1}, "vpn.invalid_request"),
            ({"client_id": True}, "vpn.invalid_request"),
        ],
    )
    def test_malformed_or_unknown_requests_are_refused(self, kwargs, code):
        range_obj = _ready_range()
        request = {
            "common_name": f"participant-{range_obj.request.request_id}",
            "server": "vpn-a",
            "client_id": 1,
            **kwargs,
        }
        with pytest.raises(VpnSessionDenied) as denied:
            authorize_vpn_session(**request)
        assert denied.value.code == code


class TestRenewAndEnd:
    def test_a_valid_session_is_renewed_and_kept(self):
        range_obj = _ready_range()
        grant = _connect(range_obj)
        VpnSession.objects.filter(pk=grant.session_id).update(lease_expires_at=timezone.now() + timedelta(seconds=5))

        assert renew_vpn_sessions(server="vpn-a", session_ids=[str(grant.session_id)]) == ()

        assert VpnSession.objects.get(pk=grant.session_id).lease_expires_at > timezone.now() + timedelta(seconds=30)

    def test_destroying_the_range_revokes_the_live_session(self):
        range_obj = _ready_range()
        grant = _connect(range_obj)
        Range.objects.filter(pk=range_obj.pk).update(status=Range.Status.DESTROYING)

        assert renew_vpn_sessions(server="vpn-a", session_ids=[str(grant.session_id)]) == (grant.session_id,)

        session = VpnSession.objects.get(pk=grant.session_id)
        assert (session.state, session.end_reason) == (VpnSessionState.ENDED, VpnSessionEndReason.REVOKED)

    def test_a_server_cannot_keep_sessions_it_does_not_own_or_that_do_not_exist(self):
        range_obj = _ready_range()
        grant = _connect(range_obj, server="vpn-a")
        unknown = uuid4()

        kill = renew_vpn_sessions(server="vpn-b", session_ids=[str(grant.session_id), str(unknown)])

        assert set(kill) == {grant.session_id, unknown}
        assert VpnSession.objects.get(pk=grant.session_id).state == VpnSessionState.ACTIVE

    def test_an_unreported_session_has_left_the_server(self):
        range_obj = _ready_range()
        grant = _connect(range_obj, server="vpn-a")

        assert renew_vpn_sessions(server="vpn-a", session_ids=[]) == ()

        session = VpnSession.objects.get(pk=grant.session_id)
        assert (session.state, session.end_reason) == (VpnSessionState.ENDED, VpnSessionEndReason.DISCONNECTED)

    def test_a_crashed_servers_sessions_expire_on_another_servers_heartbeat(self):
        lapsed = _connect(_ready_range(), server="vpn-dead")
        VpnSession.objects.filter(pk=lapsed.session_id).update(lease_expires_at=timezone.now() - timedelta(seconds=1))

        renew_vpn_sessions(server="vpn-a", session_ids=[])

        session = VpnSession.objects.get(pk=lapsed.session_id)
        assert (session.state, session.end_reason) == (VpnSessionState.ENDED, VpnSessionEndReason.LEASE_EXPIRED)

    def test_a_disconnect_ends_only_the_reporting_servers_session(self):
        range_obj = _ready_range()
        grant = _connect(range_obj, server="vpn-a")

        end_vpn_session(server="vpn-b", session_id=str(grant.session_id))
        assert VpnSession.objects.get(pk=grant.session_id).state == VpnSessionState.ACTIVE

        end_vpn_session(server="vpn-a", session_id=str(grant.session_id))
        session = VpnSession.objects.get(pk=grant.session_id)
        assert (session.state, session.end_reason) == (VpnSessionState.ENDED, VpnSessionEndReason.DISCONNECTED)

    @pytest.mark.parametrize("ids", [["not-a-uuid"], [str(uuid4()) for _ in range(1001)], "not-a-list"])
    def test_malformed_heartbeats_are_refused(self, ids):
        with pytest.raises(VpnSessionDenied, match=r"vpn\.invalid_request"):
            renew_vpn_sessions(server="vpn-a", session_ids=ids)
