"""GCP network inventory adapter for subnet allocation and alerting."""

from __future__ import annotations

import logging

from cloud.exceptions import CloudNetworkInventoryError
from cloud.gcp.base import get_project_id, import_google_module

logger = logging.getLogger(__name__)


def _network_matches(subnetwork_network: str, network_id: str) -> bool:
    if not subnetwork_network or not network_id:
        return False
    return subnetwork_network == network_id or subnetwork_network.endswith(f"/networks/{network_id}")


class GCPNetworkInventory:
    """Compute Engine subnet inventory implementation of NetworkInventory."""

    def list_subnet_cidrs(self, network_id: str) -> list[str]:
        logger.debug("list_subnet_cidrs: network_id=%s", network_id)
        project_id = get_project_id()
        if not project_id:
            raise CloudNetworkInventoryError("GCP project ID is required to list subnet CIDRs")

        try:
            compute_v1 = import_google_module("google.cloud.compute_v1")
            client = compute_v1.SubnetworksClient()
            cidrs: list[str] = []
            for _scope, scoped_list in client.aggregated_list(project=project_id):
                subnetworks = getattr(scoped_list, "subnetworks", None) or []
                for subnet in subnetworks:
                    subnetwork_network = getattr(subnet, "network", "")
                    if not _network_matches(subnetwork_network, network_id):
                        continue
                    cidr = getattr(subnet, "ip_cidr_range", "")
                    if cidr:
                        cidrs.append(cidr)
            return cidrs
        except ImportError as e:
            raise CloudNetworkInventoryError("GCP network inventory requires google-cloud-compute") from e
        except Exception as e:
            logger.error("list_subnet_cidrs: failed network_id=%s error=%s", network_id, e)
            raise CloudNetworkInventoryError(f"Failed to list GCP subnet CIDRs: {e}") from e

    def publish_subnet_exhaustion_alarm(
        self,
        network_id: str,
        cidr_prefix: str,
        subnet_size: int,
    ) -> None:
        logger.error(
            "CRITICAL: Subnet exhaustion in GCP network %s. "
            "No free /%d subnet available in prefix %s. "
            "This is user-impacting - investigate immediately.",
            network_id,
            subnet_size,
            cidr_prefix,
        )
