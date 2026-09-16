"""Inventory admission independently rereads provider ownership and lineage."""

from copy import deepcopy
from uuid import uuid4

import pytest

from shared.cloud.preparation_readback import GCEPreparationReadback
from shared.preparation_grant import PreparationGrantConfiguration
from tests.shared.test_preparation_grant import grant_configuration


def fixture():
    operation, attempt = uuid4(), uuid4()
    grant = PreparationGrantConfiguration.model_validate(grant_configuration())
    name = "prep-" + attempt.hex
    scope = f"projects/{grant.project_id}/zones/{grant.zone}"
    labels = {"shifter-preparation": operation.hex, "preparation-attempt": attempt.hex}
    ref = f"projects/{grant.project_id}/global/images/{name}"
    documents = {
        ref: {"id": "555", "status": "READY", "sourceDiskId": "333", "labels": labels},
        f"{scope}/disks/{name}": {"id": "333", "sourceImageId": "111", "labels": labels},
        f"{scope}/instances/{name}": {
            "id": "222",
            "status": "TERMINATED",
            "labels": labels,
            "networkInterfaces": [{"subnetwork": grant.subnetwork}],
            "serviceAccounts": [],
            "disks": [{"source": f"{scope}/disks/{name}", "boot": True}],
        },
    }
    built = {
        "image_ref": ref,
        "image_id": "555",
        "source_disk_id": "333",
        "source_image_id": "111",
        "builder_instance_id": "222",
    }
    return operation, attempt, grant, documents, built


class Reader:
    def __init__(self, documents):
        self.documents, self.reads = documents, []

    def get(self, path, **kwargs):
        self.reads.append(path)
        return deepcopy(self.documents[path])


@pytest.mark.parametrize("failure", [None, "disk", "replacement", "pending"])
def test_cleanup_checks_provider_absence_and_only_retains_the_admitted_image(failure):
    operation, attempt, grant, _, built = fixture()
    scope = f"projects/{grant.project_id}/zones/{grant.zone}"
    image_scope = f"projects/{grant.project_id}/global/images"
    owned = {
        "name": built["image_ref"].rsplit("/", 1)[-1],
        "id": built["image_id"],
        "labels": {"shifter-preparation": operation.hex},
    }
    docs = {
        f"{scope}/instances": {},
        f"{scope}/disks": {},
        image_scope: {"items": [owned]},
        f"{scope}/operations": {},
        f"projects/{grant.project_id}/global/operations": {},
    }
    if failure == "disk":
        docs[f"{scope}/disks"] = {"items": [dict(owned, name="remaining-disk")]}
    elif failure == "replacement":
        owned["id"] = "999"
    elif failure == "pending":
        docs[f"{scope}/operations"] = {
            "items": [{"status": "PENDING", "targetLink": f"{scope}/instances/prep-{attempt.hex}"}]
        }
    observer = GCEPreparationReadback(grant, Reader(docs))
    retained = {"image_ref": built["image_ref"], "image_id": built["image_id"]}
    if failure:
        with pytest.raises(ValueError):
            observer.verify_cleanup(operation, [attempt], retained_image=retained)
    else:
        observer.verify_cleanup(operation, [attempt], retained_image=retained)


def test_build_receipt_needs_three_actual_provider_reads():
    operation, attempt, grant, documents, built = fixture()
    reader = Reader(documents)
    GCEPreparationReadback(grant, reader).verify_build(operation, attempt, built)
    assert set(reader.reads) == set(documents)


@pytest.mark.parametrize("failure", ["image-id", "source-disk", "source-image", "ownership", "running", "credential"])
def test_changed_or_unisolated_provider_resources_reject_builder_claims(failure):
    operation, attempt, grant, documents, built = fixture()
    image, disk, guest = documents.values()
    if failure == "image-id":
        image["id"] = "999"
    elif failure == "source-disk":
        image["sourceDiskId"] = "999"
    elif failure == "source-image":
        disk["sourceImageId"] = "999"
    elif failure == "ownership":
        guest["labels"] = {"shifter-preparation": uuid4().hex}
    elif failure == "running":
        guest["status"] = "RUNNING"
    else:
        guest["serviceAccounts"] = [{"email": "foreign@example.invalid"}]
    with pytest.raises(ValueError):
        GCEPreparationReadback(grant, Reader(documents)).verify_build(operation, attempt, built)


def scan_fixture():
    operation, attempt, grant, _, _ = fixture()
    name = "prep-" + attempt.hex
    scope = f"projects/{grant.project_id}/zones/{grant.zone}"
    labels = {"shifter-preparation": operation.hex, "preparation-attempt": attempt.hex}
    documents = {
        f"{scope}/disks/{name}-data": {"id": "666", "sourceImageId": "555", "sizeGb": "10", "labels": labels},
        f"{scope}/disks/{name}-scan": {"id": "777", "sourceImageId": grant.scanner_image_id, "labels": labels},
        f"{scope}/instances/{name}-scan": {
            "status": "TERMINATED",
            "labels": labels,
            "serviceAccounts": [],
            "networkInterfaces": [{"subnetwork": grant.subnetwork}],
            "disks": [
                {"source": f"{scope}/disks/{name}-scan", "boot": True},
                {"source": f"{scope}/disks/{name}-data", "boot": False, "mode": "READ_ONLY"},
            ],
        },
    }
    receipt = {
        "input_id": "base",
        "image_ref": "projects/test-project/global/images/base",
        "image_id": "555",
        "disk_id": "666",
        "raw_disk_digest": "sha256:" + "1" * 64,
        "size_bytes": 10737418240,
    }
    return operation, attempt, grant, documents, receipt


@pytest.mark.parametrize("failure", [None, "writable", "source", "scanner", "size"])
def test_independent_scan_requires_read_only_disk_and_approved_scanner(failure):
    operation, attempt, grant, documents, receipt = scan_fixture()
    data, scanner, guest = documents.values()
    if failure == "writable":
        guest["disks"][1]["mode"] = "READ_WRITE"
    elif failure == "source":
        data["sourceImageId"] = "999"
    elif failure == "scanner":
        scanner["sourceImageId"] = "999"
    elif failure == "size":
        data["sizeGb"] = "20"
    reader = GCEPreparationReadback(grant, Reader(documents))
    if failure:
        with pytest.raises(ValueError):
            reader.verify_inputs(operation, attempt, {"observations": [receipt]})
    else:
        reader.verify_inputs(operation, attempt, {"observations": [receipt]})


@pytest.mark.parametrize("failure", [None, "boot-source", "live-probe"])
def test_output_readback_requires_fresh_boot_and_completed_independent_probe(failure):
    operation, attempt, grant, documents, receipt = scan_fixture()
    receipt.pop("input_id")
    receipt.update(boot_observed=True, sanitized=True, constraint_values={})
    scope = f"projects/{grant.project_id}/zones/{grant.zone}"
    labels = {"shifter-preparation": operation.hex, "preparation-attempt": attempt.hex}
    for suffix, image_id, status in (
        ("boot", receipt["image_id"], "RUNNING"),
        ("probe", grant.scanner_image_id, "TERMINATED"),
    ):
        name = f"prep-{attempt.hex}-{suffix}"
        documents[f"{scope}/disks/{name}"] = {"labels": labels, "sourceImageId": image_id}
        documents[f"{scope}/instances/{name}"] = {
            "labels": labels,
            "status": status,
            "serviceAccounts": [],
            "networkInterfaces": [{"subnetwork": grant.subnetwork}],
            "disks": [{"source": f"{scope}/disks/{name}", "boot": True}],
        }
    if failure == "boot-source":
        documents[f"{scope}/disks/prep-{attempt.hex}-boot"]["sourceImageId"] = "999"
    elif failure == "live-probe":
        documents[f"{scope}/instances/prep-{attempt.hex}-probe"]["status"] = "RUNNING"
    reader = GCEPreparationReadback(grant, Reader(documents))
    if failure:
        with pytest.raises(ValueError):
            reader.verify_output(operation, attempt, receipt)
    else:
        reader.verify_output(operation, attempt, receipt)
