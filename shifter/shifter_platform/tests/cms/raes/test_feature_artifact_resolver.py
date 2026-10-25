"""Unprojected feature sources resolve to recipe-acquired artifacts or fail this range."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from cms.raes.feature_artifacts import feature_artifact_resolver
from engine.models import AcquiredFeatureArtifact
from engine.services._feature_artifacts import StorageTarget
from shared.raes.content_delivery import ContentDeliveryError

SHA = hashlib.sha256(b"claude").hexdigest()
KEY = f"raes/content-delivery/{SHA[:2]}/{SHA}"


class _Storage:
    def __init__(self, objects: dict[str, int]) -> None:
        self.objects = objects

    def object_exists(self, bucket: str, key: str) -> bool:
        return key in self.objects

    def head_object(self, bucket: str, key: str) -> dict:
        return {"content_length": self.objects[key], "etag": "x"}


def _plan(*, os_family: str = "linux", requirement: dict | None = None) -> dict:
    source: dict = {"name": "claude-code", "version": "*"}
    if requirement is not None:
        source["artifact_requirement"] = requirement
    return {
        "resources": {
            "node.attacker": {"resource_type": "node", "payload": {"os_family": os_family}},
            "feature.claude": {
                "resource_type": "feature-binding",
                "payload": {
                    "node_address": "node.attacker",
                    "spec": {"template": {"type": "artifact", "source": source}},
                },
            },
        }
    }


def _ref(feature_type: str = "artifact") -> SimpleNamespace:
    return SimpleNamespace(
        address="feature.claude",
        source_name="claude-code",
        source_version="*",
        feature_type=feature_type,
        target_address="node.attacker",
    )


def _ready_row() -> AcquiredFeatureArtifact:
    return AcquiredFeatureArtifact.objects.create(
        source_name="claude-code",
        resolved_version="2.1.289",
        platform="linux-x64-glibc",
        recipe_id="npm-binary/claude-code/v1",
        payload_kind="file",
        install_policy="executable",
        state=AcquiredFeatureArtifact.State.READY,
        storage_key=KEY,
        sha256=SHA,
        byte_count=6,
        acquired_at=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_ready_artifact_becomes_a_byte_free_feature_binding():
    _ready_row()
    target = StorageTarget(storage=_Storage({KEY: 6}), bucket="assets", prefix="raes/content-delivery")

    binding = feature_artifact_resolver(_plan(), target=target)(_ref())

    assert (binding.resource_type, binding.resource_address) == ("feature-binding", "feature.claude")
    assert (binding.sha256, binding.storage_key, binding.byte_count) == (SHA, KEY, 6)
    assert (binding.payload_kind, binding.install_policy) == ("file", "executable")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("plan", "ref", "message"),
    [
        (_plan(), _ref("configuration"), "only artifact features"),
        (_plan(os_family="windows"), _ref(), "not acquirable for 'windows'"),
        (_plan(requirement={"explicitness": "constrained", "permitted_routes": []}), _ref(), "constrained"),
        (
            _plan(
                requirement={
                    "explicitness": "open",
                    "permitted_routes": [{"mechanism": {"mechanism": "dynamic-composition"}, "acquisition": "none"}],
                }
            ),
            _ref(),
            "acquisition not permitted",
        ),
    ],
    ids=["configuration-feature", "windows-node", "constrained", "routes-without-pull"],
)
def test_unsatisfiable_requests_fail_materialization(plan, ref, message):
    target = StorageTarget(storage=_Storage({}), bucket="assets", prefix="raes/content-delivery")
    with pytest.raises(ContentDeliveryError, match=message):
        feature_artifact_resolver(plan, target=target)(ref)


@pytest.mark.django_db(transaction=True)
def test_unavailable_artifact_fails_this_range_with_its_reason(settings):
    settings.RAES_FEATURE_ARTIFACT_WAIT_SECONDS = 0
    target = StorageTarget(storage=_Storage({}), bucket="assets", prefix="raes/content-delivery")
    with pytest.raises(ContentDeliveryError, match="feature artifact 'claude-code' is unavailable"):
        feature_artifact_resolver(_plan(), target=target)(_ref())
    assert AcquiredFeatureArtifact.objects.get().state == AcquiredFeatureArtifact.State.ACQUIRING
    assert timedelta(0) <= timezone.now() - AcquiredFeatureArtifact.objects.get().attempt_started_at
