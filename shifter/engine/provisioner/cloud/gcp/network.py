"""GCP network inventory adapter for GDC scenario subnet allocation and alerting."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Protocol, cast

from cloud.exceptions import CloudNetworkInventoryError
from cloud.gcp.base import get_project_id, get_region, import_google_module
from config import is_gce_range_cell_backend, load_gdc_network_access_config

logger = logging.getLogger(__name__)
_SUBNET_CIDR_ANNOTATION = "shifter.dev/subnet-cidr"
_MANAGED_BY_LABEL = "shifter-provisioner"
InventoryItem = dict[str, object]


def _project_from_network_id(network_id: str) -> str:
    """Extract the project from a ``projects/<project>/global/networks/<name>`` self-link.

    Range subnetworks live in the range VPC's project, which the network self-link
    carries directly. Prefer it over the control-plane ``get_project_id()`` so the
    inventory read targets the real range project even when the control-plane
    ``GCP_PROJECT_ID`` is a deploy-overlay placeholder.
    """
    parts = str(network_id or "").split("/")
    if "projects" in parts:
        index = parts.index("projects")
        if index + 1 < len(parts) and parts[index + 1]:
            return parts[index + 1]
    return ""


class _SubnetworksClient(Protocol):
    """Subset of the Compute subnetworks client used by inventory."""

    def list(self, *, project: str, region: str) -> Iterable[object]:
        """Return Compute subnetworks for a project and region."""


class GCPNetworkInventory:
    """GCP network inventory implementation of NetworkInventory."""

    def __init__(self, *, gce_subnetworks_client_factory: Callable[[], _SubnetworksClient] | None = None) -> None:
        self._gce_subnetworks_client_factory = gce_subnetworks_client_factory

    def list_subnet_cidrs(self, network_id: str) -> list[str]:
        """List provisioned subnet CIDRs for the active GCP range backend."""
        logger.debug("list_subnet_cidrs: network_id=%s", network_id)
        if is_gce_range_cell_backend():
            return self._list_gce_range_subnet_cidrs(network_id)
        gdc_access = load_gdc_network_access_config()
        if gdc_access is None:
            raise CloudNetworkInventoryError(
                "GCP range provisioning requires GDC access configuration; GDC_ACCESS_SECRET_ID is missing"
            )
        return self._list_gdc_network_cidrs(network_id, gdc_access.kubeconfig)

    def _list_gce_range_subnet_cidrs(self, network_id: str) -> list[str]:
        """List managed Compute Engine subnet CIDRs for GCE range cells."""
        # Range subnetworks live in the range VPC's project (from the network
        # self-link), not necessarily the control-plane project.
        project_id = _project_from_network_id(network_id) or get_project_id()
        region = get_region()
        if not project_id or not region:
            raise CloudNetworkInventoryError("GCE network inventory requires GCP project and region")
        try:
            client = self._build_gce_subnetworks_client()
            response = client.list(project=project_id, region=region)
        except ImportError as e:
            raise CloudNetworkInventoryError("GCE network inventory requires google-cloud-compute") from e
        except Exception as e:
            logger.exception("list_subnet_cidrs: failed to list GCE subnetworks for %s: %s", network_id, e)
            raise CloudNetworkInventoryError(f"Failed to read GCE subnetwork inventory: {e}") from e

        cidrs: list[str] = []
        for item in response:
            if not self._is_managed_gce_subnetwork(item):
                continue
            if not self._matches_requested_network(item, network_id):
                continue
            cidr = self._get_field(item, "ip_cidr_range", "ipCidrRange")
            if cidr:
                cidrs.append(str(cidr))
        return cidrs

    def _build_gce_subnetworks_client(self) -> _SubnetworksClient:
        """Build or reuse the Compute subnetworks client."""
        if self._gce_subnetworks_client_factory:
            return self._gce_subnetworks_client_factory()
        compute = import_google_module("google.cloud.compute_v1")
        return compute.SubnetworksClient()

    def _list_gdc_network_cidrs(self, network_id: str, kubeconfig_yaml: str) -> list[str]:
        """List managed GDC Network CIDRs from the runtime cluster."""
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
            logger.exception("list_subnet_cidrs: failed to list GDC Network objects for %s: %s", network_id, e)
            raise CloudNetworkInventoryError(f"Failed to list GDC scenario networks: {e}") from e
        except Exception as e:
            logger.exception("list_subnet_cidrs: failed to build GDC client for %s: %s", network_id, e)
            raise CloudNetworkInventoryError(f"Failed to read GDC network inventory: {e}") from e

        cidrs: list[str] = []
        for item in response.get("items", []):
            if not self._is_managed_gdc_network(item):
                continue
            cidrs.extend(self._managed_network_cidrs(item))
        return cidrs

    @staticmethod
    def _is_managed_gdc_network(item: InventoryItem) -> bool:
        """Return whether a Kubernetes Network belongs to the range plane."""
        metadata = item.get("metadata", {})
        labels = cast(InventoryItem, metadata).get("labels", {}) if isinstance(metadata, dict) else {}
        if not isinstance(labels, dict):
            return False
        if labels.get("app.kubernetes.io/managed-by") == "shifter-provisioner":
            return True
        return labels.get("shifter.dev/range-plane") == "gdc-vmruntime"

    @staticmethod
    def _get_field(item: object, *names: str) -> object:
        """Read a field from a dict or SDK object."""
        for name in names:
            value = item.get(name) if isinstance(item, dict) else getattr(item, name, None)
            if value not in (None, ""):
                return value
        return ""

    @classmethod
    def _is_managed_gce_subnetwork(cls, item: object) -> bool:
        """Return whether a Compute subnetwork belongs to the range plane."""
        labels = cls._get_field(item, "labels") or {}
        if not isinstance(labels, dict):
            return False
        return labels.get("managed-by") == _MANAGED_BY_LABEL

    @classmethod
    def _matches_requested_network(cls, item: object, network_id: str) -> bool:
        """Return whether a Compute subnetwork belongs to the requested range network."""
        if not network_id or network_id.startswith("gcp-range-cells:"):
            return True
        network = str(cls._get_field(item, "network"))
        return network.endswith(f"/{network_id}") or network == network_id

    @staticmethod
    def _managed_network_cidrs(item: InventoryItem) -> list[str]:
        """Return CIDRs from the current annotation or legacy route fields."""
        metadata = item.get("metadata", {})
        metadata_dict = cast(InventoryItem, metadata) if isinstance(metadata, dict) else {}
        annotations = metadata_dict.get("annotations", {}) or {}
        if not isinstance(annotations, dict):
            annotations = {}
        annotated_cidr = str(annotations.get(_SUBNET_CIDR_ANNOTATION, "")).strip()
        if annotated_cidr:
            return [annotated_cidr]

        legacy_cidrs: list[str] = []
        spec = item.get("spec", {})
        spec_dict = cast(InventoryItem, spec) if isinstance(spec, dict) else {}
        routes = spec_dict.get("routes", [])
        routes_list = routes if isinstance(routes, list) else []
        for route in routes_list:
            if not isinstance(route, dict):
                continue
            cidr = str(route.get("to", "")).strip()
            if cidr:
                legacy_cidrs.append(cidr)
        return legacy_cidrs

    def publish_subnet_exhaustion_alarm(
        self,
        network_id: str,
        cidr_prefix: str,
        subnet_size: int,
    ) -> None:
        """Emit the subnet exhaustion signal for GCP range networks."""
        logger.error(
            "CRITICAL: Subnet exhaustion in GCP network %s. "
            "No free /%d subnet available in prefix %s. "
            "This is user-impacting - investigate immediately.",
            network_id,
            subnet_size,
            cidr_prefix,
        )
