"""Feature artifacts are claimed once, finalized by the launcher with verification, and fail per range."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID

import pytest
from django.db import transaction
from django.utils import timezone

from engine.models import AcquiredFeatureArtifact
from engine.services import reconcile_feature_artifact_acquisitions
from engine.services._feature_artifacts import (
    ArtifactRequest,
    FeatureArtifactUnavailableError,
    StorageTarget,
    await_ready,
    finalize_attempt,
    request_acquisition,
)
from shared.cloud.exceptions import CloudStorageError, CloudTaskError
from shared.feature_artifacts.job import RESULT_MARKER, AcquisitionResult
from shared.feature_artifacts.recipes import OPEN_VERSION, RecipeError

State = AcquiredFeatureArtifact.State
BINARY = b"claude-binary" * 1000
SHA = hashlib.sha256(BINARY).hexdigest()
PREFIX = "raes/content-delivery"
KEY = f"{PREFIX}/{SHA[:2]}/{SHA}"
IMAGE = "registry.example/platform@sha256:" + "a" * 64
REQUEST = ArtifactRequest(source_name="claude-code", version=OPEN_VERSION, platform="linux-x64-glibc")
GOOD = AcquisitionResult(
    ok=True, storage_key=KEY, sha256=SHA, byte_count=len(BINARY), upstream_ref="npm:x", upstream_integrity="sha512-x"
)


class FakeObjectStorage:
    """In-memory object storage at the cloud boundary."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.error: Exception | None = None

    def object_exists(self, bucket: str, key: str) -> bool:
        if self.error is not None:
            raise self.error
        return key in self.objects

    def head_object(self, bucket: str, key: str) -> dict:
        return {"content_length": len(self.objects[key]), "etag": "x"}


class FakeTaskRunner:
    """Kubernetes task-runner boundary: tracks Jobs and returns scripted outputs."""

    def __init__(self) -> None:
        self.launched: list[str] = []
        self.deleted: list[str] = []
        self.outputs: dict[str, list[object]] = {}

    def run_task(self, **kwargs) -> str:
        identity = kwargs["task_identity"]
        if identity not in self.launched:
            self.launched.append(identity)
        return identity

    def get_task_output(self, cluster: str, task_ref: str, expected: dict) -> bytes | None:
        script = self.outputs.get(expected["task_identity"], [None])
        step = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(step, Exception):
            raise step
        return step

    def delete_completed_task(self, cluster: str, task_ref: str, expected: dict) -> None:
        self.deleted.append(expected["task_identity"])


def _line(result: AcquisitionResult) -> bytes:
    return (RESULT_MARKER + json.dumps(asdict(result)) + "\n").encode()


@pytest.fixture
def env():
    storage = FakeObjectStorage()
    return type(
        "Env",
        (),
        {
            "storage": storage,
            "target": StorageTarget(storage=storage, bucket="assets", prefix=PREFIX),
            "runner": FakeTaskRunner(),
        },
    )()


def _attempt() -> tuple[UUID, UUID]:
    row = AcquiredFeatureArtifact.objects.get()
    return row.id, row.attempt_id


@pytest.mark.django_db
def test_requests_share_one_claim_and_a_verified_ready_artifact_is_reused(env):
    first = request_acquisition(REQUEST, target=env.target)
    second = request_acquisition(REQUEST, target=env.target)
    assert first.state == second.state == State.ACQUIRING
    assert first.attempt_id == second.attempt_id
    assert first.resolved_version == "2.1.289"

    env.storage.objects[KEY] = BINARY
    assert finalize_attempt(*_attempt(), GOOD, target=env.target)
    ready = AcquiredFeatureArtifact.objects.get()
    assert (ready.state, ready.storage_key, ready.byte_count) == (State.READY, KEY, len(BINARY))

    again = request_acquisition(REQUEST, target=env.target)
    assert again.state == State.READY
    assert again.attempt_id == first.attempt_id  # reused, never re-claimed

    env.storage.objects.clear()  # the stored object vanished
    reclaimed = request_acquisition(REQUEST, target=env.target)
    assert reclaimed.state == State.ACQUIRING
    assert reclaimed.attempt_id != first.attempt_id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "lie",
    [
        {"storage_key": "raes/content-delivery/00/elsewhere"},
        {"byte_count": len(BINARY) + 1},
        {"sha256": "f" * 64},
    ],
    ids=["wrong-key", "wrong-size", "wrong-digest"],
)
def test_finalize_rejects_results_the_stored_object_does_not_back(env, lie):
    request_acquisition(REQUEST, target=env.target)
    env.storage.objects[KEY] = BINARY
    claimed = AcquisitionResult(**{**asdict(GOOD), **lie})

    finalize_attempt(*_attempt(), claimed, target=env.target)

    row = AcquiredFeatureArtifact.objects.get()
    assert row.state == State.FAILED
    assert row.failure_reason == "acquired object failed independent verification"


@pytest.mark.django_db
def test_failure_backs_off_then_a_later_request_retries_and_stale_attempts_are_fenced(env):
    request_acquisition(REQUEST, target=env.target)
    row_id, first = _attempt()
    finalize_attempt(
        row_id, first, AcquisitionResult(ok=False, reason="npm package version not found"), target=env.target
    )
    failed = AcquiredFeatureArtifact.objects.get()
    assert (failed.state, failed.failure_reason) == (State.FAILED, "npm package version not found")

    assert request_acquisition(REQUEST, target=env.target).state == State.FAILED  # within backoff
    AcquiredFeatureArtifact.objects.update(retry_not_before=timezone.now() - timedelta(seconds=1))
    retry = request_acquisition(REQUEST, target=env.target)
    assert retry.state == State.ACQUIRING
    assert retry.attempt_id != first

    env.storage.objects[KEY] = BINARY
    assert not finalize_attempt(row_id, first, GOOD, target=env.target)  # stale attempt cannot write
    assert AcquiredFeatureArtifact.objects.get().state == State.ACQUIRING


@pytest.mark.django_db
def test_storage_errors_never_masquerade_as_a_missing_object(env):
    request_acquisition(REQUEST, target=env.target)
    env.storage.objects[KEY] = BINARY
    finalize_attempt(*_attempt(), GOOD, target=env.target)
    ready_attempt = AcquiredFeatureArtifact.objects.get().attempt_id

    env.storage.error = CloudStorageError("Failed to check S3 object: AccessDenied")
    with pytest.raises(CloudStorageError):
        request_acquisition(REQUEST, target=env.target)

    row = AcquiredFeatureArtifact.objects.get()
    assert (row.state, row.attempt_id) == (State.READY, ready_attempt)  # not reclaimed, nothing re-downloaded


@pytest.mark.django_db
def test_unknown_sources_fail_closed_without_creating_rows(env):
    with pytest.raises(RecipeError):
        request_acquisition(ArtifactRequest("arbitrary-url-fetch", OPEN_VERSION, "linux-x64-glibc"), target=env.target)
    assert not AcquiredFeatureArtifact.objects.exists()


@pytest.mark.django_db
class TestLauncherReconcile:
    def test_launches_once_observes_and_finalizes_with_cleanup(self, env):
        request_acquisition(REQUEST, target=env.target)
        _row, attempt = _attempt()
        env.storage.objects[KEY] = BINARY
        env.runner.outputs[str(attempt)] = [None, _line(GOOD)]

        assert reconcile_feature_artifact_acquisitions(image=IMAGE, target=env.target, runner=env.runner) == 1
        assert AcquiredFeatureArtifact.objects.get().state == State.ACQUIRING  # Job still running
        reconcile_feature_artifact_acquisitions(image=IMAGE, target=env.target, runner=env.runner)

        assert AcquiredFeatureArtifact.objects.get().state == State.READY
        assert env.runner.launched == [str(attempt)]
        assert env.runner.deleted == [str(attempt)]

    def test_job_that_fails_without_a_result_fails_the_attempt(self, env):
        request_acquisition(REQUEST, target=env.target)
        _row, attempt = _attempt()
        env.runner.outputs[str(attempt)] = [CloudTaskError("Task execution failed")]

        reconcile_feature_artifact_acquisitions(image=IMAGE, target=env.target, runner=env.runner)

        row = AcquiredFeatureArtifact.objects.get()
        assert (row.state, row.failure_reason) == (State.FAILED, "acquisition Job failed without a result")

    def test_disabled_without_an_image_and_errors_are_isolated_per_attempt(self, env):
        request_acquisition(REQUEST, target=env.target)
        assert reconcile_feature_artifact_acquisitions(image="", target=env.target, runner=env.runner) == 0
        assert not env.runner.launched

        _row, attempt = _attempt()
        env.runner.outputs[str(attempt)] = [CloudTaskError("Task output is unavailable")]
        reconcile_feature_artifact_acquisitions(image=IMAGE, target=env.target, runner=env.runner)
        assert AcquiredFeatureArtifact.objects.get().state == State.ACQUIRING  # retried next tick


@pytest.mark.django_db(transaction=True)
class TestLaunchGate:
    def _finish_in_background(self, env, result: AcquisitionResult) -> threading.Timer:
        def finish() -> None:
            row_id, attempt = _attempt()
            env.storage.objects[KEY] = BINARY
            finalize_attempt(row_id, attempt, result, target=env.target)

        timer = threading.Timer(0.2, finish)
        timer.start()
        return timer

    def test_returns_once_the_launcher_finishes_the_shared_attempt(self, env):
        timer = self._finish_in_background(env, GOOD)
        row = await_ready(REQUEST, target=env.target, timeout=timedelta(seconds=10), poll=timedelta(seconds=0.05))
        timer.join()
        assert row.state == State.READY

    def test_failed_attempt_fails_only_the_waiting_range(self, env):
        timer = self._finish_in_background(env, AcquisitionResult(ok=False, reason="npm tarball integrity mismatch"))
        with pytest.raises(FeatureArtifactUnavailableError, match="integrity mismatch"):
            await_ready(REQUEST, target=env.target, timeout=timedelta(seconds=10), poll=timedelta(seconds=0.05))
        timer.join()

    def test_unknown_recipe_timeout_and_open_transactions_fail_the_range(self, env):
        with pytest.raises(FeatureArtifactUnavailableError, match="no platform acquisition recipe"):
            await_ready(
                ArtifactRequest("nope", OPEN_VERSION, "linux-x64-glibc"),
                target=env.target,
                timeout=timedelta(seconds=1),
            )
        with pytest.raises(FeatureArtifactUnavailableError, match="did not complete in time"):
            await_ready(REQUEST, target=env.target, timeout=timedelta(0), sleep=lambda _seconds: None)
        with transaction.atomic(), pytest.raises(RuntimeError, match="inside a database transaction"):
            await_ready(REQUEST, target=env.target, timeout=timedelta(seconds=1))

    def test_unverifiable_storage_fails_the_range(self, env):
        request_acquisition(REQUEST, target=env.target)
        env.storage.objects[KEY] = BINARY
        finalize_attempt(*_attempt(), GOOD, target=env.target)
        env.storage.error = CloudStorageError("Failed to check S3 object: SlowDown")

        with pytest.raises(FeatureArtifactUnavailableError, match="could not be verified"):
            await_ready(REQUEST, target=env.target, timeout=timedelta(seconds=1))
