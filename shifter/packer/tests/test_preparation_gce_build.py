"""The GCE profile pins actual source IDs and keeps build guests credentialless."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest


def test_standard_e2_uses_supported_maintenance_policy_without_losing_runtime_limit():
    from preparation.gce_build import _guest

    guest = _guest(request(), "prep-example", 10, {"shifter-preparation": "example"}, "")
    assert guest["scheduling"]["onHostMaintenance"] == "MIGRATE"
    assert guest["scheduling"]["instanceTerminationAction"] == "STOP"
    assert guest["scheduling"]["maxRunDuration"] == {"seconds": "3600"}


def module():
    spec = importlib.util.spec_from_file_location(
        "preparation_gce_build", Path(__file__).parents[1] / "preparation/gce_build.py"
    )
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class Compute:
    def __init__(self, source_id="111", credentials=False, isolation_violation=None):
        self.source_id = source_id
        self.credentials = credentials
        self.isolation_violation = isolation_violation
        self.calls = []

    def get(self, path):
        self.calls.append(("get", path))
        if path.endswith("/images/base"):
            return {"id": "111", "status": "READY", "diskSizeGb": "10"}
        if "/disks/" in path:
            return {"id": "222", "sourceImageId": self.source_id, "sizeGb": "10"}
        if "/images/" in path:
            return {"id": "333", "sourceDiskId": "222", "status": "READY"}
        instance = {
            "id": "444",
            "status": "TERMINATED",
            "serviceAccounts": [{"email": "unexpected@example.invalid"}] if self.credentials else [],
            "networkInterfaces": [
                {
                    "subnetwork": "https://www.googleapis.com/compute/v1/projects/test-project/regions/us-central1/subnetworks/preparation"
                }
            ],
            "disks": [{"source": path.replace("/instances/", "/disks/"), "boot": True, "autoDelete": False}],
        }
        network = instance["networkInterfaces"][0]
        disk = instance["disks"][0]
        if self.isolation_violation == "extra-network":
            instance["networkInterfaces"].append(dict(network))
        elif self.isolation_violation == "external-ip":
            network["accessConfigs"] = [{"natIP": "203.0.113.1"}]
        elif self.isolation_violation == "external-ipv6":
            network["ipv6AccessConfigs"] = [{"externalIpv6": "2001:db8::1"}]
        elif self.isolation_violation == "wrong-subnetwork":
            network["subnetwork"] = "projects/test-project/regions/us-central1/subnetworks/other"
        elif self.isolation_violation == "extra-disk":
            instance["disks"].append(dict(disk))
        elif self.isolation_violation == "not-boot":
            disk["boot"] = False
        elif self.isolation_violation == "auto-delete":
            disk["autoDelete"] = True
        elif self.isolation_violation == "wrong-disk":
            disk["source"] = "projects/test-project/zones/us-central1-a/disks/other"
        return instance

    def create(self, path, body, request_id):
        self.calls.append(("create", path, body, request_id))

    def wait_for_build(self, instance_path, nonce):
        self.calls.append(("wait", instance_path, nonce))

    def clear_metadata(self, path):
        self.calls.append(("clear", path))


def request():
    return {
        "operation_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "project_id": "test-project",
        "zone": "us-central1-a",
        "subnetwork": "projects/test-project/regions/us-central1/subnetworks/preparation",
        "image_ref": "projects/test-project/global/images/base",
        "image_id": "111",
        "max_disk_gb": 40,
        "max_duration_seconds": 3600,
    }


def test_actual_image_lineage_is_read_back_after_credentialless_build():
    api = Compute()
    result = module().build_image(api, request(), {"build.sh": b"true", "verify.sh": b"true"})
    creates = [call for call in api.calls if call[0] == "create"]
    guest = creates[0][2]
    assert guest["serviceAccounts"] == []
    assert "accessConfigs" not in guest["networkInterfaces"][0]
    assert guest["disks"][0]["initializeParams"]["sourceImage"].endswith("/images/base")
    assert guest["disks"][0]["autoDelete"] is False
    assert guest["scheduling"]["maxRunDuration"] == {"seconds": "3600"}
    assert {"key": "block-project-ssh-keys", "value": "TRUE"} in guest["metadata"]["items"]
    assert result["image_id"] == "333"
    assert result["source_image_id"] == "111"
    assert result["source_disk_id"] == "222"
    assert result["builder_instance_id"] == "444"
    assert [c[0] for c in api.calls].index("clear") < api.calls.index(creates[1])


def test_source_name_replacement_between_read_and_disk_creation_never_creates_image():
    api = Compute(source_id="999")
    with pytest.raises(ValueError):
        module().build_image(api, request(), {"build.sh": b"true", "verify.sh": b"true"})
    assert len([call for call in api.calls if call[0] == "create"]) == 1


def test_unexpected_guest_cloud_credentials_never_produce_a_candidate():
    api = Compute(credentials=True)
    with pytest.raises(ValueError):
        module().build_image(api, request(), {"build.sh": b"true", "verify.sh": b"true"})
    assert len([call for call in api.calls if call[0] == "create"]) == 1


@pytest.mark.parametrize(
    "violation",
    [
        "extra-network",
        "external-ip",
        "external-ipv6",
        "wrong-subnetwork",
        "extra-disk",
        "not-boot",
        "auto-delete",
        "wrong-disk",
    ],
)
def test_each_build_guest_isolation_violation_prevents_candidate_creation(violation):
    api = Compute(isolation_violation=violation)

    with pytest.raises(ValueError, match="isolation"):
        module().build_image(api, request(), {"build.sh": b"true", "verify.sh": b"true"})

    assert len([call for call in api.calls if call[0] == "create"]) == 1


@pytest.mark.parametrize(
    "field,value",
    [("image_id", "999"), ("max_disk_gb", 1), ("image_ref", "projects/test-project/global/images/family/ubuntu")],
)
def test_unpinned_or_over_budget_input_never_creates_guest(field, value):
    api = Compute()
    raw = request()
    raw[field] = value
    with pytest.raises(ValueError):
        module().build_image(api, raw, {"build.sh": b"true", "verify.sh": b"true"})
    assert not [call for call in api.calls if call[0] == "create"]
