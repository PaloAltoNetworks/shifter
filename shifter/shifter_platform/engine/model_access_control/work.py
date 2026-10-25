"""Bound synchronous control work even after the HTTP caller has gone away."""

from __future__ import annotations

from collections.abc import Callable

from django.db import close_old_connections, connection

from shared.model_access.work import BoundedWork

_GENERAL = BoundedWork(8, name="model-control")
_LIFECYCLE = BoundedWork(4, name="model-lease")


class ControlWork:
    """No unbounded queue; lease/finalization work has independent capacity."""

    @staticmethod
    async def run[Result](function: Callable[[], Result], *, lifecycle: bool, database: bool = False) -> Result:
        work = _LIFECYCLE if lifecycle else _GENERAL
        return await work.run(lambda: _database_call(function) if database else function())


def _database_call[Result](function: Callable[[], Result]) -> Result:
    """Bound each database/lock wait; no transaction encloses external source I/O."""
    close_old_connections()
    try:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '1500ms'")
                cursor.execute("SET lock_timeout = '1000ms'")
        return function()
    finally:
        connection.close()
