"""Run an independently installed functional probe inside the isolated VPC."""

from __future__ import annotations

import base64
import ipaddress
from typing import Any
from uuid import UUID, uuid5

from preparation.gce_build import ComputeAPI, _guest, _validate_request, _verify_guest_isolation
from preparation.gce_verify import _pinned_image
from preparation.guest_runtime import STARTUP


def probe_from_guest(api: ComputeAPI, request: dict[str, Any], probe: bytes, host: str, nonce: str) -> bool:
    """Reach a private candidate without platform peering or public ingress.

    The caller supplies the approved scanner identity and independently verified
    context's probe code. The candidate cannot supply either executable.
    """
    operation_id, attempt_id = _validate_request(request)
    UUID(nonce)
    address = ipaddress.ip_address(host)
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_link_local:
        raise ValueError("invalid private probe address")
    if len(probe) > 96 * 1024:
        raise ValueError("probe material exceeds the metadata profile")
    image = _pinned_image(api, request["image_ref"], request["image_id"], request["max_disk_gb"])
    name = f"prep-{attempt_id.hex}-probe"
    scope = f"projects/{request['project_id']}/zones/{request['zone']}"
    labels = {
        "shifter-preparation": operation_id.hex,
        "preparation-attempt": attempt_id.hex,
        "preparation-role": "verify",
    }
    startup = _startup(probe, str(address), nonce, str(attempt_id))
    api.create(
        f"{scope}/instances",
        _guest(request, name, int(image["diskSizeGb"]), labels, startup),
        str(uuid5(attempt_id, "functional-probe")),
    )
    disk_path = f"{scope}/disks/{name}"
    instance_path = f"{scope}/instances/{name}"
    if str(api.get(disk_path).get("sourceImageId")) != request["image_id"]:
        raise ValueError("functional probe does not use the approved scanner")
    _verify_guest_isolation(api.get(instance_path), request["subnetwork"], disk_path)
    receipt = api.wait_for_observation(instance_path, str(attempt_id))
    observed = api.get(instance_path)
    _verify_guest_isolation(observed, request["subnetwork"], disk_path)
    if observed.get("status") != "TERMINATED" or receipt != {"boot_observed": True}:
        raise ValueError("candidate did not pass the independent functional probe")
    api.clear_metadata(instance_path)
    return True


def _startup(probe: bytes, host: str, nonce: str, attempt_id: str) -> str:
    """Handle startup."""
    encoded = base64.b64encode(probe).decode()
    return (
        STARTUP
        + f'''
python3 -I - <<'SHIFTER_PROBE'
import base64, importlib.util, json, pathlib
root = pathlib.Path("/var/lib/shifter-probe")
root.mkdir(mode=0o700, parents=True, exist_ok=False)
path = root / "verify_boot.py"
path.write_bytes(base64.b64decode("{encoded}"))
spec = importlib.util.spec_from_file_location("approved_probe", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
passed = module.probe_http("{host}", "{nonce}") is True
result = base64.b64encode(json.dumps({{"boot_observed": passed}}).encode()).decode()
with open("/dev/ttyS0", "w") as serial:
    serial.write("SHIFTER_PREPARATION_OBSERVATION:{attempt_id}:" + result + "\\n")
SHIFTER_PROBE
poweroff
'''
    )
