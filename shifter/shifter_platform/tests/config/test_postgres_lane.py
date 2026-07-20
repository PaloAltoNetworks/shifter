"""PostgreSQL-lane guardrail: prove Django actually resolved to PostgreSQL (#1524).

A healthy ``postgres`` service in CI does not prove the ORM used it — under the
old ``TESTING=1``-forces-SQLite behavior the service sat idle while every test
ran on SQLite. This ``postgres``-marked test asserts the resolved connection
vendor from *inside* the test process, so the PostgreSQL lane fails closed if
the backend selector ever regresses. Being ``postgres``-marked, it is excluded
from the SQLite lane (``-m "not postgres"``) and guarantees the fail-closed
marker guard in the root conftest always has at least one marked test to find.
"""

from __future__ import annotations

import pytest
from django.db import connection

pytestmark = [pytest.mark.postgres, pytest.mark.django_db]


def test_resolved_backend_is_postgresql():
    assert connection.vendor == "postgresql", (
        f"PostgreSQL lane resolved to {connection.vendor!r}; a healthy postgres "
        "service does not prove Django used it (#1524)."
    )
