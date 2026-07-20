"""Executed coverage for the in-guest probe transport (issue #1347).

The transport carries the anti-MITM guarantee: it refuses to run without a guest
host identity and pins the SSH connection to that host key, so an impostor server
cannot return a forged all-secure envelope. These tests execute that real logic
(the ``asyncssh`` third-party boundary is faked, not the first-party seam), so the
host-key check and the nonzero-exit rejection go red if either is removed.
"""

from __future__ import annotations

from typing import Any

import pytest

from engine.services import _range_escape
from engine.services._range_escape import GuestProbeError, GuestProbeRequest, run_guest_probe


class _FakeResult:
    def __init__(self, stdout: str, exit_status: int) -> None:
        self.stdout = stdout
        self.exit_status = exit_status


class _FakeConn:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.run_calls: list[dict[str, Any]] = []

    async def run(self, command: str, *, input: str, timeout: int) -> _FakeResult:
        self.run_calls.append({"command": command, "input": input, "timeout": timeout})
        return self._result

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeAsyncssh:
    """Minimal asyncssh stand-in recording how the connection is pinned."""

    class Error(Exception):
        pass

    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.known_hosts_input: str | None = None
        self.connect_kwargs: dict[str, Any] = {}

    def import_private_key(self, data: str) -> str:
        return f"key:{data}"

    def import_known_hosts(self, data: str) -> str:
        self.known_hosts_input = data
        return f"known_hosts:{data}"

    def connect(self, host: str, **kwargs: Any) -> _FakeConn:
        self.connect_kwargs = {"host": host, **kwargs}
        return _FakeConn(self._result)


def _install_fake(monkeypatch: pytest.MonkeyPatch, result: _FakeResult) -> _FakeAsyncssh:
    fake = _FakeAsyncssh(result)
    monkeypatch.setattr(_range_escape, "asyncssh", fake)
    return fake


def _request(**overrides: object) -> GuestProbeRequest:
    base: dict[str, object] = {
        "host": "10.0.0.4",
        "username": "kali",
        "private_key": "PRIV",
        "host_public_key": "ssh-ed25519 AAAAKEY",
        "command": "bash -s",
        "stdin": "program",
    }
    base.update(overrides)
    return GuestProbeRequest(**base)  # type: ignore[arg-type]


def test_missing_host_key_refuses_to_run() -> None:
    request = _request(host_public_key="   ")
    with pytest.raises(GuestProbeError, match="missing guest host identity"):
        run_guest_probe(request)


def test_connection_is_pinned_to_host_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake(monkeypatch, _FakeResult(stdout="__ESCAPE_RECORD__{}__END__", exit_status=0))

    out = run_guest_probe(_request())

    assert out == "__ESCAPE_RECORD__{}__END__"
    # The known_hosts is pinned to the supplied host key, not accept-any.
    assert fake.known_hosts_input == "10.0.0.4 ssh-ed25519 AAAAKEY\n"
    assert fake.connect_kwargs["known_hosts"] == "known_hosts:10.0.0.4 ssh-ed25519 AAAAKEY\n"


def test_nonzero_remote_exit_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, _FakeResult(stdout="partial", exit_status=1))
    request = _request()

    with pytest.raises(GuestProbeError, match="exited 1"):
        run_guest_probe(request)
