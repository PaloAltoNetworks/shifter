"""Subnet and SubnetAllocation models."""

from django.db import models

from shared.schemas.persistence import unwrap_persisted_spec

from ._range import Range
from ._request import Instantiation


class Subnet(Instantiation):
    """Logical subnet for CyberScript DSL routing.

    Represents a logical network segment from the CyberScript DSL.
    NOT an AWS subnet - this is realized as NGFW routes when a range
    with NGFW is provisioned.

    Tracks lifecycle for:
    - Creating NGFW address objects and routes on provision
    - Removing NGFW routes on destroy
    - Cleanup on failures

    Attributes:
        name: Logical subnet name from DSL (e.g., 'dc_network', 'server_network').
        connected_to: List of subnet names this subnet can reach (for NGFW routes).
        range: The Range this subnet belongs to.
    """

    name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Logical subnet name from CyberScript DSL",
    )
    connected_to = models.JSONField(
        default=list,
        help_text="List of subnet names this subnet connects to (for NGFW routes)",
    )
    range = models.ForeignKey(
        Range,
        on_delete=models.CASCADE,
        related_name="logical_subnets",
        null=True,
        blank=True,
        help_text="Range this logical subnet belongs to",
    )

    class Meta:
        """Default ordering and display names for the Subnet model."""

        ordering = ["-created_at"]
        verbose_name = "Logical Subnet"
        verbose_name_plural = "Logical Subnets"

    def __str__(self) -> str:
        """Return a human-readable label with the subnet's name and uuid."""
        return f"Subnet {self.name} ({self.uuid})"

    @property
    def instance_uuids(self) -> list[str]:
        """Return list of instance UUIDs in this subnet.

        Extracts from spec if available, otherwise empty list.
        """
        if not self.spec:
            return []
        spec_payload = unwrap_persisted_spec(self.spec)
        instances = spec_payload.get("instances", [])
        return [inst.get("uuid") for inst in instances if inst.get("uuid")]


class SubnetAllocation(models.Model):
    """Tracks allocated subnets to prevent CIDR collisions during concurrent provisioning.

    Row exists = subnet is occupied. No row = subnet is free.
    Rows are INSERTed on allocation and DELETEd on destroy.

    The allocator also reconciles with AWS: if a subnet exists in AWS
    but not in this table, it's inserted (drift repair).
    """

    vpc_id = models.CharField(
        max_length=255,
        help_text="AWS vpc-id, GDC network name, or GCE network self-link (projects/<p>/global/networks/<n>)",
    )
    cidr = models.CharField(max_length=20, help_text="e.g. 10.1.2.16/28")
    subnet_size = models.IntegerField(help_text="Prefix length: 24 or 28")
    range_id = models.IntegerField(default=0)
    request_id = models.CharField(max_length=64, default="")
    # Canonical fingerprint of everything the reservation realizes -- network,
    # prefix length, and the ordered authored subnet identities (#1838). A retry
    # is only the same request if this matches; comparing counts alone would let a
    # reordered or re-based request receive the first batch's CIDRs positionally.
    # Blank on drift-observed rows, which no request owns.
    reservation_shape = models.CharField(max_length=71, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table name and the unique CIDR-per-VPC constraint for allocations."""

        db_table = "engine_subnetallocation"
        constraints = [
            models.UniqueConstraint(
                fields=["vpc_id", "cidr"],
                name="unique_cidr_per_vpc",
            ),
        ]

    def __str__(self) -> str:
        """Return a human-readable label with the allocated CIDR and VPC id."""
        return f"{self.cidr} in {self.vpc_id}"
