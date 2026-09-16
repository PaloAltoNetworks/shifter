"""Boot evidence requires an independent fresh probe of the actual candidate VM."""

from copy import deepcopy
from uuid import uuid4

import pytest


class Compute:
    def __init__(self, image_id="111", *, instance_overrides=None, disk_source_reads=None):
        self.image_id = image_id
        self.guest = None
        self.instance_overrides = instance_overrides or []
        self.disk_source_reads = disk_source_reads or []
        self.instance_reads = 0
        self.disk_reads = 0

    def get(self, path):
        if "/images/" in path:
            return {"id": "111", "status": "READY", "diskSizeGb": "10"}
        if "/disks/" in path:
            source = (
                self.disk_source_reads[self.disk_reads]
                if self.disk_reads < len(self.disk_source_reads)
                else self.image_id
            )
            self.disk_reads += 1
            return {"id": "222", "sourceImageId": source}
        instance = {
            "id": "333",
            "status": "RUNNING",
            "serviceAccounts": [],
            "networkInterfaces": [dict(self.guest["networkInterfaces"][0], networkIP="10.0.0.5")],
            "disks": [{"source": path.replace("/instances/", "/disks/"), "boot": True, "autoDelete": False}],
        }
        if self.instance_reads < len(self.instance_overrides):
            instance.update(deepcopy(self.instance_overrides[self.instance_reads]))
        self.instance_reads += 1
        return instance

    def create(self, path, body, request_id):
        self.guest = deepcopy(body)


def request():
    return {
        "operation_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "project_id": "test-project",
        "zone": "us-central1-a",
        "subnetwork": "projects/test-project/regions/us-central1/subnetworks/preparation",
        "image_ref": "projects/test-project/global/images/candidate",
        "image_id": "111",
        "max_disk_gb": 40,
        "max_duration_seconds": 3600,
    }


def test_boot_proof_uses_observed_private_ip_and_new_attempt_challenge():
    from preparation.gce_boot import verify_boot

    seen = []
    raw = request()

    def probe(ip, nonce):
        seen.append((ip, nonce))
        return True

    assert verify_boot(Compute(), raw, probe) == {"boot_observed": True}
    assert seen == [("10.0.0.5", raw["attempt_id"])]


def test_vm_running_without_successful_probe_is_not_boot_proof():
    from preparation.gce_boot import verify_boot

    with pytest.raises(ValueError):
        verify_boot(Compute(), request(), lambda ip, nonce: False)


def test_replaced_candidate_id_is_rejected_before_any_probe():
    from preparation.gce_boot import verify_boot

    def forbidden(ip, nonce):
        raise AssertionError("must not probe a substituted artifact")

    with pytest.raises(ValueError):
        verify_boot(Compute(image_id="999"), request(), forbidden)


def test_boot_probe_rejects_an_isolation_violation_before_network_probe():
    from preparation.gce_boot import verify_boot

    api = Compute(instance_overrides=[{"serviceAccounts": [{"email": "unexpected@example.invalid"}]}])
    with pytest.raises(ValueError, match="isolation"):
        verify_boot(api, request(), lambda ip, nonce: True)


@pytest.mark.parametrize("changed", [{"id": "999"}, {"status": "TERMINATED"}])
def test_boot_probe_rejects_instance_replacement_during_verification(changed):
    from preparation.gce_boot import verify_boot

    api = Compute(instance_overrides=[{}, changed])
    with pytest.raises(ValueError, match="changed during verification"):
        verify_boot(api, request(), lambda ip, nonce: True)


def test_boot_probe_rejects_disk_source_replacement_during_verification():
    from preparation.gce_boot import verify_boot

    api = Compute(disk_source_reads=["111", "999"])
    with pytest.raises(ValueError, match="source changed"):
        verify_boot(api, request(), lambda ip, nonce: True)
