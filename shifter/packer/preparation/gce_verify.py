"""Independent GCE raw-disk inspection, separate from builder execution."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from preparation.gce_build import ComputeAPI, _guest, _same_ref, _validate_request
from preparation.guest_runtime import STARTUP


def scan_image(
    api: ComputeAPI,
    request: dict[str, Any],
    context: dict[str, bytes],
    *,
    verify_output: bool,
) -> dict[str, Any]:
    """Read candidate bytes using a distinct, pinned, credentialless scanner VM."""
    raw = dict(request)
    scanner_ref = raw.pop("scanner_image")
    scanner_id = raw.pop("scanner_image_id")
    operation_id, attempt_id = _validate_request(raw)
    scanner_request = dict(raw, image_ref=scanner_ref, image_id=scanner_id)
    _validate_request(scanner_request)
    candidate = _pinned_image(api, raw["image_ref"], raw["image_id"], raw["max_disk_gb"])
    scanner = _pinned_image(api, scanner_ref, scanner_id, raw["max_disk_gb"])
    name = f"prep-{attempt_id.hex}"
    scope = f"projects/{raw['project_id']}/zones/{raw['zone']}"
    labels = {
        "shifter-preparation": operation_id.hex,
        "preparation-attempt": attempt_id.hex,
        "preparation-role": "verify",
    }
    data_path = f"{scope}/disks/{name}-data"
    api.create(
        f"{scope}/disks",
        {"name": name + "-data", "sourceImage": raw["image_ref"], "sizeGb": candidate["diskSizeGb"], "labels": labels},
        str(uuid5(attempt_id, "scan-data")),
    )
    data = api.get(data_path)
    if str(data.get("sourceImageId")) != raw["image_id"]:
        raise ValueError("scanner data disk does not match the pinned candidate")
    guest = _guest(
        scanner_request,
        name + "-scan",
        int(scanner["diskSizeGb"]),
        labels,
        _startup(context, attempt_id, verify_output=verify_output),
    )
    api.create(f"{scope}/instances", guest, str(uuid5(attempt_id, "scanner")))
    scanner_disk_path = f"{scope}/disks/{name}-scan"
    if str(api.get(scanner_disk_path).get("sourceImageId")) != scanner_id:
        raise ValueError("scanner boot disk does not derive from the approved scanner")
    instance_path = f"{scope}/instances/{name}-scan"
    # Candidate and scanner can share a base image, including partition and
    # filesystem UUIDs. Attach only after scanner boot so fstab cannot select
    # candidate partitions for the scanner's own root or EFI mounts.
    api.wait_for_ready(instance_path, str(attempt_id))
    api.attach_readonly(instance_path, data_path, str(uuid5(attempt_id, "attach-candidate")))
    initial = api.get(instance_path)
    _verify_scanner(initial, raw["subnetwork"], scanner_disk_path, data_path)
    observation = api.wait_for_observation(instance_path, str(attempt_id))
    instance = api.get(instance_path)
    _verify_scanner(instance, raw["subnetwork"], scanner_disk_path, data_path)
    if (
        instance.get("status") != "TERMINATED"
        or instance.get("id") != initial.get("id")
        or str(api.get(data_path).get("id")) != str(data["id"])
    ):
        raise ValueError("scanner ownership changed during observation")
    if observation.get("size_bytes") != int(candidate["diskSizeGb"]) * 1024**3:
        raise ValueError("scanner did not measure the complete candidate disk")
    api.clear_metadata(instance_path)
    return {**observation, "image_ref": raw["image_ref"], "image_id": raw["image_id"], "disk_id": str(data["id"])}


def _pinned_image(api: ComputeAPI, reference: str, identity: str, max_disk_gb: int) -> dict[str, Any]:
    """Handle pinned image."""
    image = api.get(reference)
    if (
        image.get("status") != "READY"
        or str(image.get("id")) != identity
        or not 0 < int(image.get("diskSizeGb", 0)) <= max_disk_gb
    ):
        raise ValueError("pinned scanner or candidate image is unavailable")
    return image


def _verify_scanner(instance: dict[str, Any], network: str, boot: str, data: str) -> None:
    """Handle verify scanner."""
    interfaces = instance.get("networkInterfaces", [])
    disks = instance.get("disks", [])
    if len(interfaces) != 1 or len(disks) != 2:
        raise ValueError("independent scanner isolation could not be verified")
    invalid = (
        bool(instance.get("serviceAccounts")),
        bool(interfaces[0].get("accessConfigs")),
        bool(interfaces[0].get("ipv6AccessConfigs")),
        not _same_ref(interfaces[0].get("subnetwork"), network),
        not _same_ref(disks[0].get("source"), boot),
        disks[0].get("boot") is not True,
        not _same_ref(disks[1].get("source"), data),
        disks[1].get("mode") != "READ_ONLY",
        disks[1].get("deviceName") != "shifter-candidate",
    )
    if any(invalid):
        raise ValueError("independent scanner isolation could not be verified")


def _startup(context: dict[str, bytes], attempt_id: UUID, *, verify_output: bool) -> str:
    """Stage trusted verifier code separately from candidate data; never execute the image."""
    if any(
        not re.fullmatch(r"[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*", name) or ".." in name.split("/") for name in context
    ):
        raise ValueError("invalid contained verifier path")
    if sum(map(len, context.values())) > 96 * 1024:
        raise ValueError("contained verifier exceeds the metadata profile")
    files = {"context/" + name: value for name, value in context.items()}
    for name in ("scan_guest.py", "raw_disk.py"):
        files[name] = Path(__file__).with_name(name).read_bytes()
    encoded = base64.b64encode(
        json.dumps({name: base64.b64encode(value).decode() for name, value in files.items()}).encode()
    ).decode()
    mode = " --verify-output" if verify_output else ""
    return (
        STARTUP
        + f'''
python3 -I - <<'SHIFTER_SCANNER'
import base64, json, pathlib
root = pathlib.Path("/var/lib/shifter-scan")
root.mkdir(mode=0o700, parents=True, exist_ok=False)
for name, data in json.loads(base64.b64decode("{encoded}")).items():
    target = root / name
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(data))
SHIFTER_SCANNER
printf '%s\\n' 'SHIFTER_PREPARATION_READY:{attempt_id}' > /dev/ttyS0
for attempt in $(seq 1 90); do
    if [ -b /dev/disk/by-id/google-shifter-candidate ]; then break; fi
    sleep 2
done
python3 -I /var/lib/shifter-scan/scan_guest.py {attempt_id}{mode}
'''
    )
