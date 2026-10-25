"""The server's metadata identity, Secret Manager reads, health listener and startup wait (#2480)."""

from __future__ import annotations

import base64
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from shifter_openvpn import __main__ as entry
from shifter_openvpn import gcp


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def network(monkeypatch):
    """Replace only the opener's network call; record every request."""
    seen: list[urllib.request.Request] = []

    def open_(request, timeout):
        seen.append(request)
        url = request.full_url
        if url.endswith("/token"):
            return _Response(json.dumps({"access_token": "ya29.test"}).encode())
        if "/identity?" in url:
            return _Response(b"eyJ.identity.token\n")
        if url.startswith("https://secretmanager.googleapis.com/"):
            return _Response(json.dumps({"payload": {"data": base64.b64encode(b"material").decode()}}).encode())
        raise AssertionError(url)

    monkeypatch.setattr(gcp.transport.OPENER, "open", open_)
    return seen


def test_identity_tokens_are_full_format_for_the_audience(network):
    assert gcp.identity_token("https://portal.example.com/vpn-control") == "eyJ.identity.token"
    url = network[0].full_url
    assert "audience=https%3A%2F%2Fportal.example.com%2Fvpn-control" in url and "format=full" in url
    assert network[0].get_header("Metadata-flavor") == "Google"


def test_secrets_are_read_with_the_attached_identity(network):
    assert gcp.read_secret("projects/p/secrets/server") == "material"
    access = network[-1]
    assert access.full_url == "https://secretmanager.googleapis.com/v1/projects/p/secrets/server/versions/latest:access"
    assert access.get_header("Authorization") == "Bearer ya29.test"


def test_the_health_port_accepts_connections_once_serving(monkeypatch):
    monkeypatch.setattr(entry.socket, "gethostbyname", lambda _name: "127.0.0.1")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()

    threading.Thread(target=entry._serve_health, args=(port,), daemon=True).start()
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                assert connection.recv(1) == b""  # accepted, then closed with no data
                return
        except ConnectionRefusedError:
            time.sleep(0.05)
    raise AssertionError("health listener did not start")


class _Process:
    def __init__(self, exited: bool) -> None:
        self.exited = exited

    def poll(self):
        return 1 if self.exited else None


def test_startup_waits_for_the_management_socket(tmp_path):
    path = tmp_path / "management.sock"
    threading.Timer(0.3, path.touch).start()
    entry._wait_for_socket(str(path), _Process(exited=False), timeout=5)

    with pytest.raises(RuntimeError, match="management socket"):
        entry._wait_for_socket(str(tmp_path / "never"), _Process(exited=True), timeout=5)


def test_the_http_client_opens_only_http_and_never_follows_redirects():
    from shifter_openvpn import transport

    opener = transport.closed_opener()
    with pytest.raises(urllib.error.URLError, match="unknown url type"):
        opener.open("file:///etc/passwd")
    assert not any(isinstance(h, urllib.request.HTTPRedirectHandler) for h in opener.handlers)
    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in opener.handlers)


class _Stoppable:
    def __init__(self) -> None:
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self) -> int:
        return 0


def test_a_stop_signal_is_passed_to_openvpn_and_ends_cleanly(monkeypatch):
    stopping = threading.Event()
    process = _Stoppable()

    entry._forward_stop(process, stopping)(15, None)

    assert process.terminated and stopping.is_set()
    exits: list[int] = []
    monkeypatch.setattr(entry.os, "_exit", exits.append)
    entry._watch_openvpn(process, stopping)
    entry._watch_openvpn(process, threading.Event())
    assert exits == [0, 1]  # asked to stop vs. OpenVPN died on its own
