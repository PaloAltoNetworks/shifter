"""Independent scanning pins both the candidate and the approved scanner image."""

from copy import deepcopy
from uuid import uuid4

import pytest


class Compute:
    def __init__(
        self,
        scanner_source="222",
        *,
        candidate_source="111",
        instance_overrides=None,
        data_disk_ids=None,
        size_bytes=10 * 1024**3,
    ):
        self.scanner_source = scanner_source
        self.candidate_source = candidate_source
        self.instance_overrides = instance_overrides or []
        self.data_disk_ids = data_disk_ids or []
        self.size_bytes = size_bytes
        self.created = []
        self.ready = False
        self.attached = None
        self.instance_reads = 0
        self.data_disk_reads = 0

    def get(self, path):
        if path.endswith("/images/candidate"):
            return {"id": "111", "status": "READY", "diskSizeGb": "10"}
        if path.endswith("/images/scanner"):
            return {"id": "222", "status": "READY", "diskSizeGb": "10"}
        if "/disks/" in path:
            if path.endswith("-data"):
                identity = (
                    self.data_disk_ids[self.data_disk_reads]
                    if self.data_disk_reads < len(self.data_disk_ids)
                    else "333"
                )
                self.data_disk_reads += 1
                return {"id": identity, "sourceImageId": self.candidate_source}
            return {"id": "333", "sourceImageId": self.scanner_source}
        guest = self.created[-1][1]
        instance = {
            "id": "444",
            "status": "TERMINATED",
            "serviceAccounts": [],
            "networkInterfaces": guest["networkInterfaces"],
            "disks": [
                {"source": path.replace("/instances/", "/disks/"), "boot": True},
                {
                    "source": path.replace("/instances/", "/disks/").replace("-scan", "-data"),
                    "mode": "READ_ONLY",
                    "deviceName": "shifter-candidate",
                },
            ],
        }
        if self.instance_reads < len(self.instance_overrides):
            instance.update(deepcopy(self.instance_overrides[self.instance_reads]))
        self.instance_reads += 1
        return instance

    def create(self, path, body, request_id):
        self.created.append((path, body, request_id))

    def wait_for_ready(self, path, nonce):
        assert len(self.created[-1][1]["disks"]) == 1
        self.ready = True

    def attach_readonly(self, path, disk, request_id):
        assert self.ready, "candidate must be attached after boot to avoid duplicate filesystem identifiers"
        self.attached = {"source": disk, "mode": "READ_ONLY", "deviceName": "shifter-candidate"}

    def wait_for_observation(self, path, nonce):
        return {"raw_disk_digest": "sha256:" + "a" * 64, "size_bytes": self.size_bytes}

    def clear_metadata(self, path):
        pass


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
        "scanner_image": "projects/test-project/global/images/scanner",
        "scanner_image_id": "222",
    }


def test_candidate_bytes_are_scanned_on_an_independently_pinned_credentialless_guest():
    from preparation.gce_verify import scan_image

    api = Compute()
    observed = scan_image(api, request(), {}, verify_output=False)
    guest = api.created[-1][1]
    assert guest["serviceAccounts"] == []
    assert len(guest["disks"]) == 1
    assert api.attached["mode"] == "READ_ONLY"
    assert api.attached["deviceName"] == "shifter-candidate"
    assert observed["image_id"] == "111"
    assert observed["disk_id"] == "333"
    assert observed["raw_disk_digest"] == "sha256:" + "a" * 64


def test_scanner_name_replacement_cannot_emit_trusted_evidence():
    from preparation.gce_verify import scan_image

    with pytest.raises(ValueError):
        scan_image(Compute(scanner_source="999"), request(), {}, verify_output=False)


def test_candidate_disk_name_replacement_cannot_emit_trusted_evidence():
    from preparation.gce_verify import scan_image

    with pytest.raises(ValueError, match="data disk does not match"):
        scan_image(Compute(candidate_source="999"), request(), {}, verify_output=False)


@pytest.mark.parametrize(
    "api,error",
    [
        (Compute(instance_overrides=[{}, {"id": "999"}]), "ownership changed"),
        (Compute(data_disk_ids=["333", "999"]), "ownership changed"),
        (Compute(size_bytes=9 * 1024**3), "complete candidate disk"),
    ],
)
def test_scanner_rejects_instance_disk_or_size_changes_during_observation(api, error):
    from preparation.gce_verify import scan_image

    with pytest.raises(ValueError, match=error):
        scan_image(api, request(), {}, verify_output=False)


def _scanner_instance():
    scope = "projects/test-project/zones/us-central1-a/disks/prep"
    return {
        "serviceAccounts": [],
        "networkInterfaces": [{"subnetwork": "projects/test-project/regions/us-central1/subnetworks/preparation"}],
        "disks": [
            {"source": scope + "-scan", "boot": True},
            {"source": scope + "-data", "mode": "READ_ONLY", "deviceName": "shifter-candidate"},
        ],
    }


@pytest.mark.parametrize(
    "violation",
    [
        "credentials",
        "extra-network",
        "external-ip",
        "external-ipv6",
        "wrong-subnetwork",
        "wrong-disk-count",
        "wrong-boot-source",
        "not-boot",
        "wrong-data-source",
        "writable-data",
        "wrong-device",
    ],
)
def test_each_scanner_isolation_violation_is_rejected(violation):
    from preparation.gce_verify import _verify_scanner

    instance = _scanner_instance()
    network = instance["networkInterfaces"][0]
    boot, data = instance["disks"]
    if violation == "credentials":
        instance["serviceAccounts"] = [{"email": "unexpected@example.invalid"}]
    elif violation == "extra-network":
        instance["networkInterfaces"].append(dict(network))
    elif violation == "external-ip":
        network["accessConfigs"] = [{}]
    elif violation == "external-ipv6":
        network["ipv6AccessConfigs"] = [{}]
    elif violation == "wrong-subnetwork":
        network["subnetwork"] = "projects/test-project/regions/us-central1/subnetworks/other"
    elif violation == "wrong-disk-count":
        instance["disks"].pop()
    elif violation == "wrong-boot-source":
        boot["source"] += "-other"
    elif violation == "not-boot":
        boot["boot"] = False
    elif violation == "wrong-data-source":
        data["source"] += "-other"
    elif violation == "writable-data":
        data["mode"] = "READ_WRITE"
    elif violation == "wrong-device":
        data["deviceName"] = "candidate"

    with pytest.raises(ValueError, match="scanner isolation"):
        _verify_scanner(
            instance,
            "projects/test-project/regions/us-central1/subnetworks/preparation",
            "projects/test-project/zones/us-central1-a/disks/prep-scan",
            "projects/test-project/zones/us-central1-a/disks/prep-data",
        )
