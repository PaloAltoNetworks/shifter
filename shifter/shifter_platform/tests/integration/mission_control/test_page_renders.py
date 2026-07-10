"""Authenticated page-render query-budget tests (#924, TEST-7).

These render the authenticated pages that carry the event load through the real
Django request/response stack with ``django.test.Client`` and count the actual
SQL queries with ``CaptureQueriesContext`` — no ``render`` patching, no mocked
context processors. Each budget is an exact, named integer: a regression that
adds a query (the #898 / #852 per-render cost concern) fails the assertion and
must be justified by bumping the number deliberately.

Every authenticated Mission Control render runs the four context processors
(``active_range``, ``terminal_cdn_assets``, ``user_permissions``,
``ctf_navigation``); the dashboard/terminal budgets pin that shared cost, the
active-range case pins the range-projection overhead, and the CTF case pins a
real participant page.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

User = get_user_model()

# Exact per-page query budgets. Bump deliberately (with justification) when a
# real change adds queries; an accidental regression must fail here first.
#
# Tightened by #898: request-scoped group caching collapses the five per-render
# auth_user_groups lookups to one, select_related("agent", "request") removes the
# get_active_range FK N+1, and the full active-range payload is now built only on
# the terminal render — so non-terminal pages pay a single cheap has_active_range
# query instead of the runtime-IP / scenario / instance-context projection.
DASHBOARD_NO_RANGE_BUDGET = 4
DASHBOARD_ACTIVE_RANGE_BUDGET = 4
TERMINAL_BUDGET = 4
TERMINAL_ACTIVE_RANGE_BUDGET = 6
CTF_PARTICIPANT_DASHBOARD_BUDGET = 16


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="render-user@example.com",
        email="render-user@example.com",
        password="render-pass-123",
    )


@pytest.fixture
def client_for(db):
    """Factory: a logged-in client (with OIDC session) for a given user."""

    def _client(user) -> Client:
        client = Client()
        client.force_login(user)
        session = client.session
        session["oidc_id_token_expiration"] = time.time() + 3600
        session.save()
        return client

    return _client


@pytest.fixture
def active_range(db, user):
    """Seed a non-deleted CMS range so ``get_active_range`` returns a context."""
    from cms.models import RangeInstance
    from cms.models import Request as CMSRequest
    from shared.enums import RequestType

    request = CMSRequest.objects.create(
        request_id=uuid.uuid4(),
        request_type=RequestType.RANGE.value,
        user=user,
    )
    return RangeInstance.objects.create(
        request=request,
        scenario_id="test_scenario",
        user_id=user.id,
        status="ready",
    )


@pytest.fixture
def ctf_participant(db, user):
    """Make ``user`` an active CTF participant with an active event selected."""
    from ctf.enums import ParticipantStatus
    from ctf.models import CTFEvent, CTFParticipant
    from management.services import set_active_ctf_event
    from shared.auth import CTF_PARTICIPANT_GROUP

    event = CTFEvent.objects.create(
        name="Render Test Event",
        created_by=user,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=2),
    )
    participant = CTFParticipant.objects.create(
        event=event,
        user=user,
        email=user.email,
        name="Render Participant",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    user.groups.add(group)
    set_active_ctf_event(user, event.id)
    return participant


def _render_query_count(client: Client, url: str):
    """Return (response, query_count) for a GET, capturing only the render."""
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    return response, len(ctx.captured_queries)


@pytest.fixture(autouse=True)
def _real_context_processors():
    """Pin the real context processors for these exact-count budgets.

    Django caches the resolved context-processor callables on each template
    ``Engine`` (a ``cached_property``). Several ctf view suites patch the
    context processors by module path (``mission_control.context_processors
    .active_range``, ``shared.context_processors.user_permissions``,
    ``ctf.context_processors.ctf_navigation``) to isolate their view tests; if
    one of those patched renders is the first to warm a cold ``Engine`` on a
    pytest-xdist worker, the *mocked* processors get cached process-wide and
    survive the ``with patch`` block — so later renders silently skip those
    processors' queries and every exact-count budget on the worker fails (the
    measured count drops, e.g. 4 -> 2). Dropping the cached resolution before
    and after each budget test forces re-resolution against the live (real,
    unpatched) module attributes, so the budgets are deterministic regardless of
    worker scheduling; clearing on teardown also leaves the next test a cold
    cache so a ctf suite that follows can still apply its own patch. The
    underlying ctf-suite fragility (relying on a cold Engine cache) is tracked
    for the ctf decomposition.
    """
    from django.template import engines

    def _reset() -> None:
        for backend in engines.all():
            engine = getattr(backend, "engine", None)
            if engine is not None:
                engine.__dict__.pop("template_context_processors", None)

    _reset()
    yield
    _reset()


@pytest.mark.django_db
class TestPageRenderQueryBudgets:
    """Numeric per-render query budgets for authenticated pages."""

    def test_dashboard_no_active_range_budget(self, user, client_for):
        client = client_for(user)
        response, queries = _render_query_count(client, "/mission-control/")

        assert response.status_code == 200
        assert queries == DASHBOARD_NO_RANGE_BUDGET

    def test_dashboard_active_range_budget(self, user, client_for, active_range):
        client = client_for(user)
        response, queries = _render_query_count(client, "/mission-control/")

        assert response.status_code == 200
        assert queries == DASHBOARD_ACTIVE_RANGE_BUDGET

    def test_terminal_budget(self, user, client_for):
        client = client_for(user)
        response, queries = _render_query_count(client, "/mission-control/terminal/")

        assert response.status_code == 200
        assert queries == TERMINAL_BUDGET

    def test_terminal_active_range_budget(self, user, client_for, active_range):
        """The terminal render is the one page that still builds the full
        active-range payload (#898 terminal_full tier); this pins its budget so
        the FK/runtime-IP/scenario work cannot silently regress or migrate to
        non-terminal pages."""
        client = client_for(user)
        response, queries = _render_query_count(client, "/mission-control/terminal/")

        assert response.status_code == 200
        assert queries == TERMINAL_ACTIVE_RANGE_BUDGET

    def test_ctf_participant_dashboard_budget(self, user, client_for, ctf_participant):
        client = client_for(user)
        response, queries = _render_query_count(client, "/ctf/")

        assert response.status_code == 200
        assert queries == CTF_PARTICIPANT_DASHBOARD_BUDGET
