"""Naming, URI, label, and tag helpers for GCE range-cell resource planning.

Extracted from ``gcp_range_cell_plan.py`` to keep that module under the
file-length limit. These are pure functions with no provisioner state: they
normalize scenario values into Compute Engine resource names/labels and build
relative self-links and network tags.
"""

from __future__ import annotations

import re


def _sanitize_name(value: str, *, max_length: int = 63) -> str:
    """Normalize a value into a Compute Engine resource name."""
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    normalized = normalized[:max_length].rstrip("-")
    if not normalized:
        normalized = "range"
    if not normalized[0].isalpha():
        normalized = f"r-{normalized}"
    return normalized[:max_length].rstrip("-")


def _label_value(value: object, *, max_length: int = 63) -> str:
    """Normalize a value into a Compute Engine label value."""
    normalized = re.sub(r"[^a-z0-9_-]+", "-", str(value).strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-_")
    return normalized[:max_length].rstrip("-_") or "unknown"


def _short_resource_name(prefix: str, *parts: object, max_length: int = 63) -> str:
    """Build a bounded resource name from stable name parts."""
    return _sanitize_name(
        "-".join([prefix, *(str(part) for part in parts if part not in (None, ""))]), max_length=max_length
    )


def range_router_nat_plan(range_id: int, subnet_self_links: list[str]) -> dict[str, object]:
    """Build the range-owned Cloud Router + NAT plan element (PLAT-238, ADR-026-R6).

    Deterministic per range so an idempotent replay reconciles the same router/NAT.
    Scoped to exactly the supplied subnet self-links; the caller omits this element
    entirely for a ``none`` (zero-egress) range so it carries no NAT path.
    """
    return {
        "router_name": _short_resource_name("shifter-r", range_id, "nat-router"),
        "nat_name": _short_resource_name("shifter-r", range_id, "nat"),
        "subnetwork_self_links": list(subnet_self_links),
    }


def _network_self_link(project_id: str, network_name: str) -> str:
    """Return the relative self-link for a global Compute network."""
    return f"projects/{project_id}/global/networks/{network_name}"


def _network_name_from_id(network_id: str) -> str:
    """Extract the network name from a self-link or partial URL.

    Accepts a full self-link, a partial URL ``projects/<p>/global/networks/<name>``,
    or a bare name; returns the trailing network name.
    """
    return network_id.rstrip("/").rsplit("/", 1)[-1]


def _subnetwork_self_link(project_id: str, region: str, subnet_name: str) -> str:
    """Return the relative self-link for a regional Compute subnet."""
    return f"projects/{project_id}/regions/{region}/subnetworks/{subnet_name}"


def _machine_type_self_link(zone: str, machine_type: str) -> str:
    """Return the relative self-link for a zonal machine type."""
    return f"zones/{zone}/machineTypes/{machine_type}"


def _disk_type_self_link(zone: str, disk_type: str) -> str:
    """Return the relative self-link for a zonal disk type."""
    return f"zones/{zone}/diskTypes/{disk_type}"


def _network_tag(range_id: int) -> str:
    """Return the common network tag for a range cell."""
    return _short_resource_name("shifter-range", range_id)


def _subnet_tag(range_id: int, subnet_name: str) -> str:
    """Return the subnet-scoped network tag for range instances."""
    return _short_resource_name("shifter-range", range_id, subnet_name)
