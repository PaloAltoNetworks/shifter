"""Root pytest hooks — must set env before Django settings import (#948).

Also hosts the fail-closed PostgreSQL-lane marker harness (#1524): when the run
selects the real PostgreSQL backend (``TEST_DB_BACKEND=postgres``), the lane
must collect at least one ``postgres``-marked test and must fail if any selected
``postgres``-marked test is skipped. Keeping this in the canonical root harness
(rather than grepping pytest prose or a per-test ``skipif``) means the
production-semantics evidence cannot silently disappear.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from typing import Any

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")

# Imported after the pre-Django-import env setup above so ordering intent is clear.
import pytest

_POSTGRES_MARKER = "postgres"
# Nodeids of postgres-marked tests that actually produced a report (i.e. were
# selected and executed), and the subset that were skipped. Keyed off
# pytest_runtest_logreport — which the xdist controller receives for every test
# AFTER `-m` deselection — so the guard reflects what really ran, never a
# pre-deselection collection count (that ordering bug let a `-m 'not postgres'`
# run count marked tests, deselect them all, and still pass; #1524).
_ran_postgres_nodeids: set[str] = set()
_skipped_postgres_nodeids: set[str] = set()
_TESTDB_CREATION_LOCK = os.path.join(tempfile.gettempdir(), "shifter-postgres-testdb-create.lock")


def _postgres_lane() -> bool:
    """Whether this run targets the real PostgreSQL backend (#1524)."""
    return os.environ.get("TEST_DB_BACKEND", "").strip().lower() == "postgres"


def _is_primary_process(config: pytest.Config) -> bool:
    """True on the non-xdist main process or the xdist controller (not a worker).

    xdist workers carry a ``workerinput`` attribute and each only sees the reports
    of the tests they ran; the controller receives every worker's reports and owns
    the final exit code, so the guard verdict is computed there.
    """
    return not hasattr(config, "workerinput")


def _emit_step_summary(line: str) -> None:
    """Append a line to the GitHub step summary when running under Actions."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Track postgres-marked tests that ran (and which were skipped) (#1524)."""
    if not _postgres_lane():
        return
    if _POSTGRES_MARKER not in getattr(report, "keywords", {}):
        return
    _ran_postgres_nodeids.add(report.nodeid)
    if report.skipped:
        _skipped_postgres_nodeids.add(report.nodeid)


def _postgres_guard_failures() -> list[str]:
    """Fail-closed reasons for the PostgreSQL lane: zero marked ran, or any skipped."""
    failures: list[str] = []
    if not _ran_postgres_nodeids:
        failures.append("no postgres-marked tests ran (all deselected, skipped, or none collected)")
    if _skipped_postgres_nodeids:
        failures.append(f"{len(_skipped_postgres_nodeids)} postgres-marked test(s) skipped")
    return failures


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the PostgreSQL lane closed on the primary process when the marked
    evidence contract is violated (#1524)."""
    if not _postgres_lane() or not _is_primary_process(session.config):
        return
    _emit_step_summary(f"- postgres-marked tests executed: {len(_ran_postgres_nodeids)}")
    failures = _postgres_guard_failures()
    if failures:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        _emit_step_summary("- PostgreSQL lane fail-closed guard FAILED: " + "; ".join(failures))


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    """Surface the PostgreSQL lane fail-closed guard verdict (#1524)."""
    if not _postgres_lane() or not _is_primary_process(config):
        return
    for failure in _postgres_guard_failures():
        terminalreporter.write_line(f"ERROR: PostgreSQL lane fail-closed guard: {failure} (#1524)", red=True, bold=True)
    for nodeid in sorted(_skipped_postgres_nodeids):
        terminalreporter.write_line(f"  - skipped postgres-marked: {nodeid}", red=True)


@contextlib.contextmanager
def _testdb_creation_lock() -> Iterator[None]:
    """Serialize test-database creation/teardown across xdist workers (#1524).

    Concurrent ``CREATE DATABASE`` (and ``DROP DATABASE``) from parallel xdist
    workers contend on the shared ``pg_database`` catalog and fail with
    "tuple concurrently updated". An advisory ``fcntl`` file lock on a shared
    temp path serializes only that catalog-mutating window, so the workers still
    run their tests in parallel. Advisory POSIX locking is sufficient here — the
    PostgreSQL lane runs on Linux CI and Linux dev hosts.
    """
    import fcntl

    with open(_TESTDB_CREATION_LOCK, "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@pytest.fixture(scope="session")
def django_db_setup(
    request: pytest.FixtureRequest,
    django_test_environment: None,
    django_db_blocker: object,
    django_db_use_migrations: bool,
    django_db_keepdb: bool,
    django_db_createdb: bool,
    django_db_modify_db_settings: None,
) -> Iterator[None]:
    """Wrap pytest-django's ``django_db_setup`` to serialize DB creation (#1524).

    This does NOT reimplement the test-database lifecycle: it delegates entirely
    to pytest-django's stock generator (creation, migrations, per-worker
    ``_gw*`` naming, teardown). It only holds a cross-worker file lock around the
    stock fixture's setup and teardown phases on the PostgreSQL lane, eliminating
    the concurrent ``CREATE DATABASE`` race. On the SQLite lane it delegates with
    no lock — byte-for-byte identical to not overriding the fixture.
    """
    from pytest_django.fixtures import django_db_setup as _stock_django_db_setup

    stock = _stock_django_db_setup.__wrapped__(  # type: ignore[attr-defined]
        request,
        django_test_environment,
        django_db_blocker,
        django_db_use_migrations,
        django_db_keepdb,
        django_db_createdb,
        django_db_modify_db_settings,
    )
    if not _postgres_lane():
        yield from stock
        return

    with _testdb_creation_lock():
        next(stock)  # create + migrate the per-worker database under the lock
    try:
        yield  # tests run in parallel; the lock is released during the session
    finally:
        with _testdb_creation_lock():
            for _ in stock:  # drain teardown (drop, when not --reuse-db) under the lock
                pass
