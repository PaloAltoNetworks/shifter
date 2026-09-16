"""Boot candidate images independently, under a fresh profile-specific challenge."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from typing import Any
from uuid import uuid5

from preparation.gce_build import ComputeAPI, _guest, _validate_request, _verify_guest_isolation
from preparation.gce_verify import _pinned_image


def verify_boot(api: ComputeAPI, request: dict[str, Any], probe: Callable[[str, str], bool]) -> dict[str, bool]:
    """A running VM is insufficient: the independently installed probe must pass."""
    operation_id, attempt_id = _validate_request(request)
    image = _pinned_image(api, request["image_ref"], request["image_id"], request["max_disk_gb"])
    name = f"prep-{attempt_id.hex}-boot"
    scope = f"projects/{request['project_id']}/zones/{request['zone']}"
    labels = {
        "shifter-preparation": operation_id.hex,
        "preparation-attempt": attempt_id.hex,
        "preparation-role": "verify",
    }
    # An explicit empty startup-script suppresses inherited project startup
    # material. The image must boot its installed service without repair code.
    guest = _guest(request, name, int(image["diskSizeGb"]), labels, "")
    api.create(f"{scope}/instances", guest, str(uuid5(attempt_id, "boot-probe")))
    instance_path = f"{scope}/instances/{name}"
    disk_path = f"{scope}/disks/{name}"
    instance = api.get(instance_path)
    _verify_guest_isolation(instance, request["subnetwork"], disk_path)
    if str(api.get(disk_path).get("sourceImageId")) != request["image_id"]:
        raise ValueError("boot probe does not use the pinned candidate")
    address = ipaddress.ip_address(instance["networkInterfaces"][0].get("networkIP", ""))
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_link_local:
        raise ValueError("boot probe endpoint is outside the private guest profile")
    if probe(str(address), str(attempt_id)) is not True:
        raise ValueError("candidate did not pass its independent boot probe")
    observed = api.get(instance_path)
    _verify_guest_isolation(observed, request["subnetwork"], disk_path)
    if observed.get("id") != instance.get("id") or observed.get("status") != "RUNNING":
        raise ValueError("boot probe guest changed during verification")
    if str(api.get(disk_path).get("sourceImageId")) != request["image_id"]:
        raise ValueError("boot probe source changed during verification")
    return {"boot_observed": True}
