"""Claim-fenced terminal transitions for CTFScheduledTask (#2099).

The scheduler must never let a worker's completion overwrite a task that was
cancelled or reclaimed under it: completion, requeue, and cancellation are
conditional transitions fenced on the claim token and current status, not blind
saves. These drive the model methods directly and assert the fence holds.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
from ctf.models import CTFScheduledTask

pytestmark = pytest.mark.django_db


def _task(ctf_event):
    return CTFScheduledTask.objects.create(
        event=ctf_event,
        task_type=ScheduledTaskType.EVENT_START.value,
        scheduled_for=timezone.now(),
        status=ScheduledTaskStatus.PENDING.value,
    )


def test_completion_requires_the_owning_claim_token(ctf_event):
    task = _task(ctf_event)
    token_a = uuid4()
    task.mark_running(claim_token=token_a)

    # A different worker reclaims the row with a fresh token (stale-lease recovery).
    token_b = uuid4()
    CTFScheduledTask.objects.filter(pk=task.pk).update(claim_token=token_b)

    # The original worker's completion is fenced: it does not win, status unchanged.
    assert task.complete_if_claimed(token_a) is False
    task.refresh_from_db()
    assert task.status == ScheduledTaskStatus.RUNNING.value

    # The current owner completes normally.
    assert task.complete_if_claimed(token_b) is True
    task.refresh_from_db()
    assert task.status == ScheduledTaskStatus.COMPLETED.value


def test_completion_cannot_overwrite_a_cancelled_task(ctf_event):
    task = _task(ctf_event)
    token = uuid4()
    task.mark_running(claim_token=token)

    # The task is cancelled while the worker runs the handler.
    assert task.cancel_if_active() is True
    task.refresh_from_db()
    assert task.status == ScheduledTaskStatus.CANCELLED.value

    # The worker finishes and tries to complete: fenced, cancellation survives.
    assert task.complete_if_claimed(token) is False
    task.refresh_from_db()
    assert task.status == ScheduledTaskStatus.CANCELLED.value


def test_cancel_cannot_overwrite_a_completed_task(ctf_event):
    task = _task(ctf_event)
    token = uuid4()
    task.mark_running(claim_token=token)
    assert task.complete_if_claimed(token) is True

    # A late cancellation cannot recall a completed task.
    assert task.cancel_if_active() is False
    task.refresh_from_db()
    assert task.status == ScheduledTaskStatus.COMPLETED.value


def test_interrupted_requeue_is_claim_fenced_and_clears_the_token(ctf_event):
    task = _task(ctf_event)
    token = uuid4()
    task.mark_running(claim_token=token)

    assert task.requeue_if_claimed(token) is True
    task.refresh_from_db()
    assert task.status == ScheduledTaskStatus.PENDING.value
    assert task.claim_token is None

    # A second (stale) requeue with the old token no longer matches.
    assert task.requeue_if_claimed(token) is False
