"""Organizer content-refresh API contract (issue #1971).

Content resolution runs for real against a mocked object-storage boundary
(``shared.cloud.get_object_storage``) rather than a first-party service patch,
so these tests exercise the true resolve -> reconcile path (ADR-019-R1).
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.test import override_settings
from django.utils import timezone

from ctf.content_bundle import parse_ctf_content_bundle
from ctf.enums import EventStatus
from ctf.models import CTFEvent
from ctf.services.content_hydration import hydrate_event_ctf_content
from ctf.services.content_resolution import HydrationSourceEvidence, ResolvedCtfContent
from shared.schemas.ctf_content_reference import load_ctf_content_references_json
from tests.ctf._api_flow_helpers import call_json as _json

pytestmark = pytest.mark.django_db

_PREFIX = "ctf/content-bundles"


def _raw(*, one_name: str = "Challenge One", one_flag: str = "TEST{one}", one_points: int = 100) -> bytes:
    return json.dumps(
        {
            "contract": "shifter-ctf-content/v1",
            "scenario_id": "scenario-one",
            "challenges": [
                {
                    "id": "challenge-one",
                    "name": one_name,
                    "description": "Inspect the portal.",
                    "category": "Module 1",
                    "points": one_points,
                    "difficulty": "easy",
                    "order": 1,
                    "flags": [{"type": "static", "value": one_flag, "order": 0}],
                    "hints": [],
                    "prerequisites": [],
                }
            ],
        }
    ).encode()


def _digest(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _resolved_from_raw(raw: bytes) -> ResolvedCtfContent:
    return ResolvedCtfContent(
        bundle=parse_ctf_content_bundle(raw),
        evidence=HydrationSourceEvidence(
            reference_contract="shifter-ctf-content-references/v1",
            declared_digest=_digest(raw),
            object_key_fingerprint="b" * 64,
            object_identity_fingerprint="c" * 64,
            object_size_bytes=len(raw),
        ),
    )


def _references(raw: bytes):
    return load_ctf_content_references_json(
        json.dumps(
            {
                "contract": "shifter-ctf-content-references/v1",
                "references": [
                    {
                        "scenario_id": "scenario-one",
                        "object_key": f"{_PREFIX}/aa/bundle.json",
                        "digest": _digest(raw),
                    }
                ],
            }
        ),
        prefix=_PREFIX,
    )


def _storage(raw: bytes) -> Mock:
    storage = Mock()
    identity = {"content_length": len(raw), "etag": "etag-one", "generation": "7"}
    storage.head_object.return_value = identity

    def download(_bucket, _key, destination, **_kwargs):
        Path(destination).write_bytes(raw)
        return identity

    storage.download_object.side_effect = download
    return storage


def _managed_active_event(organizer_user, raw: bytes) -> CTFEvent:
    now = timezone.now()
    event = CTFEvent.objects.create(
        name="Refresh API",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=now + timedelta(hours=1),
        event_end=now + timedelta(hours=2),
        scenario_id="scenario-one",
    )
    hydrate_event_ctf_content(event.pk, _resolved_from_raw(raw), actor_id=organizer_user.pk)
    event.status = EventStatus.ACTIVE.value
    event.save(update_fields=["status", "updated_at"])
    return event


def _post_refresh(client, event, expected_digest):
    return _json(
        client,
        "post",
        "api_event_content_refresh",
        kwargs={"event_id": event.id},
        body={"expected_current_digest": expected_digest},
    )


def test_refresh_applies_configured_revision(authenticated_organizer_client, organizer_user, monkeypatch):
    raw_a = _raw()
    raw_b = _raw(one_name="Fixed", one_flag="TEST{fixed}")
    event = _managed_active_event(organizer_user, raw_a)
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: _storage(raw_b))
    with override_settings(
        CTF_CONTENT_BUCKET="private-content",
        CTF_CONTENT_MAX_BYTES=1024 * 1024,
        CTF_CONTENT_REFERENCES=_references(raw_b),
    ):
        resp = _post_refresh(authenticated_organizer_client, event, _digest(raw_a))
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "refreshed"


def test_refresh_rejects_unsafe_live_change_as_conflict(authenticated_organizer_client, organizer_user, monkeypatch):
    raw_a = _raw()
    raw_b = _raw(one_points=999)
    event = _managed_active_event(organizer_user, raw_a)
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: _storage(raw_b))
    with override_settings(
        CTF_CONTENT_BUCKET="private-content",
        CTF_CONTENT_MAX_BYTES=1024 * 1024,
        CTF_CONTENT_REFERENCES=_references(raw_b),
    ):
        resp = _post_refresh(authenticated_organizer_client, event, _digest(raw_a))
    assert resp.status_code == 409


def test_refresh_rejects_malformed_digest(authenticated_organizer_client, organizer_user):
    event = _managed_active_event(organizer_user, _raw())
    resp = _post_refresh(authenticated_organizer_client, event, "not-a-digest")
    assert resp.status_code == 400


def test_refresh_on_scenario_without_content_is_conflict(authenticated_organizer_client, organizer_user):
    raw_a = _raw()
    event = _managed_active_event(organizer_user, raw_a)
    with override_settings(CTF_CONTENT_REFERENCES=load_ctf_content_references_json("", prefix=_PREFIX)):
        resp = _post_refresh(authenticated_organizer_client, event, _digest(raw_a))
    assert resp.status_code == 409
