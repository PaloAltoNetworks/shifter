"""Engine facade over the subnet-coordination routines (#1838).

The routines themselves are proven against real PostgreSQL in
``test_subnet_coordination_postgres.py``. What is left to pin here is the part of
the facade that runs on every backend: how a driver failure becomes a fixed
reason code, and -- more importantly -- which failures it refuses to translate.
A connection or infrastructure fault laundered into a domain reason code would
read to an operator as "the reservation was refused" when in fact nothing was
asked.

These drive the real facade functions and patch only the database boundary. The
patch lives in a fixture so each test body holds exactly one call that can throw.
"""

from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

import pytest
from django.db import connection

from engine.services import (
    read_subnet_reservation,
    release_subnet_reservation,
    reserve_subnet_cidrs,
)
from shared.subnet_coordination import (
    REASON_CONFLICT,
    REASON_EXHAUSTED,
    REASON_INVALID_REQUEST,
    REASON_OPERATION_NOT_PERMITTED,
    REASON_STALE_GENERATION,
    REASON_UNKNOWN_OPERATION,
    SubnetCoordinationError,
    build_reservation_request,
)

OPERATION_ID = str(uuid4())
REQUEST_ID = str(uuid4())


class _DriverError(Exception):
    """A driver error carrying a SQLSTATE, as psycopg raises it."""

    def __init__(self, sqlstate: str):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _FakeCursor:
    """The database boundary: it records statements and returns canned rows."""

    def __init__(self, *, rows=None, scalar=None, error=None):
        self._rows = rows or []
        self._scalar = scalar
        self._error = error
        self.executed: list[tuple] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._error is not None:
            raise self._error

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._scalar


class _Boundary:
    """Holds the cursor the patched connection hands out for one test."""

    cursor: _FakeCursor | None = None

    def use(self, cursor: _FakeCursor) -> _FakeCursor:
        self.cursor = cursor
        return cursor


@pytest.fixture
def boundary(monkeypatch):
    """Patch the Django connection's cursor -- the database boundary itself."""
    holder = _Boundary()

    @contextmanager
    def _factory():
        yield holder.cursor

    monkeypatch.setattr(connection, "cursor", _factory)
    return holder


def _request(**overrides):
    base = {
        "operation_id": OPERATION_ID,
        "request_id": REQUEST_ID,
        "network_id": "range-network-test",
        "network_cidr": "10.1.0.0/16",
        "prefix_length": 28,
        "subnets": ("0:attack", "1:victim"),
    }
    base.update(overrides)
    return build_reservation_request(**base)


class TestReserve:
    def test_returns_the_reserved_cidrs_in_ordinal_order(self, boundary):
        boundary.use(_FakeCursor(rows=[(2, "10.1.2.16/28"), (1, "10.1.2.0/28")]))

        result = reserve_subnet_cidrs(_request())

        assert result == ("10.1.2.0/28", "10.1.2.16/28")

    def test_sends_the_full_request_including_its_shape_fingerprint(self, boundary):
        cursor = boundary.use(_FakeCursor(rows=[(1, "10.1.2.0/28"), (2, "10.1.2.16/28")]))
        request = _request()

        reserve_subnet_cidrs(request)

        params = cursor.executed[0][1]
        assert params[-1] == request.shape_fingerprint
        assert params[1] == OPERATION_ID

    @pytest.mark.parametrize(
        ("sqlstate", "reason"),
        [
            ("SH001", REASON_CONFLICT),
            ("SH002", REASON_EXHAUSTED),
            ("SH003", REASON_STALE_GENERATION),
            ("SH004", REASON_UNKNOWN_OPERATION),
            ("SH005", REASON_INVALID_REQUEST),
            ("SH006", REASON_OPERATION_NOT_PERMITTED),
        ],
    )
    def test_maps_each_routine_refusal_to_its_reason_code(self, boundary, sqlstate, reason):
        boundary.use(_FakeCursor(error=_DriverError(sqlstate)))
        request = _request()

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(request)

        assert reason in str(exc.value)

    def test_does_not_translate_an_unrecognized_driver_failure(self, boundary):
        # 08006 is a connection failure. Translating it would tell an operator
        # the reservation was refused when it was never evaluated.
        boundary.use(_FakeCursor(error=_DriverError("08006")))
        request = _request()

        with pytest.raises(_DriverError):
            reserve_subnet_cidrs(request)

    def test_reads_the_sqlstate_through_a_wrapping_exception(self, boundary):
        # Django re-raises driver errors wrapped in its own exception class, so
        # the SQLSTATE lives on __cause__ rather than the exception itself.
        wrapper = RuntimeError("wrapped by the database layer")
        wrapper.__cause__ = _DriverError("SH001")
        boundary.use(_FakeCursor(error=wrapper))
        request = _request()

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(request)

        assert REASON_CONFLICT in str(exc.value)

    def test_a_short_batch_from_the_routine_fails_closed(self, boundary):
        # All-or-nothing: fewer rows than requested must not read as success.
        boundary.use(_FakeCursor(rows=[(1, "10.1.2.0/28")]))
        request = _request()

        with pytest.raises(SubnetCoordinationError):
            reserve_subnet_cidrs(request)


class TestRead:
    def test_returns_the_reservation_in_order(self, boundary):
        boundary.use(_FakeCursor(rows=[(2, "10.1.2.16/28"), (1, "10.1.2.0/28")]))

        result = read_subnet_reservation(operation_id=OPERATION_ID, request_id=REQUEST_ID)

        assert result == ("10.1.2.0/28", "10.1.2.16/28")

    def test_returns_empty_when_nothing_is_reserved(self, boundary):
        boundary.use(_FakeCursor(rows=[]))

        assert read_subnet_reservation(operation_id=OPERATION_ID, request_id=REQUEST_ID) == ()

    def test_maps_a_refusal_to_its_reason_code(self, boundary):
        boundary.use(_FakeCursor(error=_DriverError("SH003")))

        with pytest.raises(SubnetCoordinationError) as exc:
            read_subnet_reservation(operation_id=OPERATION_ID, request_id=REQUEST_ID)

        assert REASON_STALE_GENERATION in str(exc.value)

    def test_does_not_translate_an_unrecognized_driver_failure(self, boundary):
        boundary.use(_FakeCursor(error=_DriverError("08006")))

        with pytest.raises(_DriverError):
            read_subnet_reservation(operation_id=OPERATION_ID, request_id=REQUEST_ID)


class TestRelease:
    def test_returns_how_many_rows_were_released(self, boundary):
        boundary.use(_FakeCursor(scalar=(3,)))

        assert release_subnet_reservation(operation_id=OPERATION_ID, request_id=REQUEST_ID) == 3

    def test_treats_a_missing_row_count_as_nothing_released(self, boundary):
        boundary.use(_FakeCursor(scalar=None))

        assert release_subnet_reservation(operation_id=OPERATION_ID, request_id=REQUEST_ID) == 0

    def test_maps_a_refusal_to_its_reason_code(self, boundary):
        boundary.use(_FakeCursor(error=_DriverError("SH006")))

        with pytest.raises(SubnetCoordinationError) as exc:
            release_subnet_reservation(operation_id=OPERATION_ID, request_id=REQUEST_ID)

        assert REASON_OPERATION_NOT_PERMITTED in str(exc.value)

    def test_does_not_translate_an_unrecognized_driver_failure(self, boundary):
        boundary.use(_FakeCursor(error=_DriverError("08006")))

        with pytest.raises(_DriverError):
            release_subnet_reservation(operation_id=OPERATION_ID, request_id=REQUEST_ID)
