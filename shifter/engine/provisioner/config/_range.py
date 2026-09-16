"""Range/instance dataclasses, provider-neutral range-network contract, and DB loading.

Depends on the ``_env`` leaf, the ``_gcp_backend`` leaf, ``_gdc`` (for the GDC
network-access loader used by ``load_range_network_config``), and ``_ngfw``
(for NGFW attachment resolution used by ``get_range_from_db``).
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from shared.enums import ResourceStatus

from log_redact import safe_log_fingerprint

from ._env import _parse_csv_env
from ._gcp_backend import _is_active_gdc_range_plane, is_gce_range_cell_backend
from ._gdc import load_gdc_network_access_config
from ._ngfw import resolve_ngfw_attachment_config

logger = logging.getLogger(__name__)


@dataclass
class InstanceConfig:
    """Configuration for an instance to be provisioned.

    Attributes:
        uuid: Unique identifier from the spec (for tagging and DB correlation).
        name: Display name for UI (e.g., "target-ubuntu", "attacker-kali").
        role: Instance role ("attacker", "victim", or "dc").
        os_type: Operating system type ("kali", "ubuntu", "windows").
        instance_type: AWS instance type (e.g., "t3.medium").
        agent_s3_key: S3 key for agent installer (optional).
        agent_presigned_url: Presigned URL for agent download (optional).
        dc_config: Domain controller configuration (optional).
        join_domain: Whether this instance should join a domain.
        dc_config_param_name: SSM parameter path for DC config (optional).
    """

    # Required: correlation key for tagging and DB updates
    uuid: str
    # Display name like "target-ubuntu" or "attacker-kali"
    name: str
    # "attacker", "victim", or "dc"
    role: str
    # "kali", "ubuntu", "windows"
    os_type: str
    instance_type: str
    # S3 key for agent installer
    agent_s3_key: str | None = None
    # Presigned URL for agent download
    agent_presigned_url: str | None = None
    # {"domain_name": "...", "netbios_name": "..."}
    dc_config: dict[str, str] | None = None
    # Whether this instance should join a domain
    join_domain: bool = False
    # SSM parameter path for DC config
    dc_config_param_name: str | None = None


@dataclass
class SubnetConfig:
    """Configuration for a logical subnet and its instances.

    A logical subnet groups instances that share network visibility.
    Each SubnetConfig becomes one AWS /28 subnet during provisioning.

    Attributes:
        name: Subnet name (e.g., 'attack', 'dc_network').
        uuid: Unique identifier for tagging and correlation.
        instances: List of instances in this subnet.
        connected_to: List of subnet names this subnet needs to reach.
    """

    name: str
    uuid: str
    instances: list[InstanceConfig]
    connected_to: list[str] = field(default_factory=list)


@dataclass
class RangeConfig:
    """Configuration for a complete range.

    Attributes:
        range_id: Database ID for the range.
        user_id: Owner's user ID.
        request_uuid: Correlation key for the provisioning request.
        environment: Deployment environment (dev, staging, prod).
        subnets: List of logical subnets with their instances.
        vpc_id: AWS VPC ID for range deployment.
        vpc_cidr: VPC CIDR block (e.g., '10.1.0.0/16').
        ngfw_data_eni_id: Legacy AWS data ENI ID for inter-subnet routing.
            Empty string if no AWS NGFW attachment is present.
    """

    range_id: int
    user_id: int
    request_uuid: str
    environment: str
    subnets: list[SubnetConfig]
    vpc_id: str
    vpc_cidr: str
    route_table_id: str
    instance_profile_name: str
    kali_ami_id: str
    victim_ami_id: str
    windows_ami_id: str
    agent_s3_bucket: str
    availability_zone: str
    # Legacy AWS data ENI ID for inter-subnet routing
    ngfw_data_eni_id: str = ""
    # Provider-neutral NGFW attachment mode
    ngfw_attachment_mode: str = ""
    # Provider-neutral next hop used for subnet routes
    ngfw_route_next_hop_ip: str = ""
    # AMI ID for DC instances (prebaked with AD DS)
    dc_ami_id: str = ""
    portal_vpc_cidr: str = ""
    # VPC peering connection ID for portal route
    portal_vpc_peering_id: str = ""
    # NGFW (VM-Series) configuration
    ngfw_enabled: bool = False
    ngfw_ami_id: str = ""
    ngfw_instance_type: str = "m5.xlarge"
    # NGFW connection info for subnet configuration (set when ngfw_enabled=True)
    # NGFW management IP for SSH
    ngfw_management_ip: str = ""
    # Secrets Manager ARN for SSH private key
    ngfw_ssh_key_secret_arn: str = ""
    # NGFW subnet CIDR for computing gateway IP
    ngfw_subnet_cidr: str = ""
    # S3 VPC endpoint for agent downloads (Gateway endpoint ID)
    s3_endpoint_id: str = ""
    # AWS Network Firewall endpoint ID for internet egress from range subnets
    firewall_endpoint_id: str = ""
    # SSM/Bedrock endpoints subnet CIDR for NGFW routing
    ssm_endpoints_subnet_cidr: str = ""


@dataclass(frozen=True)
class RangeNetworkConfig:
    """Provider-neutral network contract for range provisioning.

    This keeps the provisioner's subnet allocation and future Terraform inputs
    behind generic env names while preserving the legacy AWS VPC env vars as
    fallbacks.
    """

    network_id: str
    network_cidr: str
    network_region: str
    portal_network_cidrs: tuple[str, ...] = ()

    @property
    def primary_portal_cidr(self) -> str:
        """Return the first portal CIDR for legacy single-CIDR call sites."""
        return self.portal_network_cidrs[0] if self.portal_network_cidrs else ""


def _load_portal_network_cidrs() -> tuple[str, ...]:
    """Load portal CIDRs with the legacy single-CIDR fallback."""
    portal_network_cidrs = _parse_csv_env(os.environ.get("PORTAL_NETWORK_CIDRS", ""))
    legacy_portal_cidr = os.environ.get("PORTAL_VPC_CIDR", "")
    if not portal_network_cidrs and legacy_portal_cidr:
        return (legacy_portal_cidr,)
    return portal_network_cidrs


def _resolve_range_project_id() -> str:
    """Resolve the active cloud project id used by range networking."""
    return (
        os.environ.get("GCP_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("CLOUD_PROJECT_ID")
        or ""
    ).strip()


def _resolve_range_network_region() -> str:
    """Resolve the range network region from current provider env."""
    return (
        os.environ.get("RANGE_NETWORK_REGION")
        or os.environ.get("GCP_REGION")
        or os.environ.get("CLOUD_REGION")
        or os.environ.get("AWS_REGION", "")
    )


def _default_range_network_id(project_id: str) -> str:
    """Return the provider-specific default range network id."""
    if is_gce_range_cell_backend():
        return f"gcp-range-cells:{project_id}"
    return ""


def load_range_network_config() -> RangeNetworkConfig:
    """Load the active provider's range-network contract from environment variables."""
    portal_network_cidrs = _load_portal_network_cidrs()
    gdc_access = load_gdc_network_access_config() if _is_active_gdc_range_plane() else None
    if gdc_access is not None:
        return RangeNetworkConfig(
            network_id=gdc_access.cluster_id,
            network_cidr=gdc_access.vxlan_cidr,
            network_region=gdc_access.region,
            portal_network_cidrs=portal_network_cidrs,
        )

    project_id = _resolve_range_project_id()
    return RangeNetworkConfig(
        network_id=os.environ.get("RANGE_NETWORK_ID")
        or os.environ.get("RANGE_VPC_ID", "")
        or _default_range_network_id(project_id),
        network_cidr=os.environ.get("RANGE_NETWORK_CIDR") or os.environ.get("RANGE_VPC_CIDR", ""),
        network_region=_resolve_range_network_region(),
        portal_network_cidrs=portal_network_cidrs,
    )


def get_range_availability_zone(default: str = "us-east-2b") -> str:
    """Return the configured range placement zone for AWS-style callers."""
    return (
        os.environ.get("RANGE_NETWORK_ZONE")
        or os.environ.get("RANGE_AVAILABILITY_ZONE")
        or os.environ.get("AVAILABILITY_ZONE")
        or default
    )


def get_range_from_db(range_id: int) -> dict[str, Any]:
    """Load range configuration from database.

    Returns range data with the new schema where range_config contains
    the full RangeSpec (scenario_id, user_id, subnets with instances).
    Also resolves provider-neutral NGFW attachment details from the user's
    active NGFW if the scenario has ngfw: true.

    Args:
        range_id: Database ID of the range.

    Returns:
        Dict with keys: id, user_id, request_uuid, range_config, ngfw_enabled,
        ngfw_data_eni_id, ngfw_instance_id, and ngfw_attachment.

    Raises:
        ValueError: If range not found.
    """
    logger.debug("Loading range %d from database", range_id)

    from provisioner_db import get_db_connection

    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT
                    r.id,
                    r.user_id,
                    r.uuid,
                    r.range_config
                FROM mission_control_range r
                WHERE r.id = %s
                """,
            (range_id,),
        )
        row = cur.fetchone()
        if not row:
            logger.error("Range %d not found in database", range_id)
            raise ValueError(f"Range {range_id} not found")

        user_id = row[1]
        from shared.persisted_envelope import unwrap_persisted_spec

        range_config = unwrap_persisted_spec(row[3] or {})

        # Check if scenario requires NGFW (ngfw: true in range_config)
        ngfw_enabled = range_config.get("ngfw", False)

        # Look up provider-neutral NGFW attachment data from the user's NGFW.
        ngfw_data_eni_id = ""
        ngfw_instance_id = None
        ngfw_attachment: dict[str, Any] = {}
        if ngfw_enabled:
            cur.execute(
                """
                SELECT ei.state, ei.id
                FROM engine_instance ei
                JOIN engine_request er ON ei.request_id = er.id
                WHERE er.user_id = %s
                  AND ei.role = 'ngfw'
                  AND ei.status IN (%s, %s, %s, %s)
                ORDER BY ei.created_at DESC
                LIMIT 1
                """,
                (
                    user_id,
                    ResourceStatus.READY.value,
                    ResourceStatus.PAUSED.value,
                    ResourceStatus.PAUSING.value,
                    ResourceStatus.RESUMING.value,
                ),
            )
            ngfw_row = cur.fetchone()
            if ngfw_row:
                resolved_attachment = resolve_ngfw_attachment_config(ngfw_row[0] or {})
                if resolved_attachment.is_attachable:
                    ngfw_data_eni_id = resolved_attachment.data_attachment_id
                    ngfw_instance_id = ngfw_row[1]
                    ngfw_attachment = {
                        "cloud_provider": resolved_attachment.cloud_provider,
                        "management_ip": resolved_attachment.management_ip,
                        "ssh_key_secret_ref": resolved_attachment.ssh_key_secret_ref,
                        "dataplane_ip": resolved_attachment.dataplane_ip,
                        "route_next_hop_ip": resolved_attachment.route_next_hop_ip,
                        "data_attachment_id": resolved_attachment.data_attachment_id,
                        "attachment_mode": resolved_attachment.attachment_mode,
                        "provider_metadata": resolved_attachment.provider_metadata,
                    }
                    logger.debug(
                        "Found NGFW attachment mode=%s instance_id=%s for user %d",
                        resolved_attachment.attachment_mode,
                        ngfw_instance_id,
                        user_id,
                    )

        result = {
            "id": row[0],
            "user_id": user_id,
            "request_uuid": str(row[2]) if row[2] else "",
            "range_config": range_config,
            "ngfw_enabled": ngfw_enabled,
            "ngfw_data_eni_id": ngfw_data_eni_id,
            "ngfw_instance_id": ngfw_instance_id,
            "ngfw_attachment": ngfw_attachment,
        }

        logger.debug(
            "Loaded range range_fp=%s: ngfw_enabled=%s, ngfw_attachment=%s",
            safe_log_fingerprint(range_id),
            result["ngfw_enabled"],
            "present" if result["ngfw_attachment"] else "none",
        )

        return result
