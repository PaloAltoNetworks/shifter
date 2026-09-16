"""Capacity admission wired into event spin-up (PLAT-201, #680).

The requirement's operative clause is that the engine refuses or warns *before*
spinup rather than failing during it. These drive that through the real batch
entry point.
"""

from __future__ import annotations

import pytest

from ctf.services.range.batch import provision_event_ranges_throttled

pytestmark = pytest.mark.django_db


def _summary(outcome: str, *, blocking: bool):
    return {
        "outcome": outcome,
        "blocking": blocking,
        "partition": "aws-dev-use2",
        "reason_codes": ["capacity.exceeds_headroom"],
    }


class TestRefusal:
    """An enforcing over-limit metric stops the wave before anything spins up."""

    def test_blocking_assessment_refuses_before_provisioning(self, ctf_event_active, monkeypatch):
        provisioned = []
        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: _summary("rejected", blocking=True),
        )
        monkeypatch.setattr(
            "ctf.services.range.batch._record_provision_attempt",
            lambda *a, **k: provisioned.append(1),
        )

        result = provision_event_ranges_throttled(ctf_event_active.pk, 60)

        assert result["refused"] is True
        assert result["capacity"]["outcome"] == "rejected"
        assert provisioned == []

    def test_refusal_notifies_the_organizer(self, ctf_event_active, monkeypatch):
        notified = []
        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: _summary("rejected", blocking=True),
        )
        monkeypatch.setattr(
            "ctf.services.notification.notify_organizer_capacity_outcome",
            lambda event_id, capacity: notified.append(capacity),
        )

        provision_event_ranges_throttled(ctf_event_active.pk, 60)

        assert notified
        assert notified[0]["blocking"] is True

    def test_organizer_notification_carries_no_raw_figures(self, ctf_event_active, monkeypatch):
        """Bounded reason codes only -- quota numbers stay operator-only."""
        notified = []
        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: _summary("rejected", blocking=True),
        )
        monkeypatch.setattr(
            "ctf.services.notification.notify_organizer_capacity_outcome",
            lambda event_id, capacity: notified.append(capacity),
        )

        provision_event_ranges_throttled(ctf_event_active.pk, 60)

        assert set(notified[0]) == {"outcome", "blocking", "partition", "reason_codes"}


class TestAdvisoryProceeds:
    """Advisory is the default: a warning is visible but never blocks."""

    def test_warning_does_not_refuse(self, ctf_event_active, monkeypatch):
        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: _summary("warning", blocking=False),
        )

        result = provision_event_ranges_throttled(ctf_event_active.pk, 60)

        assert result.get("refused") is None
        assert result["capacity"]["outcome"] == "warning"

    def test_indeterminate_does_not_refuse(self, ctf_event_active, monkeypatch):
        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: _summary("indeterminate", blocking=False),
        )

        result = provision_event_ranges_throttled(ctf_event_active.pk, 60)

        assert result.get("refused") is None

    def test_disabled_layer_is_transparent(self, ctf_event_active, monkeypatch):
        """With capacity planning off, spin-up behaves exactly as before."""
        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: None,
        )

        result = provision_event_ranges_throttled(ctf_event_active.pk, 60)

        assert result["capacity"] is None
        assert result.get("refused") is None


class TestAssessmentFailureIsNeverFatal:
    def test_assessment_exception_does_not_break_spinup(self, ctf_event_active, monkeypatch):
        """A capacity read must never be the reason an event cannot start."""

        def boom(event_ref):
            raise RuntimeError("engine unreachable")

        monkeypatch.setattr("ctf.bridges.cms_assess_event_capacity", boom)

        result = provision_event_ranges_throttled(ctf_event_active.pk, 60)

        assert result["capacity"] is None
        assert result.get("refused") is None


class TestSparePoolPath:
    """Growing the spare pool raises peak concurrency, so it is assessed too."""

    def test_blocking_assessment_refuses_the_top_up(self, ctf_event, monkeypatch):
        from ctf.services.range.spares import provision_event_spares

        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: _summary("rejected", blocking=True),
        )

        result = provision_event_spares(ctf_event.pk, 5)

        assert result["refused"] is True
        assert result["created"] == 0
        assert result["capacity_reason_codes"] == ["capacity.exceeds_headroom"]

    def test_refusal_payload_does_not_leak_partition_topology(self, ctf_event, monkeypatch):
        """Organizer-facing bodies carry bounded codes, not deployment topology."""
        from ctf.services.range.spares import provision_event_spares

        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: _summary("rejected", blocking=True),
        )

        result = provision_event_spares(ctf_event.pk, 5)

        assert "partition" not in str(result)
        assert "aws-dev-use2" not in str(result)

    def test_advisory_warning_still_tops_up(self, ctf_event, monkeypatch):
        from ctf.services.range.spares import provision_event_spares

        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda event_id, source: _summary("warning", blocking=False),
        )

        result = provision_event_spares(ctf_event.pk, 2)

        assert result.get("refused") is None
        # Advisory proceeds and leaves the existing result contract untouched.
        assert set(result) == {"event_id", "target_count", "existing", "created"}

    def test_spare_path_assesses_after_the_new_target_is_persisted(self, ctf_event, monkeypatch):
        """The assessment must see the new pool size, not the previous one."""
        from ctf.services.range.spares import provision_event_spares

        seen = []

        def _capture(event_id, source):
            from ctf.models import CTFEvent

            seen.append(CTFEvent.objects.get(pk=event_id).spare_range_count)
            return None

        monkeypatch.setattr("ctf.services.range.capacity.assess_declared_capacity", _capture)
        ctf_event.spare_range_count = 0
        ctf_event.save(update_fields=["spare_range_count", "updated_at"])

        provision_event_spares(ctf_event.pk, 9)

        assert seen == [9]
