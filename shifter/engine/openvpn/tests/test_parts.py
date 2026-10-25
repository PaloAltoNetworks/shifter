"""Management parsing, nft rendering, configuration, server files, and the portal client (#2480)."""

from __future__ import annotations

import ipaddress
import json
import os
import pwd
import socket
import threading
import urllib.request

import pytest

from shifter_openvpn import portal as portal_module
from shifter_openvpn.config import ConfigError, load_config
from shifter_openvpn.firewall import Firewall, base_ruleset
from shifter_openvpn.management import Management, parse_event_header
from shifter_openvpn.portal import PortalClient, PortalRefused, PortalUnavailable
from shifter_openvpn.server_config import render, write_config, write_material

_MATERIAL = {"ca": "C", "certificate": "S", "private_key": "K", "tls_crypt": "T"}
_GRANT = {"session": "s", "target": "10.50.3.3", "ports": [22], "heartbeat_seconds": 15}
_ENV = {
    "PORTAL_URL": "https://portal.example.com",
    "CONTROL_AUDIENCE": "https://portal.example.com/vpn-control",
    "SERVER_SECRET": "projects/p/secrets/shifter-test-vpn-server",
    "SERVER_NAME": "shifter-test-vpn-abcd",
    "TUNNEL_NETWORK": "100.96.0.0/22",
}


class TestManagement:
    def test_event_headers(self):
        assert parse_event_header(">CLIENT:CONNECT,4,1") == ("CONNECT", 4, 1)
        assert parse_event_header(">CLIENT:ESTABLISHED,4") == ("ESTABLISHED", 4, None)
        assert parse_event_header(">CLIENT:ENV,common_name=x") is None
        assert parse_event_header(">INFO:OpenVPN Management Interface") is None
        assert parse_event_header(">CLIENT:CONNECT,x,1") is None

    def test_a_connect_block_becomes_one_event_and_commands_get_their_reply(self, tmp_path):
        path = str(tmp_path / "m.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        received: list[str] = []

        def openvpn():
            conn, _ = server.accept()
            stream = conn.makefile("rw", encoding="utf-8", newline="\n")
            stream.write(">INFO:hello\n>CLIENT:CONNECT,4,1\n>CLIENT:ENV,common_name=participant-x\n>CLIENT:ENV,END\n")
            stream.flush()
            for line in stream:
                received.append(line.strip())
                if line.strip() == "END":
                    stream.write("SUCCESS: client-auth command succeeded\n")
                    stream.flush()
                if line.startswith("client-kill"):
                    stream.write("ERROR: client not found\n")
                    stream.flush()
                    break
            conn.close()

        thread = threading.Thread(target=openvpn, daemon=True)
        thread.start()
        management = Management(path)

        event = management.events.get(timeout=5)
        assert (event.kind, event.cid, event.kid, event.env) == ("CONNECT", 4, 1, {"common_name": "participant-x"})
        management.allow(4, 1, ['push "route 10.50.3.3 255.255.255.255"'])
        assert received == ["client-auth 4 1", 'push "route 10.50.3.3 255.255.255.255"', "END"]
        with pytest.raises(Exception, match="client not found"):
            management.kill(9)
        assert management.events.get(timeout=5) is None  # the socket closed


class TestFirewall:
    def test_the_base_ruleset_drops_forwarding_and_tunnel_input_by_default(self):
        ruleset = base_ruleset(ipaddress.ip_network("100.96.0.0/22"))
        assert "type filter hook forward priority filter; policy drop;" in ruleset
        assert 'iifname "tun0" drop' in ruleset
        assert "ip saddr . ip daddr . tcp dport @allowed accept" in ruleset
        assert "ip saddr 100.96.0.0/22" in ruleset

    def test_allowances_are_validated_before_reaching_nft(self):
        scripts: list[str] = []
        firewall = Firewall(runner=scripts.append)
        firewall.allow("100.96.0.2", "10.50.3.3", (3389, 22))
        firewall.revoke("100.96.0.2", "10.50.3.3", (22,))
        assert scripts == [
            "add element inet shifter_vpn allowed { 100.96.0.2 . 10.50.3.3 . 22, 100.96.0.2 . 10.50.3.3 . 3389 }\n",
            "delete element inet shifter_vpn allowed { 100.96.0.2 . 10.50.3.3 . 22 }\n",
        ]
        for client, target, ports in [
            ("x; flush", "10.50.3.3", (22,)),
            ("100.96.0.2", "10.50.3.3", ()),
            ("100.96.0.2", "10.50.3.3", (0,)),
        ]:
            with pytest.raises(ValueError):
                firewall.allow(client, target, ports)


class TestConfig:
    def test_a_complete_environment_loads(self, monkeypatch):
        for key, value in _ENV.items():
            monkeypatch.setenv(key, value)
        config = load_config()
        assert config.tunnel_network == ipaddress.ip_network("100.96.0.0/22")
        assert config.max_clients == 250

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("PORTAL_URL", "http://portal.example.com"),
            ("SERVER_SECRET", "not-a-secret-name"),
            ("SERVER_NAME", "Bad_Name"),
            ("TUNNEL_NETWORK", "100.96.0.0/28"),
            ("MAX_CLIENTS", "5000"),
            ("TUNNEL_NETWORK", ""),
        ],
    )
    def test_a_defective_environment_is_refused(self, monkeypatch, key, value):
        for name, setting in _ENV.items():
            monkeypatch.setenv(name, setting)
        monkeypatch.setenv(key, value)
        with pytest.raises((ConfigError, ValueError)):
            load_config()


class TestServerFiles:
    def test_material_is_owner_only_and_the_config_is_hardened(self, monkeypatch, tmp_path):
        for key, value in {**_ENV, "RUNTIME_DIR": str(tmp_path / "run")}.items():
            monkeypatch.setenv(key, value)
        config = load_config()
        write_material(
            config.runtime_dir, json.dumps({"ca": "C", "certificate": "S", "private_key": "K", "tls_crypt": "T"})
        )
        paths = write_config(config)
        assert oct(os.stat(os.path.join(config.runtime_dir, "server.key")).st_mode & 0o777) == "0o600"
        text = render(config)
        for directive in (
            "tls-crypt",
            "remote-cert-tls client",
            "verify-client-cert require",
            "management-client-auth",
            "auth-user-pass-optional",
            f"management-client-user {pwd.getpwuid(os.geteuid()).pw_name}",
            "max-clients 250",
            "keepalive 5 30",
            "explicit-exit-notify 1",
        ):
            assert directive in text
        # The server is already unprivileged; a user/group switch would need CAP_SETUID/SETGID.
        for forbidden in (
            "client-to-client",
            "redirect-gateway",
            "username-as-common-name",
            "duplicate-cn",
            "\nuser ",
            "\ngroup ",
        ):
            assert forbidden not in text
        assert paths.management_socket.endswith("management.sock")

    def test_material_with_extra_keys_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            write_material(
                str(tmp_path), json.dumps({"ca": "C", "certificate": "S", "private_key": "K", "tls_crypt": "T", "x": 1})
            )


class _Response:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def read(self, _limit=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class TestPortalClient:
    @pytest.fixture
    def client(self, monkeypatch):
        sent: list[urllib.request.Request] = []
        replies: list[tuple[int, bytes]] = []

        class Opener:
            def open(self, request, timeout):
                sent.append(request)
                status, body = replies.pop(0)
                if status >= 400:
                    import io
                    import urllib.error

                    raise urllib.error.HTTPError(request.full_url, status, "x", {}, io.BytesIO(body))
                return _Response(status, body)

        monkeypatch.setattr(portal_module.transport, "OPENER", Opener())
        client = PortalClient("https://portal.example.com", "aud", "vpn-a", lambda audience: f"token-for-{audience}")
        return client, sent, replies

    def test_authorize_sends_the_server_identity_and_returns_a_strict_grant(self, client):
        portal, sent, replies = client
        replies.append(
            (201, json.dumps({"session": "s", "target": "10.50.3.3", "ports": [22], "heartbeat_seconds": 15}).encode())
        )

        grant = portal.authorize("participant-x", 3, "198.51.100.2")

        assert (grant.session, grant.target, grant.ports) == ("s", "10.50.3.3", (22,))
        assert sent[0].full_url == "https://portal.example.com/api/v1/cms/vpn-control/sessions/"
        assert sent[0].get_header("Authorization") == "Bearer token-for-aud"
        assert json.loads(sent[0].data)["server"] == "vpn-a"

    @pytest.mark.parametrize(
        ("status", "body", "error"),
        [
            (403, b'{"error": "vpn.access_revoked"}', PortalRefused),
            (500, b"oops", PortalUnavailable),
            (
                201,
                b'{"session": "s", "target": "10.50.3.3", "ports": ["22"], "heartbeat_seconds": 15}',
                PortalUnavailable,
            ),
            (201, b"x" * 70_000, PortalUnavailable),
        ],
    )
    def test_anything_outside_the_contract_is_not_a_grant(self, client, status, body, error):
        portal, _sent, replies = client
        replies.append((status, body))
        with pytest.raises(error):
            portal.authorize("participant-x", 3, "198.51.100.2")

    def test_heartbeat_and_end(self, client):
        portal, sent, replies = client
        replies.extend([(200, b'{"disconnect": ["s"], "heartbeat_seconds": 15}'), (204, b"")])

        assert portal.heartbeat(["s"]) == ({"s"}, 15)
        portal.end("s")
        assert [request.full_url.rsplit("/vpn-control/", 1)[1] for request in sent] == ["heartbeat/", "sessions/end/"]
