"""Per-range capacity draws on the creation paths (PLAT-201, #680).

Every path that creates a range for an event now draws from that event's
budget: the participant path (including a late joiner arriving after the wave)
and the spare path. These drive the behaviour that matters -- the draw happens
before the range is created, a failed creation gives the capacity back, and an
enforcing over-budget draw refuses instead of failing later in spinup.
"""

from __future__ import annotations

import pytest

from ctf.exceptions import CTFRangeError

pytestmark = pytest.mark.django_db


def _summary(outcome: str, *, blocking: bool):
    return {"outcome": outcome, "blocking": blocking, "reason_codes": ["capacity.exceeds_headroom"]}


class TestParticipantPath:
    def test_draw_happens_before_the_range_is_created(self, ctf_event_active, participant_user, monkeypatch):
        """Ordering is the point: refuse before creating, not after."""
        from ctf.models import CTFParticipant
        from ctf.services.range.provision import provision_participant_range

        participant = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="late",
            status="active",
        )
        order = []
        monkeypatch.setattr(
            "ctf.services.range.capacity.admit_range",
            lambda event_id, draw_key: order.append("admit") or None,
        )
        monkeypatch.setattr("ctf.services.range.capacity.release_range", lambda draw_key: None)

        def _record_create(**kwargs):
            order.append("create")
            raise RuntimeError("stop after ordering is observed")

        monkeypatch.setattr("ctf.bridges.cms_create_range", _record_create)

        with pytest.raises(CTFRangeError):
            provision_participant_range(participant.pk)

        assert order == ["admit", "create"]

    def test_blocking_draw_refuses_without_creating_a_range(self, ctf_event_active, participant_user, monkeypatch):
        from ctf.models import CTFParticipant
        from ctf.services.range.provision import provision_participant_range

        participant = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="late",
            status="active",
        )
        created = []
        monkeypatch.setattr(
            "ctf.services.range.capacity.admit_range",
            lambda event_id, draw_key: _summary("rejected", blocking=True),
        )
        monkeypatch.setattr("ctf.bridges.cms_create_range", lambda **kwargs: created.append(1))

        with pytest.raises(CTFRangeError, match="capacity budget"):
            provision_participant_range(participant.pk)

        assert created == []

    def test_draw_is_keyed_on_the_participant(self, ctf_event_active, participant_user, monkeypatch):
        """A stable key is what makes a retried provision idempotent."""
        from ctf.models import CTFParticipant
        from ctf.services.range.provision import provision_participant_range

        participant = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="late",
            status="active",
        )
        seen = []
        monkeypatch.setattr(
            "ctf.services.range.capacity.admit_range",
            lambda event_id, draw_key: seen.append(draw_key) or _summary("rejected", blocking=True),
        )

        with pytest.raises(CTFRangeError):
            provision_participant_range(participant.pk)

        assert seen == [participant.pk]

    def test_failed_creation_releases_the_draw(self, ctf_event_active, participant_user, monkeypatch):
        """A range that never came up must not hold budget."""
        from ctf.models import CTFParticipant
        from ctf.services.range.provision import provision_participant_range

        participant = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="late",
            status="active",
        )
        released = []
        monkeypatch.setattr("ctf.services.range.capacity.admit_range", lambda event_id, draw_key: None)
        monkeypatch.setattr("ctf.services.range.capacity.release_range", lambda draw_key: released.append(draw_key))

        def _boom(**kwargs):
            raise RuntimeError("cms down")

        monkeypatch.setattr("ctf.bridges.cms_create_range", _boom)

        with pytest.raises(CTFRangeError):
            provision_participant_range(participant.pk)

        assert released == [participant.pk]


class TestSparePath:
    def test_blocking_draw_marks_the_spare_failed_without_creating(self, ctf_event, monkeypatch):
        from ctf.enums import SpareRangeStatus
        from ctf.services.range.spares import provision_event_spares

        created = []
        monkeypatch.setattr(
            "ctf.services.range.capacity.admit_range",
            lambda event_id, draw_key: _summary("rejected", blocking=True),
        )
        monkeypatch.setattr("ctf.services.range.capacity.assess_declared_capacity", lambda event_id, source: None)
        monkeypatch.setattr("ctf.bridges.cms_create_range", lambda **kwargs: created.append(1))

        result = provision_event_spares(ctf_event.pk, 2)

        assert created == []
        assert result["created"] == 0
        from ctf.models import CTFSpareRange

        assert CTFSpareRange.objects.filter(event=ctf_event, status=SpareRangeStatus.FAILED.value).count() == 2

    def test_each_spare_draws_under_a_distinct_key(self, ctf_event, monkeypatch):
        """Two spares must not collide on one ledger key."""
        from ctf.services.range.spares import provision_event_spares

        seen = []
        monkeypatch.setattr(
            "ctf.services.range.capacity.admit_range",
            lambda event_id, draw_key: seen.append(draw_key) or _summary("rejected", blocking=True),
        )
        monkeypatch.setattr("ctf.services.range.capacity.assess_declared_capacity", lambda event_id, source: None)

        provision_event_spares(ctf_event.pk, 3)

        assert len(seen) == 3
        assert len(set(seen)) == 3
