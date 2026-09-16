"""Guacamole evidence levels, session-URL decoding, and target selection."""

from __future__ import annotations

import base64

import pytest

from range_functional_smoke import guacamole, targets
from range_functional_smoke.profile import Protocol


def _client_id(connection_name: str = "kali-rdp", data_source: str = "json") -> str:
    raw = f"{connection_name}\0c\0{data_source}".encode()
    return base64.b64encode(raw).decode().rstrip("=")


def _session_url(base: str = "https://p.example.com/guacamole", token: str = "TOK123") -> str:
    return f"{base}/#/client/{_client_id()}?token={token}"


@pytest.fixture
def range_payload() -> dict:
    """A POLARIS-shaped projection: an attacker with access and a dc without."""
    return {
        "has_range": True,
        "range": {
            "request_id": "11111111-1111-1111-1111-111111111111",
            "range_id": 6,
            "scenario_id": "polaris",
            "status": "ready",
            "is_ready": True,
            "instances": [
                {"uuid": "dc-uuid", "name": "dc01", "role": "dc", "os_type": "windows"},
                {"uuid": "kali-uuid", "name": "kali", "role": "attacker", "os_type": "kali"},
            ],
        },
        "connection_urls": [{"uuid": "kali-uuid", "terminal_url": "/mission-control/terminal/kali-uuid/"}],
    }


class TestBootstrapEvidenceLevels:
    def test_pending_is_admission_only(self):
        poll = guacamole.classify_poll(200, {"status": "pending"})
        assert poll.pending and not poll.succeeded and not poll.delivered

    def test_succeeded_without_a_url_is_not_delivery(self):
        poll = guacamole.classify_poll(200, {"status": "succeeded"})
        assert poll.succeeded
        assert not poll.delivered, "delivery is the poll that actually carries the one-time URL"

    def test_succeeded_with_a_url_is_delivery(self):
        poll = guacamole.classify_poll(200, {"status": "succeeded", "url": _session_url()})
        assert poll.succeeded and poll.delivered

    def test_consumed_url_returns_gone_and_is_not_delivery(self):
        poll = guacamole.classify_poll(410, {"status": "succeeded", "error": "no longer available"})
        assert not poll.delivered and not poll.pending

    def test_failure_states_are_neither_pending_nor_delivered(self):
        poll = guacamole.classify_poll(503, {"status": "failed", "error": "not configured"})
        assert not poll.pending and not poll.succeeded and not poll.delivered
        assert poll.error == "not configured"

    def test_bootstrap_path_follows_the_protocol_profile(self):
        assert guacamole.bootstrap_path(Protocol.RDP).endswith("/guacamole/rdp-url/")
        assert guacamole.bootstrap_path(Protocol.SSH).endswith("/guacamole/ssh-url/")


class TestSessionUrlDecoding:
    def test_decodes_tunnel_coordinates(self):
        target = guacamole.parse_session_url(_session_url())
        assert target.tunnel_url == "https://p.example.com/guacamole/tunnel"
        assert target.connection_id == "kali-rdp"
        assert target.data_source == "json"
        assert target.token == "TOK123"

    def test_token_is_kept_out_of_repr(self):
        target = guacamole.parse_session_url(_session_url(token="SUPERSECRET"))
        assert "SUPERSECRET" not in repr(target)

    def test_connect_params_carry_the_decoded_identity(self):
        params = guacamole.connect_params(guacamole.parse_session_url(_session_url()))
        assert params["GUAC_ID"] == "kali-rdp"
        assert params["GUAC_DATA_SOURCE"] == "json"
        assert params["GUAC_TYPE"] == "c"

    def test_plaintext_session_url_is_refused(self):
        """A server-returned URL must not be how plaintext gets reintroduced."""
        with pytest.raises(guacamole.GuacamoleCheckError, match="plaintext"):
            guacamole.parse_session_url(_session_url(base="http://p.example.com/guacamole"))

    def test_plaintext_session_url_allowed_for_loopback_opt_in(self):
        target = guacamole.parse_session_url(
            _session_url(base="http://127.0.0.1:8080/guacamole"), allow_plaintext_loopback=True
        )
        assert target.tunnel_url.startswith("http://127.0.0.1:8080/")
        assert guacamole.tunnel_ws_url(target).startswith("ws://")

    def test_https_session_url_yields_a_wss_tunnel(self):
        """The token rides the tunnel query string, so it must be encrypted."""
        assert guacamole.tunnel_ws_url(guacamole.parse_session_url(_session_url())).startswith("wss://")

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://p.example.com/guacamole/#/client/abc?token=t",
            "https://p.example.com/guacamole/#/nope?token=t",
            "https://p.example.com/guacamole/#/client/abc",
            f"https://p.example.com/guacamole/#/client/{base64.b64encode(b'onlyone').decode()}?token=t",
        ],
    )
    def test_malformed_urls_are_refused(self, url):
        with pytest.raises(guacamole.GuacamoleCheckError):
            guacamole.parse_session_url(url)

    def test_tunnel_url_is_the_browser_websocket_path(self):
        url = guacamole.tunnel_ws_url(guacamole.parse_session_url(_session_url()))
        assert url.startswith("wss://p.example.com/guacamole/websocket-tunnel?")
        assert "GUAC_ID=kali-rdp" in url

    def test_relative_base_url_resolves_against_the_portal_origin(self):
        """GUACAMOLE_BASE_URL is commonly a path, not an absolute URL."""
        target = guacamole.parse_session_url(
            f"/guacamole/#/client/{_client_id()}?token=TOK123", base_origin="https://portal.example.com"
        )
        assert target.tunnel_url == "https://portal.example.com/guacamole/tunnel"


class TestConnectionLevelEvidence:
    """Only guacd's own ``ready`` opcode counts as a connected session."""

    def test_ready_instruction_is_recognised(self):
        assert guacamole.has_ready_instruction("5.ready,37.$260d01da-779b-4ee5-afaa-1c7ce6e50e00;")

    def test_error_instruction_is_not_a_connection(self):
        stream = "5.error,31.Connection failed: no route,3.519;"
        assert guacamole.is_error_instruction(stream)
        assert not guacamole.has_ready_instruction(stream)

    def test_the_word_ready_in_parameter_text_does_not_count(self):
        """Length-prefixed matching stops connection text from faking success."""
        assert not guacamole.has_ready_instruction("4.args,13.hostname-ready,6.status;")

    def test_an_empty_stream_is_not_a_connection(self):
        assert not guacamole.has_ready_instruction("")


class TestTargetSelection:
    def test_selects_by_authored_role_not_first_instance(self, range_payload):
        target = targets.select_target(range_payload, role="attacker")
        assert target.instance_uuid == "kali-uuid"
        assert target.instance_name == "kali"

    def test_a_target_the_portal_does_not_offer_is_refused(self, range_payload):
        """dc01 declares no participant access, so nothing offers it a terminal."""
        with pytest.raises(targets.TargetError, match="no terminal connection"):
            targets.select_target(range_payload, role="dc")

    def test_absent_role_is_an_error_not_a_skip(self, range_payload):
        with pytest.raises(targets.TargetError, match="no instance with authored role"):
            targets.select_target(range_payload, role="victim")

    def test_not_ready_range_blocks_the_run(self, range_payload):
        range_payload["range"]["status"] = "provisioning"
        range_payload["range"]["is_ready"] = False
        with pytest.raises(targets.TargetError, match="not ready"):
            targets.select_target(range_payload, role="attacker")

    def test_no_range_at_all_is_an_error(self):
        with pytest.raises(targets.TargetError, match="no active range"):
            targets.select_target({"has_range": False, "range": None}, role="attacker")

    def test_ambiguous_role_is_refused_rather_than_guessed(self, range_payload):
        range_payload["range"]["instances"].append({"uuid": "k2", "name": "kali2", "role": "attacker"})
        range_payload["connection_urls"].append({"uuid": "k2", "terminal_url": "/x/"})
        with pytest.raises(targets.TargetError, match="ambiguous"):
            targets.select_target(range_payload, role="attacker")
