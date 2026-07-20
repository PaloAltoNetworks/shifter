"""Behavior tests for two canonical DRF Mission Control range reads (#1370):

- ``CurrentRangeView`` (``GET /api/v1/mission-control/range/``) filtering a
  CTF-participant-only account down to Kali instances, mirroring
  ``mission_control.context_processors.active_range``'s existing template
  behavior (previously the DRF read leaked non-Kali instances to participants).
- The new range-history list (``GET /api/v1/mission-control/ranges/``), backed
  by ``cms.services.list_mission_control_range_history`` — the product-scoped
  query that INCLUDES soft-deleted terminal ranges (the historical rows) and
  EXCLUDES CTF-sourced ranges (provenance isolation).

Drives real ``RangeInstance`` rows (not patched services) so the projection,
ownership filter, and CTF-participant filter are exercised end to end.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from shared.auth import CTF_PARTICIPANT_GROUP
from shared.enums import RequestType

pytestmark = pytest.mark.django_db

RANGE_URL = "/api/v1/mission-control/range/"
RANGES_URL = "/api/v1/mission-control/ranges/"


def _instance(os_type, *, uuid=None, role=None, name=None):
    return {
        "uuid": uuid or str(uuid4()),
        "name": name or os_type,
        "role": role or ("attacker" if os_type == "kali" else "victim"),
        "os_type": os_type,
    }


def _seed_range(user, *, instances, status="ready", scenario_id="basic", range_id=None, range_source="mission_control"):
    from cms.models import RangeInstance
    from cms.models import Request as CMSRequest

    request = CMSRequest.objects.create(request_id=uuid4(), request_type=RequestType.RANGE.value, user=user)
    # A terminal status (destroyed/failed) trips RangeInstance.save()'s
    # auto-soft-delete, so passing status="destroyed" seeds a soft-deleted row
    # (hidden from the default manager, visible via all_objects) without a
    # separate delete step.
    return RangeInstance.objects.create(
        request=request,
        scenario_id=scenario_id,
        user_id=user.id,
        status=status,
        range_id=range_id,
        range_source=range_source,
        range_spec={"instances": instances},
    )


def _make_ctf_participant_only(user):
    group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    user.groups.add(group)
    return user


class TestCurrentRangeViewKaliFilter:
    def test_ctf_participant_only_sees_kali_instances_only(self, authenticated_client):
        client, user = authenticated_client(email="ctf-kali@example.com")
        _make_ctf_participant_only(user)
        _seed_range(
            user,
            instances=[_instance("kali"), _instance("ubuntu"), _instance("windows"), _instance("panos")],
        )

        response = client.get(RANGE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is True
        assert [inst["os_type"] for inst in data["range"]["instances"]] == ["kali"]
        assert len(data["connection_urls"]) == 1

    def test_non_participant_sees_all_instances(self, authenticated_client):
        client, user = authenticated_client(email="normal-user@example.com")
        _seed_range(
            user,
            instances=[_instance("kali"), _instance("ubuntu"), _instance("windows"), _instance("panos")],
        )

        response = client.get(RANGE_URL)

        assert response.status_code == 200
        data = response.json()
        assert len(data["range"]["instances"]) == 4
        assert len(data["connection_urls"]) == 4

    def test_ctf_participant_without_kali_gets_empty_instances(self, authenticated_client):
        client, user = authenticated_client(email="ctf-no-kali@example.com")
        _make_ctf_participant_only(user)
        _seed_range(user, instances=[_instance("ubuntu"), _instance("windows")])

        response = client.get(RANGE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["range"]["instances"] == []
        assert data["connection_urls"] == []


class TestRangeHistoryView:
    def test_requires_login(self):
        assert Client().get(RANGES_URL).status_code == 401

    def test_returns_the_users_ranges(self, authenticated_client):
        client, user = authenticated_client(email="history-owner@example.com")
        # Only one Mission Control range is active per user at a time (#307), so a
        # realistic history is soft-deleted terminal rows plus the current active
        # one. history reads through ``all_objects``, so both appear.
        first = _seed_range(user, instances=[_instance("kali")], scenario_id="basic", status="destroyed")
        second = _seed_range(user, instances=[_instance("kali")], scenario_id="ad_attack_lab", status="provisioning")

        response = client.get(RANGES_URL)

        assert response.status_code == 200
        rows = response.json()["ranges"]
        assert {row["scenario_id"] for row in rows} == {"basic", "ad_attack_lab"}
        assert {row["request_id"] for row in rows} == {
            str(first.request.request_id),
            str(second.request.request_id),
        }
        assert {row["status"] for row in rows} == {"destroyed", "provisioning"}
        assert all(row["range_source"] == "mission_control" for row in rows)
        by_scenario = {row["scenario_id"]: row for row in rows}
        assert by_scenario["basic"]["deleted_at"] is not None  # terminal history row
        assert by_scenario["ad_attack_lab"]["deleted_at"] is None  # the active range

    def test_does_not_return_another_users_ranges(self, authenticated_client):
        _owner_client, owner = authenticated_client(email="history-owner2@example.com")
        _seed_range(owner, instances=[_instance("kali")])

        other_client, _other = authenticated_client(email="history-other@example.com")
        response = other_client.get(RANGES_URL)

        assert response.status_code == 200
        assert response.json()["ranges"] == []

    def test_returns_empty_list_when_no_ranges(self, authenticated_client):
        client, _user = authenticated_client(email="history-empty@example.com")

        response = client.get(RANGES_URL)

        assert response.status_code == 200
        assert response.json() == {"ranges": []}

    def test_includes_soft_deleted_terminal_ranges(self, authenticated_client):
        # History exists to show past ranges: terminal (destroyed/failed) rows
        # are soft-deleted on save, so the generic soft-delete-managed query
        # would hide exactly the rows this surface lists. The product-scoped
        # history query reads through all_objects and must return them.
        client, user = authenticated_client(email="history-terminal@example.com")
        active = _seed_range(user, instances=[_instance("kali")], scenario_id="basic", status="ready")
        destroyed = _seed_range(user, instances=[_instance("kali")], scenario_id="ad_attack_lab", status="destroyed")

        response = client.get(RANGES_URL)

        assert response.status_code == 200
        rows = response.json()["ranges"]
        by_request = {row["request_id"]: row for row in rows}
        assert str(active.request.request_id) in by_request
        assert str(destroyed.request.request_id) in by_request, "destroyed (soft-deleted) range missing from history"
        assert by_request[str(destroyed.request.request_id)]["status"] == "destroyed"
        assert by_request[str(destroyed.request.request_id)]["deleted_at"] is not None
        assert by_request[str(active.request.request_id)]["deleted_at"] is None

    def test_excludes_ctf_sourced_ranges(self, authenticated_client):
        # Provenance isolation: a CTF-sourced range for the same user must never
        # appear on the Mission Control history surface.
        client, user = authenticated_client(email="history-provenance@example.com")
        mc = _seed_range(user, instances=[_instance("kali")], scenario_id="basic", range_source="mission_control")
        _seed_range(user, instances=[_instance("kali")], scenario_id="ctf_only", range_source="ctf")

        response = client.get(RANGES_URL)

        assert response.status_code == 200
        rows = response.json()["ranges"]
        assert {row["request_id"] for row in rows} == {str(mc.request.request_id)}
        assert all(row["range_source"] == "mission_control" for row in rows)
