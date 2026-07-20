"""End-to-end execution test for the rendered escape probe (issue #1347).

The other tests inject observations; this one actually runs the rendered probe
program through ``bash`` against controlled local targets, so the probe's core
soundness property is pinned: a live target reads ``reachable``, a closed local
port reads ``refused`` (the network path reached the host), and a probe that
cannot run its tools reads ``error`` (never a silent secure pass). These three are
deterministic on a Linux host; the ``blocked`` outcome is the timeout path
(``timeout`` exit 124) and is not asserted here because a guaranteed silent-drop
target is not portable across CI environments.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess

import pytest

from cms.range_escape.model import ProbeKind, ProbeOutcome, ProbeTarget
from cms.range_escape.probe import parse_probe_record, render_probe_program
from shared.range_escape import BoundaryCode, DestinationClass, Outcome

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required to execute the probe")


def _tcp_target(check_id: str, address: str, port: int) -> ProbeTarget:
    return ProbeTarget(
        check_id=check_id,
        boundary_code=BoundaryCode.PLATFORM_POD_CIDR,
        destination_class=DestinationClass.PLATFORM_POD,
        kind=ProbeKind.TCP_CONNECT,
        expected=Outcome.UNREACHABLE,
        address=address,
        port=port,
    )


def _run_probe(program: str, env: dict[str, str], timeout: int = 20) -> dict[str, ProbeOutcome]:
    # Invoke bash by absolute path so it execs even when the probe's own PATH is
    # emptied (the capability-failure case), which exercises the in-script tool
    # lookup rather than blocking the interpreter launch itself.
    bash = shutil.which("bash") or "/bin/bash"
    proc = subprocess.run(  # noqa: S603 - fixed argv, controlled program, test-only
        [bash],
        input=program,
        text=True,
        capture_output=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    return {cid: obs.outcome for cid, obs in parse_probe_record(proc.stdout).items()}


def _free_closed_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_probe_distinguishes_reachable_from_refused() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    live_port = listener.getsockname()[1]
    closed_port = _free_closed_port()

    targets = [
        _tcp_target("reach", "127.0.0.1", live_port),
        _tcp_target("refuse", "127.0.0.1", closed_port),
    ]
    env = dict(os.environ)
    env["ESCAPE_PROBE_TIMEOUT"] = "2"
    try:
        outcomes = _run_probe(render_probe_program(targets), env)
    finally:
        listener.close()

    assert outcomes["reach"] is ProbeOutcome.REACHABLE
    # A closed local port answers with a reset: the path reached the host, so this
    # is refused (a fail for a should-be-unreachable boundary), not a secure block.
    assert outcomes["refuse"] is ProbeOutcome.REFUSED


def test_probe_reports_error_when_capability_missing() -> None:
    # With an empty PATH the probe cannot find its tools; the attempt must be an
    # error (inconclusive), never a secure "blocked".
    targets = [_tcp_target("t", "127.0.0.1", 22)]
    env = {"PATH": "", "ESCAPE_PROBE_TIMEOUT": "1"}
    outcomes = _run_probe(render_probe_program(targets), env)
    assert outcomes["t"] is ProbeOutcome.ERROR


def test_probe_addresses_are_data_not_shell(tmp_path) -> None:
    # A target address is data, never shell: a shell-metacharacter-shaped address is
    # rejected before rendering, so it can never construct a command or execute.
    marker = tmp_path / "pwned"
    targets = [_tcp_target("reach", "127.0.0.1", 80), _tcp_target("evil", f"127.0.0.1$(touch {marker})", 80)]
    with pytest.raises(ValueError, match="unsafe probe target"):
        render_probe_program(targets)
    assert not marker.exists()
