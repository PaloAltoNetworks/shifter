"""Probe-launch adapters for the range-escape suite (issue #1347).

An adapter runs the bounded probe program in a range's participant context and
returns the parsed observations. This is the durable extensibility seam: a native
VM participant SSH session, a scenario container exec (Polaris), or a future RAES
participant-runtime launcher all satisfy the same :class:`cms.range_escape.runner.ProbeLauncher`
protocol without changing the report schema.

Credentials are resolved only through the existing secret store, and the in-guest
transport is the portal's ``engine.services.run_guest_probe``. Both are injected so
tests exercise the adapter without SSH or a live secret store.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from cms.range_escape.model import ObservedProbe, ParticipantContext, ProbeTarget
from cms.range_escape.probe import parse_probe_record, render_probe_program

if TYPE_CHECKING:
    from engine.services import GuestProbeRequest

SecretReader = Callable[[str], str]
GuestExec = Callable[["GuestProbeRequest"], str]

# Headroom added to (per-target timeout x target count) for SSH setup and probe
# overhead, so a fully-closed multi-target run is not killed before it emits its
# report (which would turn a secure range into a spurious probe failure).
_TRANSPORT_OVERHEAD_S = 30
_DEFAULT_PER_TARGET_TIMEOUT_S = 4


def _default_secret_reader(secret_ref: str) -> str:
    """Resolve an SSH private key from the platform secret store."""
    from engine.services import get_ssh_key

    return get_ssh_key(secret_ref)


def _default_guest_exec(request: GuestProbeRequest) -> str:
    """Default guest-exec: run the probe over the portal SSH transport."""
    from engine.services import run_guest_probe

    return run_guest_probe(request)


class NativeVmProbeLauncher:
    """Runs the probe over participant SSH directly on a native range VM."""

    # The remote delivery command. Scenario adapters override the template and the
    # default container; a ``{container}`` placeholder is filled per participant.
    _COMMAND_TEMPLATE = "bash -s"
    _DEFAULT_CONTAINER = ""

    def __init__(self, *, secret_reader: SecretReader | None = None, guest_exec: GuestExec | None = None) -> None:
        self._secret_reader = secret_reader or _default_secret_reader
        self._guest_exec = guest_exec or _default_guest_exec

    def _build_command(self, participant: ParticipantContext) -> str:
        """Render the remote delivery command for this adapter and participant."""
        container = shlex.quote(participant.container or self._DEFAULT_CONTAINER or "container")
        return self._COMMAND_TEMPLATE.format(container=container)

    def launch(
        self,
        participant: ParticipantContext,
        targets: Sequence[ProbeTarget],
        *,
        per_target_timeout_s: int = _DEFAULT_PER_TARGET_TIMEOUT_S,
    ) -> dict[str, ObservedProbe]:
        from engine.services import GuestProbeError, GuestProbeRequest

        program = render_probe_program(targets, per_target_timeout_s=per_target_timeout_s)
        private_key = self._secret_reader(participant.credential_ref)
        # The transport must outlive every per-target attempt run serially, or a
        # fully-closed range (all attempts time out) is killed before it reports.
        transport_timeout_s = per_target_timeout_s * max(1, len(targets)) + _TRANSPORT_OVERHEAD_S
        request = GuestProbeRequest(
            host=participant.address,
            username=participant.username,
            private_key=private_key,
            host_public_key=participant.host_public_key,
            command=self._build_command(participant),
            stdin=program,
            port=participant.ssh_port,
            timeout_s=transport_timeout_s,
        )
        try:
            stdout = self._guest_exec(request)
        except GuestProbeError:
            # A probe that could not verifiably run yields no observations; the
            # runner marks every target fail-closed rather than passing.
            return {}
        return parse_probe_record(stdout)


class PolarisContainerProbeLauncher(NativeVmProbeLauncher):
    """Runs the probe inside a scenario participant container (Polaris reference adopter).

    Polaris participants operate from a container on the range's Docker-host VM, so
    the participant context is the container, reached through ``docker exec`` on the
    host. This is a scenario-owned adapter; the scenario-neutral core is unchanged.
    """

    _COMMAND_TEMPLATE = "sudo docker exec -i {container} bash -s"
    _DEFAULT_CONTAINER = "a14-kali"


__all__ = ["GuestExec", "NativeVmProbeLauncher", "PolarisContainerProbeLauncher", "SecretReader"]
