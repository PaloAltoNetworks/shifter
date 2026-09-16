"""Read VM existence from GCE rather than inferring it from the authored type."""

from __future__ import annotations

import re
from typing import Protocol, cast

from gcp_range_cell_clients import GCEClients
from gcp_range_cell_types import InstancePlan, RangeCellPlan


class _AttachedDisk(Protocol):
    """Represent AttachedDisk."""

    boot: bool
    source: str


class _GuestInstance(Protocol):
    """Represent GuestInstance."""

    name: str
    id: object
    machine_type: str
    disks: list[_AttachedDisk]


class _Image(Protocol):
    """Represent Image."""

    id: object
    status: str


class _Disk(Protocol):
    """Represent Disk."""

    source_image_id: object


def verify_prepared_source(plan: RangeCellPlan, instance: InstancePlan, clients: GCEClients) -> None:
    """Reject a recreated image name before installing any range credentials."""
    profile = instance["profile"]
    if not profile.source_image_id:
        return
    prefix = f"projects/{plan['project_id']}/global/images/"
    name = profile.source_image.removeprefix(prefix)
    if not profile.source_image.startswith(prefix) or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", name):
        raise ValueError("prepared source is outside the range project")
    if clients.images is None:
        raise ValueError("prepared source observation is unavailable")
    image = cast(_Image, clients.images.get(project=plan["project_id"], image=name))
    if str(image.id) != profile.source_image_id or image.status != "READY":
        raise ValueError("prepared source identity is unavailable")


def observe_gce_substrates(plan: RangeCellPlan, clients: GCEClients) -> list[dict[str, str]]:
    """Read each created instance through the authenticated provider client."""
    observations = []
    for instance in plan["instances"]:
        actual = cast(
            _GuestInstance,
            clients.instances.get(project=plan["project_id"], zone=plan["zone"], instance=instance["resource_name"]),
        )
        if actual is None or actual.name != instance["resource_name"] or not actual.id or not actual.machine_type:
            raise ValueError("compute-substrate observation is unavailable or invalid")
        expected_image_id = getattr(instance.get("profile"), "source_image_id", "")
        if expected_image_id:
            _verify_boot_image(plan, actual, clients, expected_image_id)
        observations.append({"instance_key": instance["uuid"], "value": "virtual-machine"})
    return observations


def _verify_boot_image(plan: RangeCellPlan, guest: _GuestInstance, clients: GCEClients, expected: str) -> None:
    """An image name can be recreated; its actual boot disk must retain the admitted ID."""
    boot = [disk for disk in guest.disks if disk.boot]
    if len(boot) != 1:
        raise ValueError("prepared image boot disk is ambiguous")
    source = (
        boot[0]
        .source.removeprefix("https://www.googleapis.com/compute/v1/")
        .removeprefix("https://compute.googleapis.com/compute/v1/")
    )
    prefix = f"projects/{plan['project_id']}/zones/{plan['zone']}/disks/"
    name = source.removeprefix(prefix)
    if not source.startswith(prefix) or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", name):
        raise ValueError("prepared image boot disk is outside the range scope")
    if clients.disks is None:
        raise ValueError("prepared image boot disk observation is unavailable")
    disk = cast(_Disk, clients.disks.get(project=plan["project_id"], zone=plan["zone"], disk=name))
    if str(disk.source_image_id) != expected:
        raise ValueError("prepared image provider identity changed")
