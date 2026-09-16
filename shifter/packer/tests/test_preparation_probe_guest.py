"""The functional probe executes approved code in a separate pinned guest."""

from copy import deepcopy
from uuid import uuid4

import pytest

from preparation.gce_probe import probe_from_guest


class Compute:
    def __init__(self, source_id="123", receipt=True, *, instance_overrides=None):
        self.source_id = source_id
        self.receipt = receipt
        self.guest = None
        self.instance_overrides = instance_overrides or []
        self.instance_reads = 0

    def create(self, path, body, request_id):
        self.guest = deepcopy(body)

    def get(self, path):
        if "/images/" in path:
            return {"id": "123", "status": "READY", "diskSizeGb": "10"}
        if "/disks/" in path:
            return {"id": "234", "sourceImageId": self.source_id}
        instance = dict(
            self.guest,
            status="TERMINATED",
            disks=[
                {
                    "source": path.replace("/instances/", "/disks/"),
                    "boot": True,
                    "autoDelete": False,
                }
            ],
        )
        if self.instance_reads < len(self.instance_overrides):
            instance.update(deepcopy(self.instance_overrides[self.instance_reads]))
        self.instance_reads += 1
        return instance

    def wait_for_observation(self, path, nonce):
        return {"boot_observed": self.receipt}

    def clear_metadata(self, path):
        pass


def request():
    return {
        "operation_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "project_id": "test-project",
        "zone": "us-central1-a",
        "subnetwork": "projects/test-project/regions/us-central1/subnetworks/preparation",
        "image_ref": "projects/test-project/global/images/scanner",
        "image_id": "123",
        "max_disk_gb": 20,
        "max_duration_seconds": 1200,
    }


def test_probe_requires_fresh_receipt_and_approved_scanner_source():
    api = Compute()
    raw = request()
    assert probe_from_guest(api, raw, b"def probe_http(host, nonce): return True", "10.240.0.2", raw["attempt_id"])
    assert api.guest["serviceAccounts"] == []
    assert api.guest["tags"]["items"] == ["shifter-preparation"]


@pytest.mark.parametrize("source_id,receipt", [("999", True), ("123", False), ("123", "true")])
def test_probe_rejects_changed_scanner_or_nonpassing_receipt(source_id, receipt):
    raw = request()
    with pytest.raises(ValueError):
        probe_from_guest(Compute(source_id, receipt), raw, b"pass", "10.240.0.2", raw["attempt_id"])


@pytest.mark.parametrize(
    "overrides",
    [
        [{"serviceAccounts": [{"email": "unexpected@example.invalid"}]}],
        [{}, {"serviceAccounts": [{"email": "added-during-probe@example.invalid"}]}],
    ],
)
def test_probe_rejects_isolation_drift_before_or_during_observation(overrides):
    raw = request()
    with pytest.raises(ValueError, match="isolation"):
        probe_from_guest(
            Compute(instance_overrides=overrides),
            raw,
            b"pass",
            "10.240.0.2",
            raw["attempt_id"],
        )
