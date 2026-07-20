"""CTF range recovery + spare-pool API flow tests (issue #1018).

Split out of ``test_api_view_flows.py`` to keep each test module behavior-scoped
under the platform test-suite size guard (``test_test_suite_structure.py``).
Integration-style, real DB fixtures; the recovery service runs end-to-end (no
first-party ``ctf.services.range`` patch, per ADR-019).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.ctf._api_flow_helpers import call_json as _json

if TYPE_CHECKING:
    from django.test import Client

    from ctf.models import CTFEvent, CTFParticipant

pytestmark = pytest.mark.django_db


class TestRangeRecoveryApi:
    """Organizer range-recovery endpoint (issue #1018)."""

    def test_recover_participant_range(
        self,
        authenticated_organizer_client: Client,
        organizer_user,
        ctf_participant: CTFParticipant,
        second_participant_user,
    ):
        """Organizer recovers a participant's range in their own event -> 200 + recovery result (issue #1018).

        Drives the real ``recover_participant_range`` service end-to-end
        (ADR-019 boundary-mock policy: no first-party ``ctf.services.range``
        patch) via a real CTF-sourced old range + a pooled event spare,
        mirroring ``tests/ctf/test_services/test_range_recovery.py``.
        """
        from ctf.enums import SpareRangeStatus
        from ctf.models import CTFSpareRange
        from tests.ctf.test_services.test_range_recovery import _make_spare_range

        old_range = _make_spare_range(owner=ctf_participant.user)
        ctf_participant.range_instance_id = old_range.pk
        ctf_participant.save(update_fields=["range_instance_id"])
        spare_range = _make_spare_range(owner=second_participant_user, scenario_id=ctf_participant.event.scenario_id)
        CTFSpareRange.objects.create(
            event=ctf_participant.event,
            owner_user=second_participant_user,
            range_instance_id=spare_range.pk,
            status=SpareRangeStatus.READY.value,
        )

        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_recover_participant_range",
            kwargs={"participant_id": ctf_participant.id},
            body={
                "strategy": "reassign_spare",
                "spare_range_instance_id": spare_range.pk,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["phase"] == "completed"
        assert body["strategy"] == "reassign_spare"
        assert body["old_range_instance_id"] == old_range.pk
        assert body["replacement_range_instance_id"] == spare_range.pk

        ctf_participant.refresh_from_db()
        assert ctf_participant.range_instance_id == spare_range.pk

        from ctf.models import CTFRangeRecovery

        recovery = CTFRangeRecovery.objects.get(participant=ctf_participant)
        assert recovery.created_by_id == organizer_user.id


@pytest.fixture
def event_with_spare_scenario(ctf_event: CTFEvent, organizer_user):
    """CTF event configured with an agent-free scenario so spare-pool provisioning succeeds.

    Mirrors ``tests/ctf/test_services/test_range_spares.py``'s ``event_with_scenario``
    fixture: a shared agent (``agents_by_os``) can't be resolved for many distinct
    managed spare-owning users, so the scenario used here declares no agents at all.
    """
    from cms.models import Scenario

    scenario = Scenario.objects.create(
        scenario_id="ctf-spare-pool-api-flow-test",
        name="CTF Spare Pool API Flow Test Range",
        description="Agent-free hydratable scenario for spare-pool API flow tests.",
        definition={
            "instances": [
                {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
                {"name": "Target", "role": "victim", "os_type": "windows", "xdr_agent": False},
            ],
            "subnets": [{"name": "core", "instances": ["Attacker", "Target"]}],
            "ngfw": False,
        },
        created_by=organizer_user,
        updated_by=organizer_user,
    )
    ctf_event.scenario_id = scenario.scenario_id
    ctf_event.range_config = {"agents_by_os": {}, "ngfw_enabled": False}
    ctf_event.save(update_fields=["scenario_id", "range_config"])
    return ctf_event


class TestSpareRangePoolApi:
    """Operator endpoint for managing an event's spare-range pool (issue #1018)."""

    def test_organizer_provisions_spares(
        self, authenticated_organizer_client: Client, event_with_spare_scenario: CTFEvent
    ):
        resp = _json(
            authenticated_organizer_client,
            "post",
            "api_provision_event_spares",
            kwargs={"event_id": event_with_spare_scenario.id},
            body={"count": 2},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "event_id": str(event_with_spare_scenario.id),
            "target_count": 2,
            "existing": 0,
            "created": 2,
        }

        from ctf.models import CTFSpareRange

        assert CTFSpareRange.objects.filter(event=event_with_spare_scenario).count() == 2
        event_with_spare_scenario.refresh_from_db()
        assert event_with_spare_scenario.spare_range_count == 2
