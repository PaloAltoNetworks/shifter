"""Contained GCE image construction; candidate creation never means admission.

The authenticated worker supplies an already verified locked base and context.
The cloud client performs bounded real provider operations. Every resource name
comes from operation/attempt UUIDs; recipes cannot choose projects or identities.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

from preparation.compute import reference_matches as _same_ref
from preparation.guest_runtime import STARTUP

_PROJECT = r"[a-z][a-z0-9-]{4,61}[a-z0-9]"
_IMAGE = re.compile(rf"^projects/{_PROJECT}/global/images/[a-z][a-z0-9-]{{0,62}}$")


class ComputeAPI(Protocol):
    """The small GCE surface used by this contained profile."""

    project: str
    zone: str

    def get(self, path: str) -> dict[str, Any]: ...
    def create(self, path: str, body: dict[str, Any], request_id: str) -> None: ...
    def list_owned(self, path: str, operation_id: UUID) -> list[dict[str, Any]]: ...
    def delete_owned(self, path: str, resource_id: str, operation_id: UUID) -> None: ...
    def wait_for_attempt_operations(self, attempts: list[UUID]) -> None: ...
    def wait_for_build(self, instance_path: str, nonce: str) -> None: ...
    def wait_for_ready(self, instance_path: str, nonce: str) -> None: ...
    def wait_for_observation(self, instance_path: str, nonce: str) -> dict[str, Any]: ...
    def attach_readonly(self, path: str, disk: str, request_id: str) -> None: ...
    def clear_metadata(self, path: str) -> None: ...


def build_image(api: ComputeAPI, request: dict[str, Any], context: dict[str, bytes]) -> dict[str, str]:
    """Build from a pinned base, then read immutable image and disk lineage."""
    operation_id, attempt_id = _validate_request(request)
    source = api.get(request["image_ref"])
    size = int(source.get("diskSizeGb", 0))
    if source.get("status") != "READY" or str(source.get("id")) != request["image_id"]:
        raise ValueError("locked base image is unavailable")
    if size < 1 or size > request["max_disk_gb"]:
        raise ValueError("locked base image exceeds the granted disk budget")
    name = f"prep-{attempt_id.hex}"
    zonal = f"projects/{request['project_id']}/zones/{request['zone']}"
    labels = {
        "shifter-preparation": operation_id.hex,
        "preparation-attempt": attempt_id.hex,
        "preparation-role": "build",
    }
    guest = _guest(request, name, size, labels, _startup_script(context, str(attempt_id)))
    api.create(f"{zonal}/instances", guest, str(uuid5(attempt_id, "build-guest")))
    # The source name may have been deleted/recreated between images.get and
    # disk creation. Its actual sourceImageId, not the requested URI, is proof.
    disk_path = f"{zonal}/disks/{name}"
    disk = api.get(disk_path)
    if str(disk.get("sourceImageId")) != request["image_id"]:
        raise ValueError("build disk does not derive from the verified input")
    instance_path = f"{zonal}/instances/{name}"
    api.wait_for_build(instance_path, str(attempt_id))
    instance = api.get(instance_path)
    if instance.get("status") != "TERMINATED":
        raise ValueError("build guest did not stop before candidate creation")
    _verify_guest_isolation(instance, request["subnetwork"], disk_path)
    api.clear_metadata(instance_path)
    image_path = f"projects/{request['project_id']}/global/images"
    api.create(
        image_path, {"name": name, "sourceDisk": disk_path, "labels": labels}, str(uuid5(attempt_id, "candidate"))
    )
    image = api.get(f"{image_path}/{name}")
    if image.get("status") != "READY" or str(image.get("sourceDiskId")) != str(disk.get("id")):
        raise ValueError("candidate image lineage could not be verified")
    return {
        "image_ref": f"{image_path}/{name}",
        "image_id": str(image["id"]),
        "source_disk_id": str(disk["id"]),
        "source_image_id": str(disk["sourceImageId"]),
        "builder_instance_id": str(instance["id"]),
    }


def _verify_guest_isolation(instance: dict[str, Any], subnetwork: str, disk_path: str) -> None:
    """Check provider-observed guest isolation, not just the requested settings."""
    networks = instance.get("networkInterfaces", [])
    disks = instance.get("disks", [])
    if (
        instance.get("serviceAccounts")
        or len(networks) != 1
        or networks[0].get("accessConfigs")
        or networks[0].get("ipv6AccessConfigs")
        or not _same_ref(networks[0].get("subnetwork"), subnetwork)
        or len(disks) != 1
        or disks[0].get("boot") is not True
        or disks[0].get("autoDelete") is not False
        or not _same_ref(disks[0].get("source"), disk_path)
    ):
        raise ValueError("build guest isolation could not be verified")


def _validate_request(request: dict[str, Any]) -> tuple[UUID, UUID]:
    """Contain the profile's operational projection before any provider call."""
    required = {
        "operation_id",
        "attempt_id",
        "project_id",
        "zone",
        "subnetwork",
        "image_ref",
        "image_id",
        "max_disk_gb",
        "max_duration_seconds",
    }
    if set(request) != required:
        raise ValueError("invalid contained build request")
    if any(
        (
            not re.fullmatch(_PROJECT, request["project_id"]),
            not re.fullmatch(r"[a-z]+-[a-z]+\d-[a-z]", request["zone"]),
        )
    ):
        raise ValueError("invalid build scope")
    region = request["zone"].rsplit("-", 1)[0]
    network = rf"projects/{request['project_id']}/regions/{region}/subnetworks/[a-z][a-z0-9-]{{0,62}}"
    if any((not re.fullmatch(network, request["subnetwork"]), not _IMAGE.fullmatch(request["image_ref"]))):
        raise ValueError("invalid pinned input or network")
    if not re.fullmatch(r"[1-9]\d{0,19}", request["image_id"]):
        raise ValueError("invalid pinned image identity")
    if not _bounded_int(request["max_disk_gb"], 1, 200):
        raise ValueError("invalid build budget")
    if not _bounded_int(request["max_duration_seconds"], 60, 7200):
        raise ValueError("invalid build duration")
    return UUID(request["operation_id"]), UUID(request["attempt_id"])


def _bounded_int(value: object, minimum: int, maximum: int) -> bool:
    """Accept a plain integer within the closed preparation budget."""
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return minimum <= value <= maximum


def _guest(request: dict[str, Any], name: str, size: int, labels: dict[str, str], startup: str) -> dict[str, Any]:
    """Disposable guest with no service account, external IP, or caller options."""
    return {
        "name": name,
        "machineType": f"projects/{request['project_id']}/zones/{request['zone']}/machineTypes/e2-standard-2",
        "labels": labels,
        "tags": {"items": ["shifter-preparation"]},
        "serviceAccounts": [],
        "networkInterfaces": [{"subnetwork": request["subnetwork"]}],
        "disks": [
            {
                "boot": True,
                "autoDelete": False,
                "type": "PERSISTENT",
                "initializeParams": {
                    "diskName": name,
                    "sourceImage": request["image_ref"],
                    "diskSizeGb": str(size),
                    "labels": labels,
                },
            }
        ],
        "metadata": {
            "items": [
                {"key": "startup-script", "value": startup},
                {"key": "enable-oslogin", "value": "FALSE"},
                {"key": "block-project-ssh-keys", "value": "TRUE"},
            ]
        },
        "scheduling": {
            "automaticRestart": False,
            # Standard E2 rejects TERMINATE. Live migration does not reset the
            # separately enforced maximum run duration or admit any output.
            "onHostMaintenance": "MIGRATE",
            "maxRunDuration": {"seconds": str(request["max_duration_seconds"])},
            "instanceTerminationAction": "STOP",
        },
    }


def _startup_script(context: dict[str, bytes], nonce: str) -> str:
    """Deliver only contained bytes, without downloads or credentials on the VM.

    The initial profile bounds contexts to fit GCE metadata. Larger private
    recipes require a separately qualified delivery profile, not an implicit URL.
    """
    if not {"build.sh", "verify.sh"}.issubset(context) or sum(map(len, context.values())) > 96 * 1024:
        raise ValueError("contained build material exceeds the metadata profile")
    if any(
        not re.fullmatch(r"[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*", name) or ".." in name.split("/") for name in context
    ):
        raise ValueError("invalid contained build path")
    if "_shifter_sanitize.py" in context:
        raise ValueError("contained build uses a reserved runtime path")
    files = {**context, "_shifter_sanitize.py": Path(__file__).with_name("sanitize_guest.py").read_bytes()}
    encoded = base64.b64encode(
        json.dumps({name: base64.b64encode(data).decode() for name, data in files.items()}).encode()
    ).decode()
    return (
        STARTUP
        + f'''
# The guest startup runner and cloud-init can run concurrently. Complete
# first-boot writes before installing and sanitizing the candidate filesystem.
timeout 240 cloud-init status --wait >/dev/null 2>&1
python3 -I - <<'SHIFTER_PREPARATION'
import base64, json, pathlib
root = pathlib.Path("/var/lib/shifter-preparation")
root.mkdir(mode=0o700, parents=True, exist_ok=False)
for name, data in json.loads(base64.b64decode("{encoded}")).items():
    target = root / name
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(data))
SHIFTER_PREPARATION
bash /var/lib/shifter-preparation/build.sh
cloud-init clean --logs >/dev/null 2>&1
python3 -I /var/lib/shifter-preparation/_shifter_sanitize.py
sync
printf '%s\\n' 'SHIFTER_PREPARATION_DONE:{nonce}' > /dev/ttyS0
poweroff
'''
    )
