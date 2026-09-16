"""Behaviour tests for Phase 3 reconcile_range_events command (#476).

Drives real ORM rows and the real CMS range projection helper.

Import structure:
- engine.models imported inside test functions (test code, not subject to
  ADR-001 production import boundary).
- The reconciler is imported at module level (it lives in cms, where
  engine.services is allowed).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.handlers.range_events import apply_range_status, process_range_event
from cms.management.commands.reconcile_range_events import (
    Command,
    reconcile_range_instances,
    stale_range_instances_queryset,
)
from cms.models import RangeInstance
from cms.models import Request as CMSRequest
from cms.signals import range_status_changed
from shared.enums import RequestType, ResourceStatus

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_reconciler_pass_also_expires_due_range_leases():
    """The existing generic reconciler is the single lease-cleanup runtime."""
    user = _user()
    request_id = uuid4()
    cms_req = _cms_request(user, request_id)
    _, engine_range = _engine_request_and_range(user, request_id, engine_status=ResourceStatus.READY.value)
    instance = _range_instance(user, cms_req, status=ResourceStatus.READY.value)
    now = timezone.now()
    RangeInstance.objects.filter(pk=instance.pk).update(
        expires_at=now - timedelta(minutes=1),
        maximum_expires_at=now + timedelta(days=1),
    )

    Command()._run_once(stale_seconds=300, batch_size=25)

    instance = RangeInstance.all_objects.get(pk=instance.pk)
    engine_range.refresh_from_db()
    assert instance.status == ResourceStatus.DESTROYING.value
    assert instance.deleted_at is not None
    assert engine_range.status == ResourceStatus.DESTROYING.value


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _user(suffix: str | None = None) -> User:
    sfx = suffix or uuid4().hex[:8]
    return User.objects.create_user(username=f"recon-{sfx}@e.com", email=f"recon-{sfx}@e.com")


def _cms_request(user, request_id=None) -> CMSRequest:
    return CMSRequest.objects.create(
        workspace_id=_WORKSPACE_ID,
        request_id=request_id or uuid4(),
        request_type=RequestType.RANGE.value,
        user=user,
    )


def _range_instance(user, cms_request, *, status=ResourceStatus.PROVISIONING.value) -> RangeInstance:
    return RangeInstance.objects.create(
        workspace_id=_WORKSPACE_ID,
        user_id=user.id,
        request=cms_request,
        status=status,
        scenario_id="basic",
    )


def _engine_request_and_range(user, request_id, *, engine_status=ResourceStatus.READY.value):
    """Create matching engine.Request + engine.Range rows."""
    from engine.models import Range as EngineRange
    from engine.models import Request as EngineRequest

    eng_req = EngineRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    eng_range = EngineRange.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=eng_req,
        user=user,
        status=engine_status,
    )
    return eng_req, eng_range


def _backdate_range_instance(instance: RangeInstance, seconds: int = 600) -> None:
    """Force updated_at into the past, bypassing auto_now."""
    old_ts = timezone.now() - timedelta(seconds=seconds)
    RangeInstance.all_objects.filter(pk=instance.pk).update(updated_at=old_ts)


def _ctf_signal_collector():
    """Returns (received_list, connect, disconnect) triple for range_status_changed."""
    received: list[dict] = []

    def receiver(sender, **kwargs):
        received.append(kwargs)

    return received, receiver


# ---------------------------------------------------------------------------
# apply_range_status helper tests
# ---------------------------------------------------------------------------


class TestApplyRangeStatus:
    """Unit tests for the shared idempotent helper."""

    def test_no_op_when_already_at_target_status(self, db):
        user = _user()
        cms_req = _cms_request(user)
        instance = _range_instance(user, cms_req, status=ResourceStatus.READY.value)

        result = apply_range_status(instance, ResourceStatus.READY.value)

        assert result is False
        instance.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value

    def test_applies_status_change_and_fires_ctf_signal(self, db):
        user = _user()
        cms_req = _cms_request(user)
        instance = _range_instance(user, cms_req, status=ResourceStatus.PROVISIONING.value)

        received, receiver = _ctf_signal_collector()
        range_status_changed.connect(receiver, weak=False)
        try:
            result = apply_range_status(instance, ResourceStatus.READY.value)
        finally:
            range_status_changed.disconnect(receiver)

        assert result is True
        instance.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value
        assert len(received) == 1
        assert received[0]["new_status"] == ResourceStatus.READY.value
        assert received[0]["previous_status"] == ResourceStatus.PROVISIONING.value

    def test_does_not_fire_bridges_on_no_op(self, db):
        """Already-converged instance: bridges are never called."""
        user = _user()
        cms_req = _cms_request(user)
        instance = _range_instance(user, cms_req, status=ResourceStatus.READY.value)

        received, receiver = _ctf_signal_collector()
        range_status_changed.connect(receiver, weak=False)
        try:
            apply_range_status(instance, ResourceStatus.READY.value)
        finally:
            range_status_changed.disconnect(receiver)

        assert received == []

    def test_transient_db_save_error_propagates(self, db):
        """A transient DB error in apply_range_status raises (worker can retry).

        The "already converged" early-return path (same status) must NOT raise.
        Only the save() path raises when the DB is unavailable.
        """
        from django.db.models.signals import pre_save

        user = _user()
        cms_req = _cms_request(user)
        instance = _range_instance(user, cms_req, status=ResourceStatus.PROVISIONING.value)
        target_pk = instance.pk

        def _fail_if_target(sender, instance, **kwargs):
            if instance.pk == target_pk:
                raise Exception("DB connection lost")

        pre_save.connect(_fail_if_target, sender=RangeInstance)
        try:
            with pytest.raises(Exception, match="DB connection lost"):
                apply_range_status(instance, ResourceStatus.READY.value)
        finally:
            pre_save.disconnect(_fail_if_target, sender=RangeInstance)

    def test_already_converged_no_op_returns_without_raising(self, db):
        """Already at target status → returns False without saving or raising."""
        user = _user()
        cms_req = _cms_request(user)
        instance = _range_instance(user, cms_req, status=ResourceStatus.READY.value)

        result = apply_range_status(instance, ResourceStatus.READY.value)

        assert result is False

    def test_process_range_event_propagates_db_error(self, db):
        """process_range_event propagates transient DB errors (worker retries)."""
        import json

        from django.db.models.signals import pre_save

        user = _user()
        cms_req = _cms_request(user)
        _range_instance(user, cms_req, status=ResourceStatus.PROVISIONING.value)

        msg = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "new_status": ResourceStatus.READY.value,
                    "user_id": user.id,
                    "request_id": str(cms_req.request_id),
                }
            )
        }

        def _always_fail(sender, instance, **kwargs):
            raise Exception("DB flap")

        pre_save.connect(_always_fail, sender=RangeInstance)
        try:
            with pytest.raises(Exception, match="DB flap"):
                process_range_event(msg)
        finally:
            pre_save.disconnect(_always_fail, sender=RangeInstance)


# ---------------------------------------------------------------------------
# reconcile_range_instances tests
# ---------------------------------------------------------------------------


class TestReconcileRangeInstances:
    def test_stale_lagging_instance_reconciled_to_ready_and_bridges_fired(self, db):
        """Stale PROVISIONING RangeInstance whose engine.Range is READY → updated."""
        user = _user()
        request_id = uuid4()
        cms_req = _cms_request(user, request_id)
        _engine_request_and_range(user, request_id, engine_status=ResourceStatus.READY.value)
        instance = _range_instance(user, cms_req, status=ResourceStatus.PROVISIONING.value)
        _backdate_range_instance(instance)

        received, receiver = _ctf_signal_collector()
        range_status_changed.connect(receiver, weak=False)
        try:
            counts = reconcile_range_instances(stale_seconds=0, batch_size=100)
        finally:
            range_status_changed.disconnect(receiver)

        instance.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value
        assert counts["reconciled"] == 1
        assert counts["converged"] == 0
        # CTF bridge fired.
        assert len(received) == 1
        assert received[0]["new_status"] == ResourceStatus.READY.value

    def test_already_converged_is_noop(self, db):
        """RangeInstance and engine.Range both READY → converged, no DB write."""
        user = _user()
        request_id = uuid4()
        cms_req = _cms_request(user, request_id)
        _engine_request_and_range(user, request_id, engine_status=ResourceStatus.READY.value)
        instance = _range_instance(user, cms_req, status=ResourceStatus.READY.value)
        _backdate_range_instance(instance)

        received, receiver = _ctf_signal_collector()
        range_status_changed.connect(receiver, weak=False)
        try:
            counts = reconcile_range_instances(stale_seconds=0, batch_size=100)
        finally:
            range_status_changed.disconnect(receiver)

        assert counts["converged"] == 1
        assert counts["reconciled"] == 0
        assert received == []

    def test_not_yet_stale_is_skipped(self, db):
        """Instance updated_at is recent → not in the stale query, nothing processed."""
        user = _user()
        request_id = uuid4()
        cms_req = _cms_request(user, request_id)
        _engine_request_and_range(user, request_id, engine_status=ResourceStatus.READY.value)
        _range_instance(user, cms_req, status=ResourceStatus.PROVISIONING.value)
        # Do NOT backdate — updated_at is just now.

        counts = reconcile_range_instances(stale_seconds=300, batch_size=100)

        assert counts["reconciled"] == 0
        assert counts["converged"] == 0

    def test_never_moves_status_backward(self, db):
        """Engine shows PROVISIONING but CMS is READY → not a forward move, skipped."""
        user = _user()
        request_id = uuid4()
        cms_req = _cms_request(user, request_id)
        # Engine is behind CMS (abnormal but guard must hold).
        _engine_request_and_range(user, request_id, engine_status=ResourceStatus.PROVISIONING.value)
        instance = _range_instance(user, cms_req, status=ResourceStatus.READY.value)
        _backdate_range_instance(instance)

        counts = reconcile_range_instances(stale_seconds=0, batch_size=100)

        instance.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value  # unchanged
        assert counts["skipped"] == 1
        assert counts["reconciled"] == 0

    def test_paused_instance_resumes_to_ready(self, db):
        """CMS PAUSED but engine resumed to READY → reconciled (resume recovery).

        Regression for the codex finding: a linear status rank ranked PAUSED/
        RESUMING above READY, so the lost resume event (paused → ready) the
        reconciler exists to repair was wrongly classified as a backward move
        and skipped. The explicit recovery relation must allow it.
        """
        user = _user()
        request_id = uuid4()
        cms_req = _cms_request(user, request_id)
        _engine_request_and_range(user, request_id, engine_status=ResourceStatus.READY.value)
        instance = _range_instance(user, cms_req, status=ResourceStatus.PAUSED.value)
        _backdate_range_instance(instance)

        counts = reconcile_range_instances(stale_seconds=0, batch_size=100)

        instance.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value  # resume recovery applied
        assert counts["reconciled"] == 1
        assert counts["skipped"] == 0

    def test_missing_engine_range_increments_no_engine_range_count(self, db):
        """No engine.Range found → no_engine_range count, row untouched."""
        user = _user()
        cms_req = _cms_request(user)
        instance = _range_instance(user, cms_req, status=ResourceStatus.PROVISIONING.value)
        _backdate_range_instance(instance)

        counts = reconcile_range_instances(stale_seconds=0, batch_size=100)

        assert counts["no_engine_range"] == 1
        assert counts["reconciled"] == 0
        instance.refresh_from_db()
        assert instance.status == ResourceStatus.PROVISIONING.value  # untouched

    def test_terminal_instance_excluded_from_query(self, db):
        """DESTROYED/FAILED RangeInstance rows are never touched by the reconciler."""
        user = _user()
        request_id = uuid4()
        cms_req = _cms_request(user, request_id)
        _engine_request_and_range(user, request_id, engine_status=ResourceStatus.READY.value)
        # Create a terminal instance — use all_objects to see it after save auto-soft-deletes.
        instance = RangeInstance.all_objects.create(
            user_id=user.id,
            request=cms_req,
            status=ResourceStatus.FAILED.value,
            scenario_id="basic",
            workspace_id=_WORKSPACE_ID,
        )
        _backdate_range_instance(instance)

        counts = reconcile_range_instances(stale_seconds=0, batch_size=100)

        assert counts["reconciled"] == 0
        assert counts["no_engine_range"] == 0

    def test_reconciles_stale_failed_engine_range(self, db):
        """PROVISIONING CMS but FAILED engine → forward move (rank 9 > 1), reconciled."""
        user = _user()
        request_id = uuid4()
        cms_req = _cms_request(user, request_id)
        _engine_request_and_range(user, request_id, engine_status=ResourceStatus.FAILED.value)
        instance = _range_instance(user, cms_req, status=ResourceStatus.PROVISIONING.value)
        _backdate_range_instance(instance)

        counts = reconcile_range_instances(stale_seconds=0, batch_size=100)

        assert counts["reconciled"] == 1
        instance.refresh_from_db()
        assert instance.status == ResourceStatus.FAILED.value

    def test_failing_row_does_not_abort_batch(self, db):
        """A row whose DB save raises does not abort the whole batch.

        The reconciler must catch per-row exceptions, count them as 'failed',
        and continue processing remaining rows so one transient failure doesn't
        leave the entire stale batch unprocessed.
        """
        from django.db.models.signals import pre_save

        user = _user()

        # Row 1 — will fail: pre_save signal raises for its pk
        req_id_1 = uuid4()
        cms_req_1 = _cms_request(user, req_id_1)
        _engine_request_and_range(user, req_id_1, engine_status=ResourceStatus.READY.value)
        instance_1 = _range_instance(user, cms_req_1, status=ResourceStatus.PROVISIONING.value)
        _backdate_range_instance(instance_1)

        # Row 2 — will succeed: processed normally. A different user so the two
        # stale PROVISIONING ranges don't trip the one-active-range-per-source
        # constraint (#307); the reconciler batches stale ranges across users.
        user2 = _user()
        req_id_2 = uuid4()
        cms_req_2 = _cms_request(user2, req_id_2)
        _engine_request_and_range(user2, req_id_2, engine_status=ResourceStatus.READY.value)
        instance_2 = _range_instance(user2, cms_req_2, status=ResourceStatus.PROVISIONING.value)
        _backdate_range_instance(instance_2)

        pk_to_fail = instance_1.pk

        def _fail_for_pk(sender, instance, **kwargs):
            if instance.pk == pk_to_fail:
                raise Exception("simulated transient DB error")

        pre_save.connect(_fail_for_pk, sender=RangeInstance)
        try:
            counts = reconcile_range_instances(stale_seconds=0, batch_size=100)
        finally:
            pre_save.disconnect(_fail_for_pk, sender=RangeInstance)

        assert counts["failed"] == 1
        assert counts["reconciled"] == 1

        instance_1.refresh_from_db()
        instance_2.refresh_from_db()
        assert instance_1.status == ResourceStatus.PROVISIONING.value  # unchanged (failed row)
        assert instance_2.status == ResourceStatus.READY.value  # reconciled


# ---------------------------------------------------------------------------
# process_range_event behaviour unchanged after refactor
# ---------------------------------------------------------------------------


class TestProcessRangeEventUnchangedAfterRefactor:
    """Prove that extracting apply_range_status didn't break process_range_event.

    These mirror the equivalent tests in test_handlers.py; they run here to
    give an explicit green signal that the refactor kept behaviour identical.
    """

    def _range_event(self, *, new_status, user_id, range_id=None, request_id=None, **extra):
        import json

        payload = {"event_type": "range.status.updated", "new_status": new_status, "user_id": user_id, **extra}
        if range_id is not None:
            payload["range_id"] = range_id
        if request_id is not None:
            payload["request_id"] = str(request_id)
        return {"Message": json.dumps(payload)}

    def test_updates_status_from_event(self, db):
        user = _user()
        cms_req = _cms_request(user)
        instance = RangeInstance.objects.create(
            workspace_id=_WORKSPACE_ID,
            user_id=user.id,
            request=cms_req,
            status=ResourceStatus.PROVISIONING.value,
            scenario_id="basic",
        )
        process_range_event(
            self._range_event(
                request_id=cms_req.request_id,
                new_status=ResourceStatus.READY.value,
                user_id=user.id,
            )
        )
        instance.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value

    def test_noop_on_same_status(self, db):
        """apply_range_status idempotency propagates through process_range_event."""
        user = _user()
        cms_req = _cms_request(user)
        RangeInstance.objects.create(
            workspace_id=_WORKSPACE_ID,
            user_id=user.id,
            request=cms_req,
            status=ResourceStatus.PROVISIONING.value,
            scenario_id="basic",
        )
        # Send the SAME status that's already set.
        received, receiver = _ctf_signal_collector()
        range_status_changed.connect(receiver, weak=False)
        try:
            process_range_event(
                self._range_event(
                    request_id=cms_req.request_id,
                    new_status=ResourceStatus.PROVISIONING.value,
                    user_id=user.id,
                )
            )
        finally:
            range_status_changed.disconnect(receiver)

        # apply_range_status short-circuits → no bridge fired.
        assert received == []

    def test_rejects_unknown_status(self, db):
        user = _user()
        cms_req = _cms_request(user)
        instance = RangeInstance.objects.create(
            workspace_id=_WORKSPACE_ID,
            user_id=user.id,
            request=cms_req,
            status=ResourceStatus.PROVISIONING.value,
            scenario_id="basic",
        )
        process_range_event(
            self._range_event(
                request_id=cms_req.request_id,
                new_status="bogus_status",
                user_id=user.id,
            )
        )
        instance.refresh_from_db()
        assert instance.status == ResourceStatus.PROVISIONING.value


class TestReconcileHeartbeat:
    """--loop mode touches the heartbeat file after each cycle."""

    def test_loop_touches_heartbeat(self, tmp_path, monkeypatch):
        """One loop iteration must write the heartbeat file."""
        from django.core.management import call_command

        from cms.management.commands import reconcile_range_events as cmd_module

        heartbeat_file = tmp_path / "worker-reconciler-heartbeat"
        monkeypatch.setattr(cmd_module, "HEARTBEAT_FILE", heartbeat_file)

        call_count = 0

        def fake_sleep(_interval: int) -> None:
            nonlocal call_count
            call_count += 1
            raise KeyboardInterrupt

        # Patch time.sleep at the stdlib module level (root: "time") so the
        # target is not a first-party internal path and does not widen the
        # ADR-019 boundary-mock baseline.
        with (
            patch("time.sleep", side_effect=fake_sleep),
            pytest.raises(KeyboardInterrupt),
        ):
            call_command(
                "reconcile_range_events",
                loop=True,
                interval=60,
                stale_seconds=300,
                batch_size=10,
            )

        assert heartbeat_file.exists(), "heartbeat file must be written during loop iteration"
        assert call_count == 1


class TestStaleRangeInstancesQueryset:
    """#1395: the reconciler's locked query must scope FOR UPDATE to the base row."""

    def test_locks_only_self_not_the_joined_nullable_request(self, db):
        # select_related("request") LEFT-joins a nullable FK; a bare
        # select_for_update raised NotSupportedError on Postgres ("FOR UPDATE
        # cannot be applied to the nullable side of an outer join"). of=("self",)
        # scopes the lock to cms_range so only the base row is locked.
        qs = stale_range_instances_queryset(timezone.now(), 10)

        assert qs.query.select_for_update is True
        assert qs.query.select_for_update_skip_locked is True
        assert qs.query.select_for_update_of == ("self",)
