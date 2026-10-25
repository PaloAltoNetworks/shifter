"""Registered packs' declared feature artifacts are acquired before any range needs them (#2463)."""

from __future__ import annotations

from io import StringIO

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from cms.raes.feature_artifacts import request_pack_feature_artifacts
from cms.scenarios.inbox import SHIPPED_INBOX_MANIFEST, register_inbox_packs
from engine.models import AcquiredFeatureArtifact
from engine.services._feature_artifacts import StorageTarget

IMAGE = "registry.example/platform@sha256:" + "a" * 64

pytestmark = pytest.mark.django_db


class _Storage:
    def object_exists(self, bucket: str, key: str) -> bool:
        return False


def _register_inbox(monkeypatch) -> None:
    # The shipped packs resolve under the image app root; in a checkout that is
    # the platform source root.
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(SHIPPED_INBOX_MANIFEST.parents[3]))
    actor = get_user_model().objects.create_user(
        username="feature-artifacts@example.com", email="feature-artifacts@example.com", is_staff=True
    )
    register_inbox_packs(actor=actor)


@pytest.fixture
def registered_inbox(monkeypatch):
    monkeypatch.delenv("FEATURE_ARTIFACT_JOB_IMAGE", raising=False)
    _register_inbox(monkeypatch)


def test_registration_without_an_acquisition_image_requests_nothing(registered_inbox):
    assert request_pack_feature_artifacts("smoke-linux-aws") == 0
    assert not AcquiredFeatureArtifact.objects.exists()


def test_base_aws_smoke_pack_claims_one_single_flight_claude_code_acquisition(registered_inbox, monkeypatch):
    monkeypatch.setenv("FEATURE_ARTIFACT_JOB_IMAGE", IMAGE)
    target = StorageTarget(storage=_Storage(), bucket="assets", prefix="raes/content-delivery")

    assert request_pack_feature_artifacts("smoke-linux-aws", target=target) == 1
    first = AcquiredFeatureArtifact.objects.get()
    # Version left open by the author: the platform's reviewed default is chosen.
    assert (first.source_name, first.resolved_version, first.platform, first.state) == (
        "claude-code",
        "2.1.289",
        "linux-x64-glibc",
        AcquiredFeatureArtifact.State.ACQUIRING,
    )

    assert request_pack_feature_artifacts("smoke-linux-aws", target=target) == 1
    assert AcquiredFeatureArtifact.objects.get().attempt_id == first.attempt_id  # joined, never re-claimed
    # The GCP base pack declares the same artifact: it joins the one attempt.
    assert request_pack_feature_artifacts("smoke-linux", target=target) == 1
    assert AcquiredFeatureArtifact.objects.get().attempt_id == first.attempt_id
    assert request_pack_feature_artifacts("not-registered", target=target) == 0


def test_bootstrap_command_requests_every_registered_packs_artifacts(registered_inbox, monkeypatch):
    out = StringIO()
    call_command("acquire_feature_artifacts", stdout=out)
    assert "not enabled" in out.getvalue()

    monkeypatch.setenv("FEATURE_ARTIFACT_JOB_IMAGE", IMAGE)
    out = StringIO()
    call_command("acquire_feature_artifacts", stdout=out)

    # Both base packs declare Claude Code; they share one inventory row.
    assert "requested 2 feature artifact acquisition(s)" in out.getvalue()
    assert AcquiredFeatureArtifact.objects.get().source_name == "claude-code"


def test_registering_a_pack_claims_its_artifacts_when_acquisition_is_enabled(
    monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setenv("FEATURE_ARTIFACT_JOB_IMAGE", IMAGE)

    with django_capture_on_commit_callbacks(execute=True):
        _register_inbox(monkeypatch)

    row = AcquiredFeatureArtifact.objects.get()
    assert (row.source_name, row.state) == ("claude-code", AcquiredFeatureArtifact.State.ACQUIRING)


def test_a_pack_revision_claims_artifacts_its_new_version_declares(
    registered_inbox, monkeypatch, django_capture_on_commit_callbacks
):
    from cms.models import RaesPackageSource
    from cms.scenarios.inbox import load_inbox_manifest

    shipped = next(r for r in load_inbox_manifest(SHIPPED_INBOX_MANIFEST) if r.scenario_id == "smoke-linux-aws")
    # The tenant still holds the prior revision the shipped entry upgrades from.
    RaesPackageSource.objects.filter(scenario_id="smoke-linux-aws").update(
        package_version="0.2.0", package_digest=shipped.expected_package_digest
    )
    monkeypatch.setenv("FEATURE_ARTIFACT_JOB_IMAGE", IMAGE)

    with django_capture_on_commit_callbacks(execute=True):
        register_inbox_packs(actor=get_user_model().objects.get(username="feature-artifacts@example.com"))

    assert RaesPackageSource.objects.get(scenario_id="smoke-linux-aws").package_version == "0.3.0"
    assert AcquiredFeatureArtifact.objects.get().source_name == "claude-code"
