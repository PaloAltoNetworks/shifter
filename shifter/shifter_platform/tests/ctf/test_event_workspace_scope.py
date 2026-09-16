"""CTFEvent workspace tenancy scope (ADR-051, #2048).

CTF events gain an immutable scalar ``workspace_id``. Creation resolves it from
an authorized workspace or the creator's personal workspace; it is required and
frozen after creation. Each test drives the real service/model and asserts the
effect, so it goes red if any of those rules is removed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.exceptions import CTFValidationError
from ctf.models import CTFEvent
from ctf.services.event import create_event
from workspaces.models import Workspace

pytestmark = pytest.mark.django_db

User = get_user_model()


def _event_data(**overrides):
    now = timezone.now()
    data = {
        "name": "Scoped Event",
        "event_start": now + timedelta(days=1),
        "event_end": now + timedelta(days=1, hours=8),
    }
    data.update(overrides)
    return data


def test_create_event_defaults_to_creator_personal_workspace(organizer_user):
    personal = workspace_services.resolve_personal_workspace(organizer_user)

    event = create_event(organizer_user, _event_data())

    assert event.workspace_id == personal.workspace_id


def test_create_event_uses_an_explicit_authorized_workspace(organizer_user):
    personal = workspace_services.resolve_personal_workspace(organizer_user)

    event = create_event(organizer_user, _event_data(workspace=str(personal.workspace_uuid)))

    assert event.workspace_id == personal.workspace_id


def test_create_event_rejects_a_workspace_the_creator_cannot_use(organizer_user):
    other = User.objects.create_user(username="ws-other@e.com", email="ws-other@e.com")
    other_ws = workspace_services.resolve_personal_workspace(other)
    data = _event_data(workspace=str(other_ws.workspace_uuid))

    with pytest.raises(CTFValidationError):
        create_event(organizer_user, data)


def test_create_event_rejects_an_archived_workspace(organizer_user):
    personal = workspace_services.resolve_personal_workspace(organizer_user)
    Workspace.objects.filter(pk=personal.workspace_id).update(archived_at=timezone.now())
    data = _event_data(workspace=str(personal.workspace_uuid))

    with pytest.raises(CTFValidationError):
        create_event(organizer_user, data)


def test_event_workspace_scope_is_immutable_once_set(ctf_event):
    reloaded = CTFEvent.objects.get(pk=ctf_event.pk)
    assert reloaded.workspace_id is not None
    reloaded.workspace_id = reloaded.workspace_id + 12345

    with pytest.raises(ValidationError):
        reloaded.save()


def test_service_created_event_always_carries_a_scope(organizer_user):
    # The event-creation service always populates the scope even though the column
    # is nullable for legacy/direct-ORM rows, so every event created the supported
    # way is confinable.
    event = create_event(organizer_user, _event_data())

    assert event.workspace_id is not None


def test_created_event_scope_cannot_be_rebound_without_reload(organizer_user):
    # The instance returned by create_event() (never reloaded) must still reject a
    # workspace rebind (codex finding: from_db baseline gap).
    event = create_event(organizer_user, _event_data())
    event.workspace_id = event.workspace_id + 999

    with pytest.raises(ValidationError):
        event.save()


def test_deferred_load_event_scope_cannot_be_rebound(ctf_event):
    deferred = CTFEvent.objects.only("id", "name").get(pk=ctf_event.pk)
    deferred.workspace_id = 424242

    with pytest.raises(ValidationError):
        deferred.save()
