"""Cleanup is scoped and removes guests before attached disks and images."""

from uuid import uuid4

import pytest

from preparation.cleanup import cleanup_operation


class Compute:
    project = "test-project"
    zone = "us-central1-a"

    def __init__(self, lingering=False):
        self.deleted = []
        self.lingering = lingering
        self.settled = False

    def wait_for_attempt_operations(self, attempts):
        self.settled = True

    def list_owned(self, path, operation_id):
        if not self.settled:
            return []  # The owned create has not completed yet.
        if any(item[0].startswith(path + "/") for item in self.deleted) and not self.lingering:
            return []
        return [{"name": "prep-owned", "id": "123"}]

    def delete_owned(self, path, resource_id, operation_id):
        self.deleted.append((path, resource_id, operation_id))


def test_cleanup_removes_only_enumerated_owned_resources_in_dependency_order():
    api = Compute()
    operation_id = uuid4()
    assert cleanup_operation(api, operation_id, [uuid4()]) == {"resources_remaining": []}
    assert [item[0].split("/")[-2] for item in api.deleted] == ["instances", "disks", "images"]
    assert all(item[2] == operation_id for item in api.deleted)


def test_cleanup_does_not_claim_success_when_provider_resources_remain():
    with pytest.raises(RuntimeError, match="resources remain"):
        cleanup_operation(Compute(lingering=True), uuid4(), [uuid4()])


def test_cleanup_preserves_only_the_exact_admitted_image():
    api = Compute()
    retained = {"image_ref": "projects/test-project/global/images/prep-owned", "image_id": "123"}
    assert cleanup_operation(api, uuid4(), [uuid4()], retained_image=retained) == {"resources_remaining": []}
    assert [item[0].split("/")[-2] for item in api.deleted] == ["instances", "disks"]


def test_changed_identity_under_admitted_name_is_not_silently_preserved():
    retained = {"image_ref": "projects/test-project/global/images/prep-owned", "image_id": "999"}
    with pytest.raises(ValueError, match="retained image identity"):
        cleanup_operation(Compute(), uuid4(), [uuid4()], retained_image=retained)
