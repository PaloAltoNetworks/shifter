"""PostgreSQL concurrency proof for ``cms.services.create_range()`` (#307).

``create_range()`` reserves the single active-range slot for a
``(user_id, range_source)`` inside ``transaction.atomic()`` and relies on the
partial unique constraint ``uq_rangeinstance_active_per_user_source`` as the
race-proof backstop behind the friendly ``_assert_no_active_range`` pre-check.
``tests/cms/test_services_range.py`` and ``tests/cms/test_models_range_instance.py``
prove the *sequential* shape and the constraint itself, but SQLite -- the default
test backend -- serializes writes and cannot prove that concurrent launches are
actually admitted at most once.

This module races real threads, each with its own DB connection, against a real
PostgreSQL instance (selected by the settings-owned ``TEST_DB_BACKEND=postgres``
selector plus pytest-django's native test-database lifecycle) to prove that N
simultaneous ``create_range()`` calls for one ``(user, source)`` resolve to
exactly one active range, every loser gets the authored active-range ``CMSError``,
and no orphan CMS ``Request`` row is left behind by a rolled-back reservation.

Marked ``postgres`` so the default SQLite suite excludes it (``-m "not postgres"``),
and ``django_db(transaction=True)`` so writes are real commits visible across
threads/connections (not rolled back inside a shared wrapping transaction).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from cms import services
from cms.exceptions import CMSError
from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from shared.enums import RangeSource

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.django_db(transaction=True),
]

User = get_user_model()


@pytest.fixture
def user(db):
    from workspaces.services import resolve_personal_workspace

    result = User.objects.create_user(username="cms-race@example.com", email="cms-race@example.com")
    resolve_personal_workspace(result)
    return result


def _race(user_id, scenario_id, agent_id, barrier):
    """Call ``create_range`` from a worker thread, synchronized on ``barrier``.

    Returns ``("ok", ctx)`` on success or ``("error", exc)`` on rejection so the
    caller can classify every outcome without exceptions crossing thread
    boundaries. Each worker gets its own thread-local DB connection, closed
    before returning so ThreadPoolExecutor workers do not leak connections.
    """
    # Django connections are thread-local; re-fetch the user inside the worker.
    launcher = User.objects.get(pk=user_id)
    barrier.wait(timeout=10)
    try:
        ctx = services.create_range(launcher, scenario_id, {"windows": agent_id})
    except CMSError as exc:
        return ("error", exc)
    finally:
        connection.close()
    return ("ok", ctx)


class TestConcurrentCreateRange:
    RACERS = 6

    def test_exactly_one_active_range_wins(self, user, make_agent, hydratable_scenario):
        agent = make_agent(user)
        barrier = threading.Barrier(self.RACERS)

        with ThreadPoolExecutor(max_workers=self.RACERS) as executor:
            futures = [
                executor.submit(_race, user.id, hydratable_scenario.scenario_id, agent.id, barrier)
                for _ in range(self.RACERS)
            ]
            outcomes = [future.result(timeout=60) for future in futures]

        wins = [o for o in outcomes if o[0] == "ok"]
        losses = [o for o in outcomes if o[0] == "error"]

        assert len(wins) == 1, "exactly one concurrent launch should be admitted"
        assert len(losses) == self.RACERS - 1
        assert all("already have an active range" in str(exc) for _, exc in losses)

        # Exactly one active Mission Control range for the user, and no orphan
        # Request rows from the losers' rolled-back reservations.
        active = RangeInstance.objects.filter(user_id=user.id, range_source=RangeSource.MISSION_CONTROL.value)
        assert active.count() == 1
        assert CmsRequest.objects.filter(user=user).count() == 1
