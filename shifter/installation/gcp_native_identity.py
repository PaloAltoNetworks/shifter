"""Installation projections consume the shared native identity contract."""

from ipaddress import ip_address
from typing import Any

from shared.gcp_native_identity import (
    CLOUD_SQL_PROXY_IMAGE,
    GcpNativeIdentityReadback,
    validate_native_identity,
)

from .settings_gcp import GcpOpenFgaSettings

__all__ = ["CLOUD_SQL_PROXY_IMAGE", "GcpNativeIdentityReadback", "validate_native_identity"]


def project_native_helm(outputs: dict[str, Any], *, openfga_settings: object = None) -> dict[str, Any]:
    """One projection for bootstrap and Kustomize, using only public metadata."""
    accounts = outputs["workload_service_accounts"]["value"]
    native = validate_native_identity(
        outputs.get("native_identity", {}).get("value"),
        project_id=outputs["identity_platform_project_id"]["value"],
        service_accounts=accounts,
    )
    policy = GcpOpenFgaSettings.model_validate(openfga_settings or {})
    if native.openfga_enabled != policy.enabled:
        raise ValueError("native policy readback differs from the configured deployment intent")
    database = outputs["control_plane_database"]["value"]
    database_cidrs = []
    if native.enabled:
        address = ip_address(database["private_ip"])
        prefix_length = 32 if address.version == 4 else 128
        database_cidrs.append(f"{address}/{prefix_length}")
    result = {
        "cloudSqlProxy": {
            "enabled": native.enabled,
            "instanceConnectionName": native.instance_connection_name,
            "databaseUsers": native.database_users,
            "databaseCidrs": database_cidrs,
        },
        "openfga": {"enabled": policy.enabled},
    }
    if policy.enabled:
        result["openfga"].update(
            {
                "storeId": policy.store_id,
                "modelId": policy.model_id,
                "runtimeDatabaseUser": native.database_users["openfga-runtime"],
                "adminDatabaseUser": native.database_users["openfga-admin"],
                "migrationDatabaseUser": native.database_users["openfga-migrator"],
                "databaseCidrs": result["cloudSqlProxy"]["databaseCidrs"],
                "databasePort": 3307,
                "serviceAccountAnnotations": {
                    duty: {"iam.gke.io/gcp-service-account": accounts[f"openfga-{duty}"]}
                    for duty in ("runtime", "admin", "migrator")
                },
            }
        )
    return result
