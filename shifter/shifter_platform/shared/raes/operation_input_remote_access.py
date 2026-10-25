"""Validate the optional OpenVPN remote-access authority riding an RAES input (#2030, #2480).

The Engine projects the range's persisted ``remote_access_capability`` so the
provisioner never reads it from ``mission_control_range`` (ADR-043). The
capability's teardown window is deliberately not checked here: destroy must
still delete the generation's profile after the deadline has passed. Provision
and activation re-check the window before minting any credential.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.remote_access import OpenVpnBindingError, parse_openvpn_capability

from .operation_input_identity import RaesOperationInputError, _require_exact_keys, _require_mapping

_FIELD = "raes operation input remote access"
_REMOTE_ACCESS_KEYS = frozenset({"capability"})


@dataclass(frozen=True)
class RaesRemoteAccess:
    """The range's canonical OpenVPN capability."""

    capability: dict[str, object]

    @property
    def target_ref(self) -> str:
        """Return the single range member the capability authorizes."""
        return str(self.capability["target_ref"])

    def to_transport(self) -> dict[str, object]:
        """Return the JSON-serialisable transport shape."""
        return {"capability": dict(self.capability)}


def parse_remote_access(value: object) -> RaesRemoteAccess:
    """Parse the exact remote-access projection, failing closed on any tamper."""
    obj = _require_mapping(value, _FIELD)
    _require_exact_keys(obj, _REMOTE_ACCESS_KEYS, _FIELD)
    try:
        capability = parse_openvpn_capability(obj["capability"])
    except OpenVpnBindingError:
        raise RaesOperationInputError(f"{_FIELD} capability is invalid") from None
    return RaesRemoteAccess(capability=capability.as_dict())
