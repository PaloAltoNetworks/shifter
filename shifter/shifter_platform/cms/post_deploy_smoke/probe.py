"""Connectivity probes for post-deploy smoke tests."""

from __future__ import annotations

import socket
from collections.abc import Callable


def tcp_reachable(host: str, port: int, *, timeout_seconds: float = 10.0) -> bool:
    """Return True when a TCP connection to host:port succeeds within the timeout."""
    with socket.create_connection((host, port), timeout=timeout_seconds):
        return True


def probe_ssh_endpoint(
    host: str,
    port: int,
    *,
    timeout_seconds: float = 10.0,
    connect_fn: Callable[[str, int, float], bool] | None = None,
) -> None:
    """Verify that the SSH endpoint accepts a TCP connection."""
    checker = connect_fn or (lambda h, p, t: tcp_reachable(h, p, timeout_seconds=t))
    if not checker(host, port, timeout_seconds):
        msg = f"SSH endpoint unreachable at {host}:{port}"
        raise RuntimeError(msg)


def probe_rdp_endpoint(
    host: str,
    port: int,
    *,
    timeout_seconds: float = 10.0,
    connect_fn: Callable[[str, int, float], bool] | None = None,
) -> None:
    """Verify that the RDP endpoint accepts a TCP connection."""
    checker = connect_fn or (lambda h, p, t: tcp_reachable(h, p, timeout_seconds=t))
    if not checker(host, port, timeout_seconds):
        msg = f"RDP endpoint unreachable at {host}:{port}"
        raise RuntimeError(msg)
