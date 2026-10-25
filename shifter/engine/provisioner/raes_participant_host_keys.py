"""Observe participant SSH identities through the already pinned management lane."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from typing import Any

from cryptography.hazmat.primitives.serialization import load_ssh_public_key
from shared.model_access.network import RFC1918_IPV4_NETWORKS

from executors.factory import GuestExecutionContext, build_guest_execution_context

_ALGORITHMS = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ssh-rsa")


def _key(output: str) -> str:
    """Validate observed SSH keys and select the strongest supported algorithm."""
    if not isinstance(output, str) or not 1 <= len(output.encode()) <= 8192:
        raise ValueError("Participant SSH host identity is unavailable")
    keys = _parse_host_keys(output)
    for algorithm in _ALGORITHMS:
        if algorithm in keys:
            return keys[algorithm]
    raise ValueError("Participant SSH host identity is unavailable")


def _parse_host_keys(output: str) -> dict[str, str]:
    """Reject malformed or conflicting observations before choosing a host key."""
    keys: dict[str, str] = {}
    for line in output.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3 or fields[1] not in _ALGORITHMS:
            raise ValueError("Participant SSH host identity is malformed")
        algorithm = fields[1]
        value = " ".join(fields[1:])
        load_ssh_public_key(value.encode())
        if algorithm in keys and keys[algorithm] != value:
            raise ValueError("Participant SSH host identity is ambiguous")
        keys[algorithm] = value
    return keys


def observe_participant_host_keys(
    instances: list[dict[str, Any]],
    *,
    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context,
) -> None:
    """Never substitute a management-server key for a distinct participant server."""
    for instance in instances:
        if "ssh" not in instance.get("participant_access_channels", []):
            continue
        port = instance.get("host_ssh_port", instance.get("gcp_host_ssh_port", 22))
        management_key = instance.get("host_public_key", instance.get("gcp_host_public_key", ""))
        if port == 22:
            if not management_key:
                raise ValueError("Pinned SSH host identity is unavailable")
            instance["participant_ssh_host_public_key"] = management_key
            continue
        _observe_separate_participant_key(instance, execution_builder)


def _observe_separate_participant_key(
    instance: dict[str, Any],
    execution_builder: Callable[..., GuestExecutionContext],
) -> None:
    """Read the distinct participant listener through the pinned management connection."""
    address = ipaddress.IPv4Address(instance["private_ip"])
    if not any(address in network for network in RFC1918_IPV4_NETWORKS):
        raise ValueError("Participant SSH address is outside the guest network")
    context = execution_builder(instance, os_type=instance["os"])
    try:
        if not context.wait_for_ready(60):
            raise ValueError("Management transport is unavailable for participant identity readback")
        command = f"ssh-keyscan -T 5 -p 22 -t ed25519,ecdsa,rsa {address}"
        if instance["os"] == "windows":
            command = "$ErrorActionPreference = 'Stop'\n" + command + "\nif ($LASTEXITCODE -ne 0) { exit 1 }"
        result = context.executor.run_command(
            context.target, command, timeout_seconds=30, document_name=context.document_name
        )
        if not result.success or result.exit_code != 0:
            raise ValueError("Participant SSH host identity readback failed")
        instance["participant_ssh_host_public_key"] = _key(result.stdout)
    finally:
        context.close()
