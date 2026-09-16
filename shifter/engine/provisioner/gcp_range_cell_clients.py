"""Compute Engine client bindings for GCE range cells."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cloud.gcp.base import import_google_module

_COMPUTE_MODULE = "google.cloud.compute_v1"
_GOOGLE_EXCEPTIONS_MODULE = "google.api_core.exceptions"


class ComputeCollectionClient(Protocol):
    """Subset of Compute collection clients used by this backend."""

    def get(self, **kwargs: object) -> object:
        """Return one resource or raise provider NotFound."""

    def insert(self, **kwargs: object) -> object:
        """Insert one resource and return a Compute operation."""

    def delete(self, **kwargs: object) -> object:
        """Delete one resource and return a Compute operation."""


class FirewallsCollectionClient(ComputeCollectionClient, Protocol):
    """Firewall operations additionally used to reconcile existing rules (#1711)."""

    def patch(self, **kwargs: object) -> object:
        """Converge one existing firewall rule to a new body and return an operation."""


class ComputeInstancesClient(ComputeCollectionClient, Protocol):
    """Compute instance operations additionally used by range lifecycle."""

    def set_disk_auto_delete(self, **kwargs: object) -> object:
        """Set one attached disk's instance-deletion behavior."""

    def stop(self, **kwargs: object) -> object:
        """Stop one running instance and return a Compute operation (range pause)."""

    def start(self, **kwargs: object) -> object:
        """Start one stopped instance and return a Compute operation (range resume)."""


class OperationWaitClient(Protocol):
    """Subset of Compute operation clients used by this backend."""

    def wait(self, **kwargs: object) -> object:
        """Wait for a Compute operation and return its terminal response."""


class GoogleExceptions(Protocol):
    """Google exception module subset used by this backend."""

    NotFound: type[Exception]


@dataclass(frozen=True)
class GCEClients:
    """Compute Engine clients used by the range-cell backend."""

    networks: ComputeCollectionClient
    subnetworks: ComputeCollectionClient
    firewalls: FirewallsCollectionClient
    addresses: ComputeCollectionClient
    routers: ComputeCollectionClient
    instances: ComputeInstancesClient
    global_operations: OperationWaitClient
    region_operations: OperationWaitClient
    zone_operations: OperationWaitClient
    google_exceptions: GoogleExceptions
    disks: ComputeCollectionClient | None = None
    images: ComputeCollectionClient | None = None


def _build_clients() -> GCEClients:
    """Build production Compute Engine clients lazily."""
    compute = import_google_module(_COMPUTE_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    return GCEClients(
        networks=compute.NetworksClient(),
        subnetworks=compute.SubnetworksClient(),
        firewalls=compute.FirewallsClient(),
        addresses=compute.AddressesClient(),
        routers=compute.RoutersClient(),
        instances=compute.InstancesClient(),
        global_operations=compute.GlobalOperationsClient(),
        region_operations=compute.RegionOperationsClient(),
        zone_operations=compute.ZoneOperationsClient(),
        google_exceptions=google_exceptions,
        disks=compute.DisksClient(),
        images=compute.ImagesClient(),
    )
