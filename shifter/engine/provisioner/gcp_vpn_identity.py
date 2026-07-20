"""Deterministic identities for generation-isolated GCE OpenVPN gateways."""

from __future__ import annotations

import hashlib


def gcp_vpn_gateway_service_account_id(range_id: int, generation: object) -> str:
    """Return a valid, opaque GCP account ID unique to one range generation."""
    digest = hashlib.sha256(f"{range_id}:{generation}".encode()).hexdigest()[:20]
    return f"sh-vpn-{digest}"


def gcp_vpn_gateway_service_account_email(project_id: str, range_id: int, generation: object) -> str:
    """Return the generation-owned gateway principal email."""
    return f"{gcp_vpn_gateway_service_account_id(range_id, generation)}@{project_id}.iam.gserviceaccount.com"


__all__ = ["gcp_vpn_gateway_service_account_email", "gcp_vpn_gateway_service_account_id"]
