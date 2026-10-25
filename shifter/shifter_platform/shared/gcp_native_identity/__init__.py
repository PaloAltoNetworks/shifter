"""Native GCP workload/database identity contract, without application imports."""

from .contract import (
    CLOUD_SQL_PROXY_IMAGE,
    NATIVE_APPLICATION_WORKLOADS,
    NATIVE_POLICY_WORKLOADS,
    GcpNativeIdentityReadback,
    cloud_sql_proxy_spec,
    validate_native_identity,
)

__all__ = [
    "CLOUD_SQL_PROXY_IMAGE",
    "NATIVE_APPLICATION_WORKLOADS",
    "NATIVE_POLICY_WORKLOADS",
    "GcpNativeIdentityReadback",
    "cloud_sql_proxy_spec",
    "validate_native_identity",
]
