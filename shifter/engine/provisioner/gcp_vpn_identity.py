"""Deterministic identities for GCE OpenVPN gateways.

ADR-008-R7: gateway identities are drawn from a pre-provisioned, single-project
service-account pool (``sh-vpn-pool-<slot>``). The slot is reserved per active
range by ``Range.allocate_vpn_gateway_slot`` and the provisioner holds
``serviceAccountUser`` on each pool member, so no runtime service-account
creation or self-``setIamPolicy`` is required.
"""

from __future__ import annotations


def gcp_vpn_gateway_pool_service_account_id(slot: int) -> str:
    """Return the account ID of pre-provisioned gateway SA pool member ``slot``."""
    return f"sh-vpn-pool-{slot}"


def gcp_vpn_gateway_pool_service_account_email(project_id: str, slot: int) -> str:
    """Return the email of pre-provisioned gateway SA pool member ``slot`` (ADR-008-R7)."""
    return f"{gcp_vpn_gateway_pool_service_account_id(slot)}@{project_id}.iam.gserviceaccount.com"


__all__ = [
    "gcp_vpn_gateway_pool_service_account_email",
    "gcp_vpn_gateway_pool_service_account_id",
]
