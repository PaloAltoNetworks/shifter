"""Probe-launch adapter tests (issue #1347).

These exercise the adapter seam with an injected fake secret reader and fake guest
exec, so no SSH or secret store is touched. They confirm the native adapter
delivers the self-contained probe program over ``bash -s`` and the Polaris adapter
wraps it in a container exec, and that both parse the returned envelope.
"""

from __future__ import annotations

from collections.abc import Sequence

from cms.range_escape.adapters import NativeVmProbeLauncher, PolarisContainerProbeLauncher
from cms.range_escape.model import ParticipantContext, ProbeKind, ProbeOutcome, ProbeTarget
from engine.services import GuestProbeRequest
from shared.range_escape import BoundaryCode, DestinationClass, Outcome

_ENVELOPE = '__ESCAPE_RECORD__{"core.metadata_server":{"outcome":"blocked","metadata_credentials_useful":null}}__END__'


class _RecordingExec:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.calls: list[GuestProbeRequest] = []

    def __call__(self, request: GuestProbeRequest) -> str:
        self.calls.append(request)
        return self.stdout


def _participant(**overrides: object) -> ParticipantContext:
    base: dict[str, object] = {
        "range_id": 5,
        "request_id": "req-5",
        "target_ref": "linux-uuid",
        "address": "10.50.5.4",
        "ssh_port": 22,
        "credential_ref": "secret://ssh/5",
        "username": "kali",
        "host_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAtestkey",
    }
    base.update(overrides)
    return ParticipantContext(**base)  # type: ignore[arg-type]


def _targets() -> Sequence[ProbeTarget]:
    return [
        ProbeTarget(
            check_id="core.metadata_server",
            boundary_code=BoundaryCode.METADATA_SERVER,
            destination_class=DestinationClass.METADATA,
            kind=ProbeKind.METADATA,
            expected=Outcome.UNREACHABLE,
            address="169.254.169.254",
            hostname="metadata.google.internal",
        )
    ]


def test_native_adapter_delivers_program_over_bash_and_parses() -> None:
    fake_exec = _RecordingExec(_ENVELOPE)
    launcher = NativeVmProbeLauncher(secret_reader=lambda ref: f"KEY({ref})", guest_exec=fake_exec)

    record = launcher.launch(_participant(), _targets(), per_target_timeout_s=7)

    assert record["core.metadata_server"].outcome is ProbeOutcome.BLOCKED
    call = fake_exec.calls[0]
    assert call.command == "bash -s"
    assert call.host == "10.50.5.4"
    assert call.port == 22
    assert call.username == "kali"
    assert call.private_key == "KEY(secret://ssh/5)"
    assert call.host_public_key == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAtestkey"
    # Transport timeout is sized from per-target timeout x target count + overhead,
    # never just the per-probe budget, so a fully-closed run is not killed early.
    assert call.timeout_s == 7 * 1 + 30
    # The self-contained program embeds the target spec, the per-probe timeout, and
    # the record marker.
    assert "core.metadata_server|metadata|169.254.169.254" in call.stdin
    assert "ESCAPE_PROBE_TIMEOUT=7" in call.stdin
    assert "__ESCAPE_RECORD__" in call.stdin


def test_polaris_adapter_wraps_command_in_container_exec() -> None:
    fake_exec = _RecordingExec(_ENVELOPE)
    launcher = PolarisContainerProbeLauncher(secret_reader=lambda ref: "KEY", guest_exec=fake_exec)

    launcher.launch(_participant(container="a14-kali", adapter="polaris"), _targets())

    command = fake_exec.calls[0].command
    assert command.startswith("sudo docker exec -i ")
    assert "a14-kali" in command
    assert command.endswith("bash -s")
