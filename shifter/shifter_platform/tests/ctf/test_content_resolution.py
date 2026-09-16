"""Provider-neutral resolver tests for digest-pinned CTF content."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.test import override_settings

from ctf.exceptions import CTFValidationError
from ctf.services.content_resolution import resolve_scenario_ctf_content
from shared.cloud.exceptions import CloudStorageError, ObjectPreconditionError
from shared.schemas.ctf_content_reference import load_ctf_content_references_json


def _raw_bundle() -> bytes:
    return json.dumps(
        {
            "contract": "shifter-ctf-content/v1",
            "scenario_id": "scenario-one",
            "challenges": [
                {
                    "id": "challenge-one",
                    "name": "Challenge One",
                    "description": "Inspect the evidence.",
                    "category": "Module 1",
                    "points": 100,
                    "difficulty": "easy",
                    "order": 1,
                    "flags": [{"type": "static", "value": "TEST{not-a-secret}", "order": 0}],
                    "hints": [],
                    "prerequisites": [],
                }
            ],
        }
    ).encode()


def _references(raw: bytes, *, digest: str | None = None, scenario_id: str = "scenario-one"):
    expected = digest or f"sha256:{hashlib.sha256(raw).hexdigest()}"
    return load_ctf_content_references_json(
        json.dumps(
            {
                "contract": "shifter-ctf-content-references/v1",
                "references": [
                    {
                        "scenario_id": scenario_id,
                        "object_key": "ctf/content-bundles/aa/bundle.json",
                        "digest": expected,
                    }
                ],
            }
        ),
        prefix="ctf/content-bundles",
    )


def _storage(raw: bytes) -> Mock:
    storage = Mock()
    storage.head_object.return_value = {"content_length": len(raw), "etag": "etag-one", "generation": "7"}

    def download(_bucket, _key, destination, **_kwargs):
        Path(destination).write_bytes(raw)
        return {"content_length": len(raw), "etag": "etag-one", "generation": "7"}

    storage.download_object.side_effect = download
    return storage


@pytest.mark.django_db
def test_resolver_binds_identity_digest_and_bundle(monkeypatch) -> None:
    raw = _raw_bundle()
    storage = _storage(raw)
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: storage)
    with override_settings(
        CTF_CONTENT_BUCKET="private-content",
        CTF_CONTENT_MAX_BYTES=1024 * 1024,
        CTF_CONTENT_REFERENCES=_references(raw),
    ):
        resolved = resolve_scenario_ctf_content("scenario-one")

    assert resolved.bundle.challenges[0].source_id == "challenge-one"
    assert resolved.evidence.declared_digest.startswith("sha256:")
    storage.download_object.assert_called_once()
    assert storage.download_object.call_args.kwargs["expected_identity"]["generation"] == "7"


@pytest.mark.django_db
def test_digest_mismatch_fails_before_parse(monkeypatch) -> None:
    raw = _raw_bundle()
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: _storage(raw))
    with (
        override_settings(
            CTF_CONTENT_BUCKET="private-content",
            CTF_CONTENT_MAX_BYTES=1024 * 1024,
            CTF_CONTENT_REFERENCES=_references(raw, digest=f"sha256:{'0' * 64}"),
        ),
        pytest.raises(CTFValidationError) as error,
    ):
        resolve_scenario_ctf_content("scenario-one")
    assert error.value.code == "CTF_CONTENT_DIGEST_MISMATCH"


@pytest.mark.parametrize(
    ("storage_error", "expected_code"),
    [
        (ObjectPreconditionError("changed"), "CTF_CONTENT_CHANGED"),
        (CloudStorageError("unavailable"), "CTF_CONTENT_RESOLUTION_FAILED"),
    ],
)
def test_storage_failures_are_safely_classified(monkeypatch, storage_error, expected_code) -> None:
    raw = _raw_bundle()
    storage = _storage(raw)
    storage.download_object.side_effect = storage_error
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: storage)
    with (
        override_settings(
            CTF_CONTENT_BUCKET="private-content",
            CTF_CONTENT_MAX_BYTES=1024 * 1024,
            CTF_CONTENT_REFERENCES=_references(raw),
        ),
        pytest.raises(CTFValidationError) as error,
    ):
        resolve_scenario_ctf_content("scenario-one")
    assert error.value.code == expected_code


def test_declared_oversized_object_is_rejected_before_download(monkeypatch) -> None:
    raw = _raw_bundle()
    storage = _storage(raw)
    storage.head_object.return_value = {"content_length": len(raw) + 1}
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: storage)
    with (
        override_settings(
            CTF_CONTENT_BUCKET="private-content",
            CTF_CONTENT_MAX_BYTES=len(raw),
            CTF_CONTENT_REFERENCES=_references(raw),
        ),
        pytest.raises(CTFValidationError) as error,
    ):
        resolve_scenario_ctf_content("scenario-one")
    assert error.value.code == "CTF_CONTENT_TOO_LARGE"
    storage.download_object.assert_not_called()


def test_download_larger_than_declared_is_rejected(monkeypatch) -> None:
    raw = _raw_bundle()
    storage = _storage(raw)
    storage.head_object.return_value = {"content_length": 1}
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: storage)
    with (
        override_settings(
            CTF_CONTENT_BUCKET="private-content",
            CTF_CONTENT_MAX_BYTES=len(raw) - 1,
            CTF_CONTENT_REFERENCES=_references(raw),
        ),
        pytest.raises(CTFValidationError) as error,
    ):
        resolve_scenario_ctf_content("scenario-one")
    assert error.value.code == "CTF_CONTENT_TOO_LARGE"


def test_bundle_scenario_must_match_selected_reference(monkeypatch) -> None:
    raw = _raw_bundle()
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: _storage(raw))
    with (
        override_settings(
            CTF_CONTENT_BUCKET="private-content",
            CTF_CONTENT_MAX_BYTES=1024 * 1024,
            CTF_CONTENT_REFERENCES=_references(raw, scenario_id="scenario-two"),
        ),
        pytest.raises(CTFValidationError) as error,
    ):
        resolve_scenario_ctf_content("scenario-two")
    assert error.value.code == "CTF_CONTENT_SCENARIO_MISMATCH"


def test_unconfigured_scenario_performs_no_storage_call(monkeypatch) -> None:
    storage = Mock()
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: storage)
    with override_settings(
        CTF_CONTENT_REFERENCES=load_ctf_content_references_json(
            "",
            prefix="ctf/content-bundles",
        )
    ):
        assert resolve_scenario_ctf_content("scenario-one") is None
    storage.head_object.assert_not_called()
