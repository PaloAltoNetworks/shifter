"""Independent, bounded guest OS observations for the RAES realization gate."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from typing import Any

from executors.factory import build_guest_execution_context
from raes_plan import RaesPlan

_MAX_OBSERVATION_BYTES = 4096
_LINUX_PROBE = "head -c 4097 /etc/os-release"
_WINDOWS_PROBE = """$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
@{family='windows'; product_type=[int]$os.ProductType;
  version=[string]$os.Version; caption=[string]$os.Caption} | ConvertTo-Json -Compress
"""
_LINUX_DISTRIBUTIONS = {
    "ubuntu": "ubuntu",
    "debian": "debian",
    "rocky": "rocky-linux",
    "rhel": "red-hat-enterprise-linux",
    "alpine": "x-shifter:alpine",
    "kali": "x-shifter:kali",
}


def _fail() -> ValueError:
    """Handle fail."""
    return ValueError("operating-system observation is unavailable or invalid")


def _version(value: object) -> str:
    """Handle version."""
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value != value.strip():
        raise _fail()
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise _fail()
    return value


def _linux_identity(output: str) -> dict[str, str]:
    """Handle linux identity."""
    values = _linux_release_values(output)
    distribution = _LINUX_DISTRIBUTIONS.get(values.get("ID", ""))
    if distribution is None:
        raise _fail()
    version = _linux_release_version(distribution, values)
    return {"family": "linux", "distribution": distribution, "version": version}


def _linux_release_values(output: str) -> dict[str, str]:
    """Handle linux release values."""
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in {"ID", "VERSION_ID", "VERSION_CODENAME"}:
            continue
        if key in values:
            raise _fail()
        parts = shlex.split(value)
        if len(parts) != 1:
            raise _fail()
        values[key] = parts[0]
    return values


def _linux_release_version(distribution: str, values: dict[str, str]) -> str:
    """Handle linux release version."""
    version = values.get("VERSION_ID")
    # This namespaced distribution declares its rolling channel explicitly;
    # do not infer it from a downloaded image name or numeric release label.
    if distribution == "x-shifter:kali" and values.get("VERSION_CODENAME") == "kali-rolling":
        version = "rolling"
    if distribution == "x-shifter:alpine":
        # Shifter's Alpine vocabulary names the major.minor release family.
        # A guest patch level belongs to that family, never to another minor.
        match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?", _version(version))
        if match is None:
            raise _fail()
        version = f"{match[1]}.{match[2]}"
    return _version(version)


def _windows_identity(output: str) -> dict[str, str]:
    """Handle windows identity."""
    payload = json.loads(output)
    if not isinstance(payload, dict) or set(payload) != {"family", "product_type", "version", "caption"}:
        raise _fail()
    if payload["family"] != "windows" or type(payload["product_type"]) is not int:
        raise _fail()
    product = payload["product_type"]
    if product not in {2, 3}:
        raise _fail()
    version = _version(payload["version"])
    release = {"10.0.17763": "2019", "10.0.20348": "2022", "10.0.26100": "2025"}.get(version)
    caption = payload["caption"]
    if (
        release is None
        or not isinstance(caption, str)
        or not re.fullmatch(rf"Microsoft Windows Server {release}(?: [A-Za-z0-9 ()-]+)?", caption)
    ):
        raise _fail()
    return {
        "family": "windows",
        "distribution": "windows-server",
        "version": release,
    }


def _observe(output: dict[str, Any], family: str, execution_builder: Callable[..., Any]) -> dict[str, str]:
    """Handle observe."""
    if family not in {"linux", "windows"}:
        raise _fail()
    execution = execution_builder(output, os_type=family, role="raes-node")
    try:
        if execution.wait_for_ready(timeout_seconds=600) is False:
            raise _fail()
        result = execution.executor.run_command(
            execution.target,
            _WINDOWS_PROBE if family == "windows" else _LINUX_PROBE,
            timeout_seconds=30,
            document_name=execution.document_name,
        )
        if not result.success or result.exit_code != 0 or not isinstance(result.stdout, str):
            raise _fail()
        if len(result.stdout.encode("utf-8")) > _MAX_OBSERVATION_BYTES:
            raise _fail()
        return _windows_identity(result.stdout) if family == "windows" else _linux_identity(result.stdout)
    finally:
        execution.close()


def observe_operating_systems(
    plan: RaesPlan,
    instance_outputs: list[dict[str, Any]],
    *,
    execution_builder: Callable[..., Any] = build_guest_execution_context,
) -> list[dict[str, str]]:
    """Read every concrete guest; never infer its identity from an image alias.

    The authenticated channel and probe provide the observation. The requested
    family selects only the transport/probe dialect; the probe must succeed and
    return its own bounded identity. Neither provider outputs nor authored OS
    values are copied into the observation.
    """
    expected = {f"{node.address}#{index}": node for node in plan.nodes for index in range(node.count)}
    outputs = {output.get("uuid"): output for output in instance_outputs}
    if len(outputs) != len(instance_outputs) or set(outputs) != set(expected):
        raise ValueError("operating-system instance coverage is incomplete or ambiguous")
    observations: list[dict[str, str]] = []
    try:
        for instance_key, node in expected.items():
            identity = _observe(outputs[instance_key], node.os_family or "linux", execution_builder)
            observations.append({"instance_key": instance_key, **identity})
    except Exception:
        raise _fail() from None
    return observations


def validate_operating_systems(plan: RaesPlan, observations: object) -> None:
    """Require complete guest evidence to meet every authored OS value."""
    if not isinstance(observations, list):
        raise _fail()
    expected = {f"{node.address}#{index}": node for node in plan.nodes for index in range(node.count)}
    seen: set[str] = set()
    for observation in observations:
        key = _validate_operating_system(observation, expected)
        if key in seen:
            raise _fail()
        seen.add(key)
    if seen != set(expected):
        raise _fail()


def _validate_operating_system(observation: object, expected: dict[str, Any]) -> str:
    """Handle validate operating system."""
    required = {"instance_key", "family", "distribution", "version"}
    if not isinstance(observation, dict) or set(observation) != required:
        raise _fail()
    key = observation["instance_key"]
    if not all(isinstance(value, str) for value in observation.values()) or key not in expected:
        raise _fail()
    node = expected[key]
    authored = (
        (node.os_family, observation["family"]),
        (node.os_distribution, observation["distribution"]),
        (node.os_version, observation["version"]),
    )
    if any(wanted is not None and actual != wanted for wanted, actual in authored):
        raise _fail()
    _version(observation["version"])
    return key
