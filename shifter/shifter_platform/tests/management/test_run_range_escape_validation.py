"""Management-command tests for run_range_escape_validation (issue #1347).

These drive the command wiring with a monkeypatched range resolver and a fake
probe launcher (no DB range, no SSH): report JSON is written, the verdict is
computed, multi-range mode is entered when a peer is supplied, and a leaked
boundary exits non-zero via CommandError.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from cms.management.commands import run_range_escape_validation as cmd_mod
from cms.range_escape.model import ObservedProbe, ParticipantContext, ProbeOutcome, ProbeTarget, RangeUnderTest
from shared.range_escape import BoundaryCode, Outcome

_CONFIG = {
    "platform": {
        "pod_cidr": "10.4.0.0/14",
        "service_cidr": "10.8.0.0/20",
        "node_cidr": "10.128.0.0/20",
        "portal_private_endpoints": ["10.128.0.10:5432"],
        "gke_gdc_api_endpoint": "10.128.0.2",
        "private_dns_names": ["kubernetes.default.svc"],
    },
    "egress": {"mode": "deny-all", "canaries": ["198.51.100.10"]},
}


def _range(range_id: int) -> RangeUnderTest:
    member = f"10.50.{range_id}.4"
    return RangeUnderTest(
        range_id=range_id,
        request_id=f"req-{range_id}",
        subnet_cidrs=(f"10.50.{range_id}.0/28",),
        member_ips=(member,),
        participant=ParticipantContext(
            range_id=range_id,
            request_id=f"req-{range_id}",
            target_ref="u",
            address=member,
            ssh_port=22,
            credential_ref="secret://ssh",
            username="kali",
        ),
        dns_names=(f"vm-{range_id}.zone-a.c.proj.internal",),
    )


class _SecureLauncher:
    def launch(
        self, participant: ParticipantContext, targets: Sequence[ProbeTarget], *, per_target_timeout_s: int = 4
    ) -> dict[str, ObservedProbe]:
        record: dict[str, ObservedProbe] = {}
        for target in targets:
            if target.expected == Outcome.REACHABLE:
                record[target.check_id] = ObservedProbe(outcome=ProbeOutcome.REACHABLE)
            else:
                record[target.check_id] = ObservedProbe(outcome=ProbeOutcome.BLOCKED)
        return record


class _LeakyLauncher(_SecureLauncher):
    def launch(
        self, participant: ParticipantContext, targets: Sequence[ProbeTarget], *, per_target_timeout_s: int = 4
    ) -> dict[str, ObservedProbe]:
        record = super().launch(participant, targets, per_target_timeout_s=per_target_timeout_s)
        for target in targets:
            if target.boundary_code == BoundaryCode.PLATFORM_POD_CIDR:
                record[target.check_id] = ObservedProbe(outcome=ProbeOutcome.REACHABLE, detail="leaked")
        return record


def _write_config(tmp_path) -> str:
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(_CONFIG))
    return str(path)


def test_command_writes_report_and_passes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cmd_mod, "resolve_range_under_test", lambda **kw: _range(1))
    monkeypatch.setattr(cmd_mod, "build_launcher", lambda adapter: _SecureLauncher())
    out = tmp_path / "report.json"

    call_command(
        "run_range_escape_validation",
        "--request-id",
        "req-1",
        "--config",
        _write_config(tmp_path),
        "--output",
        str(out),
    )

    data = json.loads(out.read_text())
    assert data["verdict"] == "passed"
    assert data["mode"] == "one_range"
    assert data["contract"] == "shifter.gcp-range-escape"


def test_command_emits_containment_signal(tmp_path, monkeypatch, caplog) -> None:
    # #1295: every validation run also emits the report to the #2087 containment
    # seam (default structured-logging sink), not only the pre-event gate.
    monkeypatch.setattr(cmd_mod, "resolve_range_under_test", lambda **kw: _range(1))
    monkeypatch.setattr(cmd_mod, "build_launcher", lambda adapter: _SecureLauncher())

    with caplog.at_level(logging.INFO, logger="shifter.range_escape.containment"):
        call_command(
            "run_range_escape_validation",
            "--request-id",
            "req-1",
            "--config",
            _write_config(tmp_path),
            "--output",
            str(tmp_path / "report.json"),
        )

    signal = next(r for r in caplog.records if r.getMessage() == "range-escape containment signal")
    assert signal.verdict == "passed"
    assert signal.range_escape_contract == "shifter.gcp-range-escape"


def test_command_exits_nonzero_on_leak(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(cmd_mod, "resolve_range_under_test", lambda **kw: _range(1))
    monkeypatch.setattr(cmd_mod, "build_launcher", lambda adapter: _LeakyLauncher())
    config = _write_config(tmp_path)

    with (
        caplog.at_level(logging.INFO, logger="shifter.range_escape.containment"),
        pytest.raises(CommandError) as excinfo,
    ):
        call_command("run_range_escape_validation", "--request-id", "req-1", "--config", config)

    assert "platform_pod_cidr" in str(excinfo.value)
    # The containment signal must still fire on the leak path before the gate
    # raises -- that failed verdict is exactly what #2087 monitoring exists to
    # catch, so a future edit that only emitted on success must fail here.
    signal = next(r for r in caplog.records if r.getMessage() == "range-escape containment signal")
    assert signal.verdict == "failed"
    assert "platform_pod_cidr" in signal.failed_boundaries


def test_command_enters_multi_range_with_peer(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        cmd_mod,
        "resolve_range_under_test",
        lambda **kw: _range(1) if kw["request_id"] == "req-1" else _range(2),
    )
    monkeypatch.setattr(cmd_mod, "build_launcher", lambda adapter: _SecureLauncher())
    out = tmp_path / "report.json"

    call_command(
        "run_range_escape_validation",
        "--request-id",
        "req-1",
        "--peer-request-id",
        "req-2",
        "--config",
        _write_config(tmp_path),
        "--output",
        str(out),
    )

    data = json.loads(out.read_text())
    assert data["mode"] == "multi_range"
    assert data["verdict"] == "passed"
    assert data["peer_range_ids"] == [2]
