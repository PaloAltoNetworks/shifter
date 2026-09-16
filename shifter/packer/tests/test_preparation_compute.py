"""GCE transport is bounded, scope checked, and refuses ambiguous foreign creates."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest


def module():
    spec = importlib.util.spec_from_file_location(
        "preparation_compute", Path(__file__).parents[1] / "preparation/compute.py"
    )
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.body = json.dumps(body).encode()

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def client(responses):
    session = Session(responses)
    return module().ComputeClient("test-project", "us-central1-a", 60, session=session), session


def test_create_waits_for_its_own_operation_without_following_provider_urls():
    compute, session = client(
        [
            Response(200, {"name": "operation-1", "status": "PENDING", "selfLink": "https://foreign.invalid/"}),
            Response(200, {"status": "DONE"}),
        ]
    )
    compute.create("projects/test-project/zones/us-central1-a/instances", {"name": "prep-example"}, str(uuid4()))
    assert (
        session.calls[1][1]
        == "https://compute.googleapis.com/compute/v1/projects/test-project/zones/us-central1-a/operations/operation-1"
    )
    assert all(call[2]["timeout"] <= 30 for call in session.calls)
    assert session.calls[0][2]["allow_redirects"] is False


@pytest.mark.parametrize(
    "path",
    [
        "projects/foreign-project/zones/us-central1-a/instances",
        "projects/test-project/zones/us-east1-a/instances",
        "https://foreign.invalid/instances",
        "projects/test-project/global/../images",
    ],
)
def test_foreign_or_escaping_mutation_is_rejected_before_transport(path):
    compute, session = client([])
    with pytest.raises(ValueError):
        compute.create(path, {"name": "prep-example"}, str(uuid4()))
    assert not session.calls


def test_provider_failures_never_echo_private_payloads():
    compute, _ = client([Response(403, {"error": {"message": "private input and credential details"}})])
    with pytest.raises(RuntimeError) as error:
        compute.get("projects/test-project/global/images/base")
    assert "private input" not in str(error.value)


def test_conflict_is_not_reported_as_success_without_owned_resource_readback():
    compute, _ = client(
        [Response(409, {}), Response(200, {"name": "prep-example", "labels": {"shifter-preparation": "foreign"}})]
    )
    with pytest.raises(ValueError):
        compute.create(
            "projects/test-project/global/images",
            {"name": "prep-example", "labels": {"shifter-preparation": "ours"}},
            str(uuid4()),
        )


def test_owned_image_retry_accepts_canonical_google_resource_link():
    body = {
        "name": "prep-example",
        "labels": {"shifter-preparation": "ours"},
        "sourceDisk": "projects/test-project/zones/us-central1-a/disks/prep-example",
    }
    observed = dict(body, sourceDisk="https://www.googleapis.com/compute/v1/" + body["sourceDisk"])
    compute, session = client([Response(409, {}), Response(200, observed)])
    compute.create("projects/test-project/global/images", body, str(uuid4()))
    assert len(session.calls) == 2


def test_scanner_receipt_is_bound_to_the_fresh_nonce_and_stopped_guest():
    import base64

    nonce = str(uuid4())
    evidence = {"raw_disk_digest": "sha256:" + "a" * 64, "size_bytes": 1024}
    encoded = base64.b64encode(json.dumps(evidence).encode()).decode()
    compute, _ = client(
        [
            Response(200, {"contents": f"SHIFTER_PREPARATION_OBSERVATION:{nonce}:{encoded}\n", "next": "100"}),
            Response(200, {"status": "TERMINATED"}),
        ]
    )
    result = compute.wait_for_observation("projects/test-project/zones/us-central1-a/instances/prep-scanner", nonce)
    assert result == evidence


def test_old_scanner_receipt_cannot_qualify_a_different_attempt():
    compute, _ = client(
        [
            Response(200, {"contents": f"SHIFTER_PREPARATION_OBSERVATION:{uuid4()}:e30=\n", "next": "100"}),
            Response(200, {"status": "TERMINATED"}),
        ]
    )
    with pytest.raises(RuntimeError):
        compute.wait_for_observation("projects/test-project/zones/us-central1-a/instances/prep-scanner", str(uuid4()))


def test_scanner_failure_is_a_closed_error_and_never_partial_success():
    import base64

    nonce = str(uuid4())
    encoded = base64.b64encode(json.dumps({"failure_code": "metadata_script_residue"}).encode()).decode()
    compute, _ = client(
        [
            Response(200, {"contents": f"SHIFTER_PREPARATION_OBSERVATION:{nonce}:{encoded}\n", "next": "100"}),
            Response(200, {"status": "TERMINATED"}),
        ]
    )
    with pytest.raises(RuntimeError, match="metadata_script_residue"):
        compute.wait_for_observation("projects/test-project/zones/us-central1-a/instances/prep-scanner", nonce)


def test_owned_scanner_disk_can_be_reused_after_an_ambiguous_create():
    body = {
        "name": "prep-data",
        "labels": {"shifter-preparation": "ours"},
        "sourceImage": "projects/test-project/global/images/candidate",
        "sizeGb": "10",
    }
    observed = dict(body, sourceImage="https://www.googleapis.com/compute/v1/" + body["sourceImage"])
    compute, _ = client([Response(409, {}), Response(200, observed)])
    compute.create("projects/test-project/zones/us-central1-a/disks", body, str(uuid4()))


def test_completed_guest_retry_retains_identity_after_private_metadata_was_erased():
    body = {
        "name": "prep-guest",
        "labels": {"shifter-preparation": "ours"},
        "machineType": "projects/test-project/zones/us-central1-a/machineTypes/e2-standard-2",
        "networkInterfaces": [{"subnetwork": "projects/test-project/regions/us-central1/subnetworks/preparation"}],
        "metadata": {"items": [{"key": "startup-script", "value": "trusted contained code"}]},
        "disks": [
            {"boot": True, "autoDelete": False, "initializeParams": {"diskName": "prep-guest"}},
            {
                "source": "projects/test-project/zones/us-central1-a/disks/prep-data",
                "mode": "READ_ONLY",
                "autoDelete": False,
            },
        ],
    }
    observed = dict(
        body,
        metadata={"items": []},
        status="TERMINATED",
        serviceAccounts=[],
        disks=[
            {
                "boot": True,
                "autoDelete": False,
                "source": "projects/test-project/zones/us-central1-a/disks/prep-guest",
                "mode": "READ_WRITE",
            },
            {
                "boot": False,
                "autoDelete": False,
                "source": "projects/test-project/zones/us-central1-a/disks/prep-data",
                "mode": "READ_ONLY",
            },
        ],
    )
    compute, _ = client([Response(409, {}), Response(200, observed)])
    compute.create("projects/test-project/zones/us-central1-a/instances", body, str(uuid4()))


def test_delete_requires_current_resource_id_and_operation_ownership():
    operation_id = uuid4()
    resource = {"id": "123", "labels": {"shifter-preparation": operation_id.hex}}
    compute, session = client([Response(200, resource), Response(200, {"name": "delete-1", "status": "DONE"})])
    compute.delete_owned("projects/test-project/global/images/prep-example", "123", operation_id)
    assert session.calls[-1][0] == "DELETE"
    compute, session = client([Response(200, dict(resource, id="456"))])
    with pytest.raises(ValueError):
        compute.delete_owned("projects/test-project/global/images/prep-example", "123", operation_id)
    assert all(call[0] != "DELETE" for call in session.calls)


def test_owned_listing_checks_every_page_and_filters_exact_operation_labels():
    operation_id = uuid4()
    owned = {"name": "prep-example", "id": "123", "labels": {"shifter-preparation": operation_id.hex}}
    compute, session = client(
        [
            Response(200, {"items": [{"name": "foreign", "labels": {}}], "nextPageToken": "page2"}),
            Response(200, {"items": [owned]}),
        ]
    )
    assert compute.list_owned("projects/test-project/global/images", operation_id) == [owned]
    assert session.calls[-1][2]["params"]["pageToken"] == "page2"


def test_owned_delete_is_idempotent_only_for_not_found():
    compute, session = client([Response(404, {})])
    compute.delete_owned("projects/test-project/global/images/prep-example", "123", uuid4())
    assert len(session.calls) == 1


def test_scanner_ready_marker_does_not_require_stopping_the_guest():
    nonce = str(uuid4())
    compute, _ = client(
        [
            Response(200, {"contents": f"SHIFTER_PREPARATION_READY:{nonce}\n", "next": "100"}),
            Response(200, {"status": "RUNNING"}),
        ]
    )
    compute.wait_for_ready("projects/test-project/zones/us-central1-a/instances/prep-scanner", nonce)


def test_candidate_attachment_is_always_read_only_and_waits_for_operation():
    compute, session = client(
        [Response(200, {"disks": [{"boot": True}]}), Response(200, {"name": "attach-1", "status": "DONE"})]
    )
    compute.attach_readonly(
        "projects/test-project/zones/us-central1-a/instances/prep-scanner",
        "projects/test-project/zones/us-central1-a/disks/prep-data",
        str(uuid4()),
    )
    assert session.calls[1][1].endswith("/attachDisk")
    assert session.calls[1][2]["json"]["mode"] == "READ_ONLY"


@pytest.mark.parametrize("mode", ["READ_ONLY", "READ_WRITE"])
def test_attachment_retry_observes_exact_disk_without_attaching_twice(mode):
    disk = "projects/test-project/zones/us-central1-a/disks/prep-data"
    compute, session = client(
        [
            Response(
                200,
                {
                    "disks": [
                        {"boot": True},
                        {
                            "source": disk,
                            "mode": mode,
                            "boot": False,
                            "autoDelete": False,
                            "deviceName": "shifter-candidate",
                        },
                    ]
                },
            )
        ]
    )
    if mode == "READ_ONLY":
        compute.attach_readonly("projects/test-project/zones/us-central1-a/instances/prep-scanner", disk, str(uuid4()))
    else:
        with pytest.raises(ValueError):
            compute.attach_readonly(
                "projects/test-project/zones/us-central1-a/instances/prep-scanner", disk, str(uuid4())
            )
    assert len(session.calls) == 1


@pytest.mark.parametrize("foreign", [False, True])
def test_scanner_create_retry_accepts_only_its_exact_hot_attached_candidate(foreign):
    attempt = uuid4()
    scope = "projects/test-project/zones/us-central1-a"
    desired = {
        "name": f"prep-{attempt.hex}-scan",
        "labels": {"preparation-attempt": attempt.hex},
        "machineType": scope + "/machineTypes/e2-standard-2",
        "disks": [
            {"boot": True, "autoDelete": False, "initializeParams": {"diskName": f"prep-{attempt.hex}-scan"}},
        ],
    }
    disks = [
        {"boot": True, "autoDelete": False, "source": scope + f"/disks/prep-{attempt.hex}-scan"},
        {
            "boot": False,
            "autoDelete": False,
            "mode": "READ_ONLY",
            "deviceName": "shifter-candidate",
            "source": scope + f"/disks/prep-{uuid4().hex if foreign else attempt.hex}-data",
        },
    ]
    assert module()._same_guest_disks(disks, desired) is not foreign


def test_cleanup_waits_for_owned_pending_creates_and_ignores_other_work():
    attempt = uuid4()
    compute, session = client(
        [
            Response(
                200,
                {
                    "items": [
                        {
                            "name": "ours",
                            "status": "PENDING",
                            "targetLink": "https://www.googleapis.com/compute/v1/projects/test-project/zones/us-central1-a/instances/prep-"
                            + attempt.hex,
                        },
                        {
                            "name": "unrelated",
                            "status": "PENDING",
                            "targetLink": "projects/test-project/zones/us-central1-a/instances/unrelated-workload",
                        },
                    ]
                },
            ),
            Response(200, {"status": "DONE", "error": {"errors": [{"code": "RESOURCE_NOT_READY"}]}}),
            Response(200, {"items": []}),
        ]
    )
    compute.wait_for_attempt_operations([attempt])
    assert any(call[1].endswith("/operations/ours") for call in session.calls)
    assert not any(call[1].endswith("/operations/unrelated") for call in session.calls)


def test_completed_receipt_survives_serial_endpoint_closing_during_shutdown(monkeypatch):
    import base64

    nonce = str(uuid4())
    evidence = {"raw_disk_digest": "sha256:" + "a" * 64, "size_bytes": 1024}
    encoded = base64.b64encode(json.dumps(evidence).encode()).decode()
    compute, _ = client(
        [
            Response(200, {"contents": f"SHIFTER_PREPARATION_OBSERVATION:{nonce}:{encoded}\n", "next": "100"}),
            Response(200, {"status": "STOPPING"}),
            Response(400, {"error": {"message": "serial endpoint no longer available"}}),
            Response(200, {"status": "TERMINATED"}),
        ]
    )
    monkeypatch.setattr(compute, "_pause", lambda: None)
    assert (
        compute.wait_for_observation("projects/test-project/zones/us-central1-a/instances/prep-scanner", nonce)
        == evidence
    )
