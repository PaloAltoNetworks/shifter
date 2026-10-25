"""The isolated acquisition Job stores a verified artifact and reports one result line."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from shared.feature_artifacts.job import (
    RESULT_MARKER,
    AcquisitionResult,
    acquire,
    content_key,
    main,
    parse_result,
)
from shared.feature_artifacts.npm import FetchedFile, NpmAcquisitionError
from shared.raes.content_delivery import normalized_storage_key

BINARY = b"\x7fELF" + b"\x01" * 2048
SHA = hashlib.sha256(BINARY).hexdigest()
PREFIX = "raes/content-delivery"


class MemoryStore:
    """In-memory object store at the cloud boundary."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, path: Path, key: str) -> None:
        self.objects[key] = path.read_bytes()


@pytest.fixture
def upstream():
    """Controllable upstream fetch; records the package it was asked for."""

    class Upstream:
        error: Exception | None = None
        requested: list[tuple[str, str, str]] = []

        def __call__(self, package: str, version: str, member: str, workdir: Path) -> FetchedFile:
            self.requested.append((package, version, member))
            if self.error is not None:
                raise self.error
            path = workdir / "artifact"
            path.write_bytes(BINARY)
            return FetchedFile(path, SHA, len(BINARY), f"npm:{package}@{version}", "sha512-abc")

    return Upstream()


def test_job_stores_under_the_delivery_key_and_reports_identity(upstream):
    store = MemoryStore()
    result = acquire("claude-code", "2.1.289", "linux-x64-glibc", store=store, prefix=PREFIX, fetch=upstream)

    assert result.ok
    assert result.storage_key == content_key(PREFIX, SHA) == normalized_storage_key(PREFIX, SHA)
    assert store.objects[result.storage_key] == BINARY
    assert (result.sha256, result.byte_count) == (SHA, len(BINARY))
    assert upstream.requested == [("@anthropic-ai/claude-code-linux-x64", "2.1.289", "package/claude")]

    again = acquire("claude-code", "2.1.289", "linux-x64-glibc", store=store, prefix=PREFIX, fetch=upstream)
    assert again == result
    assert list(store.objects) == [result.storage_key]  # re-acquisition lands on the same content key


@pytest.mark.parametrize(
    ("source", "version", "platform", "error", "reason"),
    [
        ("nope", "2.1.289", "linux-x64-glibc", None, "no platform acquisition recipe"),
        ("claude-code", "*", "linux-x64-glibc", None, "resolved exact version"),
        ("claude-code", "2.1.289", "windows-x64", None, "not available for platform"),
        (
            "claude-code",
            "2.1.289",
            "linux-x64-glibc",
            NpmAcquisitionError("npm tarball integrity mismatch"),
            "integrity",
        ),
        ("claude-code", "2.1.289", "linux-x64-glibc", OSError("disk full"), "acquisition failed (OSError)"),
    ],
    ids=["unknown-source", "open-version", "unsupported-platform", "integrity", "unexpected-error"],
)
def test_job_reports_failures_without_storing(upstream, source, version, platform, error, reason):
    upstream.error = error
    store = MemoryStore()
    result = acquire(source, version, platform, store=store, prefix=PREFIX, fetch=upstream)
    assert not result.ok
    assert reason in result.reason
    assert not store.objects


def test_result_line_round_trips_and_malformed_output_is_rejected():
    result = AcquisitionResult(
        ok=True, storage_key="k", sha256=SHA, byte_count=3, upstream_ref="r", upstream_integrity="i"
    )
    log = "noise\n" + RESULT_MARKER + json.dumps(asdict(result)) + "\n"
    assert parse_result(log) == result
    assert parse_result("no result here") is None
    assert parse_result(RESULT_MARKER + "{not json") is None
    assert parse_result(RESULT_MARKER + json.dumps({"ok": True})) is None


def test_main_requires_three_arguments_and_refuses_unsupported_providers(monkeypatch, capsys):
    assert main(["claude-code"]) == 2
    monkeypatch.setenv("CLOUD_PROVIDER", "azure")
    # A reported failure still exits 0 so the launcher can read its reason.
    assert main(["claude-code", "2.1.289", "linux-x64-glibc"]) == 0
    reported = parse_result(capsys.readouterr().out)
    assert reported is not None
    assert not reported.ok
    assert "not supported" in reported.reason


class _FakeGcsBucket:
    """GCS bucket boundary honoring if_generation_match=0 (create-only)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.preconditions: list[object] = []

    def blob(self, key: str):
        bucket = self

        class _Blob:
            def upload_from_filename(self, filename, content_type, if_generation_match):
                from google.api_core.exceptions import PreconditionFailed

                bucket.preconditions.append(if_generation_match)
                if key in bucket.objects:
                    raise PreconditionFailed("exists")
                bucket.objects[key] = Path(filename).read_bytes()

        return _Blob()


def test_gcs_store_writes_create_only_and_treats_an_existing_object_as_stored(upstream):
    from shared.feature_artifacts.job import GcsArtifactStore

    bucket = _FakeGcsBucket()
    store = GcsArtifactStore("assets", client=type("Client", (), {"bucket": lambda self, name: bucket})())

    first = acquire("claude-code", "2.1.289", "linux-x64-glibc", store=store, prefix=PREFIX, fetch=upstream)
    again = acquire("claude-code", "2.1.289", "linux-x64-glibc", store=store, prefix=PREFIX, fetch=upstream)

    assert first.ok and again == first
    assert bucket.objects == {first.storage_key: BINARY}
    assert bucket.preconditions == [0, 0]  # never an overwrite
