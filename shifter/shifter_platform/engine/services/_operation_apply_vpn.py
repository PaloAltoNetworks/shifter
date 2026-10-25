"""Bind realized participant OpenVPN access to its range owner (#2030, #2480, ADR-039-R10).

Split out of ``_operation_apply_raes`` (Sonar S104). The provisioner reports an
owner-free realization on the terminal READY result (ADR-043: ownership never
rides the operation input); the owner bound here is read from the locked range
row, so a warm claim's rehomed owner is the one that receives the profile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.models import OperationResultInbox, Range

__all__ = ["bound_vpn_access"]


def bound_vpn_access(
    row: OperationResultInbox, realization: dict[str, Any] | None, range_obj: Range
) -> dict[str, object] | None:
    """Return the owner-bound binding for this generation's realized OpenVPN access.

    A range holding a capability must report exactly its authorized target, and a
    range without one must report none; anything else is a permanent contract
    violation, refused once rather than retried.
    """
    from shared.remote_access import OpenVpnBindingError, bind_openvpn_realization, parse_openvpn_capability

    from ._operation_apply_raes import RaesRealizedAccessError

    capability = range_obj.remote_access_capability
    if capability is None and realization is None:
        return None
    if capability is None or realization is None:
        raise RaesRealizedAccessError("raes realized OpenVPN access does not match the range capability")
    try:
        authorized = parse_openvpn_capability(capability)
        binding = bind_openvpn_realization(realization, range_obj.user_id)
    except OpenVpnBindingError:
        raise RaesRealizedAccessError("raes realized OpenVPN access is invalid") from None
    if binding["target_ref"] != authorized.target_ref or binding["generation"] != str(row.request_id):
        raise RaesRealizedAccessError("raes realized OpenVPN access does not match the authorized generation")
    return binding
