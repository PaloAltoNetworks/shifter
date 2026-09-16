"""Deterministic identities for preconfigured GCE range hosts.

Range-host identities come from a bounded, pre-provisioned service-account
pool. The range's existing subnet allocation index selects a stable member, so
the provisioner needs no runtime IAM mutation or project-wide act-as grant.
"""

from __future__ import annotations


def gcp_range_host_pool_service_account_id(slot: int) -> str:
    """Return the account ID of pre-provisioned range-host pool member ``slot``."""
    return f"sh-range-host-{slot}"


def gcp_range_host_pool_service_account_email(project_id: str, slot: int) -> str:
    """Return the email of pre-provisioned range-host pool member ``slot``."""
    return f"{gcp_range_host_pool_service_account_id(slot)}@{project_id}.iam.gserviceaccount.com"


__all__ = [
    "gcp_range_host_pool_service_account_email",
    "gcp_range_host_pool_service_account_id",
]
