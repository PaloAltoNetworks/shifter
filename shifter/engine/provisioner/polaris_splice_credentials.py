"""Provider-neutral health and repair operations for Polaris splice credentials."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from executors.factory import GuestExecutionContext, build_guest_execution_context
from provisioner_db import get_range_data_by_request_id
from range_ops import get_range_instance_ids

_HOST_HELPER = "/opt/polaris/libexec/polaris-splice-credential.py"


class PolarisSpliceCredentialError(RuntimeError):
    """A bounded failure that never includes remote command output."""


@dataclass(frozen=True)
class PolarisSpliceCredentialResult:
    """Secret-free outcome returned to fleet callers."""

    status: str
    repaired: bool


def run_polaris_splice_credential_operation(
    instance_data: dict[str, Any],
    *,
    repair: bool,
    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context,
) -> PolarisSpliceCredentialResult:
    """Check or repair one Polaris host through its configured guest transport."""
    execution = execution_builder(
        instance_data,
        os_type=str(instance_data.get("os") or "ubuntu"),
        role=str(instance_data.get("role") or "attacker"),
    )
    try:
        mode = "host-repair" if repair else "host-check"
        result = execution.executor.run_command(
            execution.target,
            f"{_HOST_HELPER} {mode} --container a14-kali",
            timeout_seconds=120,
            document_name=execution.document_name,
        )
        if not result.success:
            operation = "repair" if repair else "check"
            raise PolarisSpliceCredentialError(f"Polaris splice credential {operation} failed")
        return PolarisSpliceCredentialResult(
            status="repaired" if repair else "healthy",
            repaired=repair,
        )
    finally:
        execution.close()


def _authored_instances(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index authored range instances by UUID."""
    return {
        str(instance.get("uuid") or ""): instance
        for subnet in spec.get("subnets", [])
        for instance in subnet.get("instances", [])
        if instance.get("uuid")
    }


def _execution_input(entry: dict[str, Any], authored: dict[str, Any]) -> dict[str, Any]:
    """Merge persisted provider state with authored execution metadata."""
    state = dict(entry.get("state") or {})
    provider = str(state.get("cloud_provider") or entry.get("cloud_provider") or "aws")
    metadata = (state.get("provider_metadata") or {}).get(provider, {})
    if isinstance(metadata, dict):
        if provider == "gcp":
            state.update({f"gcp_{key}": value for key, value in metadata.items()})
        else:
            state.update({f"{provider}_{key}": value for key, value in metadata.items()})
    state["os"] = authored.get("os") or "ubuntu"
    state["role"] = authored.get("role") or "attacker"
    return state


def run_request_polaris_splice_credential_operation(
    request_id: str,
    *,
    repair: bool,
) -> PolarisSpliceCredentialResult:
    """Check or repair the single Polaris host belonging to a range request."""
    range_data = get_range_data_by_request_id(request_id)
    authored_by_uuid = _authored_instances(range_data.get("spec") or {})
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entry in get_range_instance_ids(request_id):
        authored = authored_by_uuid.get(str(entry.get("uuid") or ""))
        if authored and authored.get("ami_key") == "polaris-vm":
            matches.append((entry, authored))
    if len(matches) != 1:
        raise PolarisSpliceCredentialError("range does not contain a Polaris host")
    entry, authored = matches[0]
    return run_polaris_splice_credential_operation(
        _execution_input(entry, authored),
        repair=repair,
    )
