"""Readiness contract for a preconfigured machine-image range host."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from .base import SetupStep

_WAIT_FOR_READY_SCRIPT = r"""#!/bin/bash
set -euo pipefail
container="{{ participant_container_name }}"
deadline=$((SECONDS + 900))
while (( SECONDS < deadline )); do
    if [ -e "/run/shifter/preconfigured-range-host.ready" ] \
        && [ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)" = "true" ] \
        && timeout 3 bash -c "</dev/tcp/127.0.0.1/3389" 2>/dev/null; then
        echo "Preconfigured range host is ready"
        exit 0
    fi
    sleep 10
done
echo "FATAL: preconfigured range host readiness timed out" >&2
exit 1
"""

PARTICIPANT_READINESS_EXECUTABLE = "/usr/local/libexec/shifter-participant-readiness"

_VERIFY_PARTICIPANT_READINESS_SCRIPT = rf"""#!/bin/bash
set -euo pipefail
container="{{{{ participant_container_name }}}}"
participant_user="{{{{ participant_user }}}}"
contract="{{{{ participant_readiness_contract }}}}"
manifest_sha256="{{{{ participant_readiness_manifest_sha256 }}}}"

if ! docker exec --user "${{participant_user}}" "${{container}}" \
    {PARTICIPANT_READINESS_EXECUTABLE} \
    --contract "${{contract}}" \
    --manifest-sha256 "${{manifest_sha256}}" >/dev/null 2>&1; then
    echo "participant-readiness: canary-failed" >&2
    exit 1
fi
echo "participant-readiness: passed"
"""


class PreconfiguredMachineHostPlan:
    """Wait for the image-owned nested workload and participant RDP endpoint."""

    name = "preconfigured_machine_host_readiness"
    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="wait_for_preconfigured_machine_host",
            script=_WAIT_FOR_READY_SCRIPT,
            timeout_seconds=930,
        ),
        SetupStep(
            name="verify_participant_readiness",
            script=_VERIFY_PARTICIPANT_READINESS_SCRIPT,
            timeout_seconds=180,
            is_verification=True,
        ),
    ]
    verify_step: ClassVar[SetupStep | None] = None

    @staticmethod
    def get_context(instance: Mapping[str, object]) -> dict[str, object]:
        """Return the validated profile-selected container name."""
        return {
            "participant_container_name": instance["gcp_participant_container_name"],
            "participant_user": instance["gcp_participant_username"],
            "participant_readiness_contract": instance["gcp_participant_readiness_contract"],
            "participant_readiness_manifest_sha256": instance["gcp_participant_readiness_manifest_sha256"],
        }


__all__ = ["PARTICIPANT_READINESS_EXECUTABLE", "PreconfiguredMachineHostPlan"]
