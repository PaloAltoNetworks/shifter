"""GCP network inventory adapter for GDC scenario subnet allocation and alerting."""

from __future__ import annotations

import logging
from typing import Any

from cloud.exceptions import CloudNetworkInventoryError
from config import load_gdc_network_access_config

logger = logging.getLogger(__name__)


class GCPNetworkInventory:
    """GDC network inventory implementation of NetworkInventory."""

    def list_subnet_cidrs(self, network_id: str) -> list[str]:
        logger.debug("list_subnet_cidrs: network_id=%s", network_id)
        gdc_access = load_gdc_network_access_config()
        if gdc_access is None:
            raise CloudNetworkInventoryError(
                "GCP range provisioning requires GDC access configuration; GDC_ACCESS_SECRET_ID is missing"
            )
        return self._list_gdc_network_cidrs(network_id, gdc_access.kubeconfig)

    def _list_gdc_network_cidrs(self, network_id: str, kubeconfig_yaml: str) -> list[str]:
        try:
            import yaml
            from kubernetes import client, config
            from kubernetes.client.exceptions import ApiException
        except ImportError as e:
            raise CloudNetworkInventoryError("GDC network inventory requires kubernetes and PyYAML") from e

        try:
            kubeconfig_dict = yaml.safe_load(kubeconfig_yaml)
            loader = config.kube_config.KubeConfigLoader(config_dict=kubeconfig_dict)
            configuration = client.Configuration()
            loader.load_and_set(configuration)
            api_client = client.ApiClient(configuration=configuration)
            custom_api = client.CustomObjectsApi(api_client)
            response = custom_api.list_cluster_custom_object(
                group="networking.gke.io",
                version="v1",
                plural="networks",
            )
        except ApiException as e:
            logger.error("list_subnet_cidrs: failed to list GDC Network objects for %s: %s", network_id, e)
            raise CloudNetworkInventoryError(f"Failed to list GDC scenario networks: {e}") from e
        except Exception as e:
            logger.error("list_subnet_cidrs: failed to build GDC client for %s: %s", network_id, e)
            raise CloudNetworkInventoryError(f"Failed to read GDC network inventory: {e}") from e

        cidrs: list[str] = []
        for item in response.get("items", []):
            if not self._is_managed_gdc_network(item):
                continue
            for route in item.get("spec", {}).get("routes", []):
                cidr = str(route.get("to", "")).strip()
                if cidr:
                    cidrs.append(cidr)
        return cidrs

    @staticmethod
    def _is_managed_gdc_network(item: dict[str, Any]) -> bool:
        labels = item.get("metadata", {}).get("labels", {}) or {}
        if labels.get("app.kubernetes.io/managed-by") == "shifter-provisioner":
            return True
        return labels.get("shifter.dev/range-plane") == "gdc-vmruntime"

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
