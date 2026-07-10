"""Directory-scoped PostgreSQL database redirect for CTF submission
concurrency tests (issue #1182).

``tests/conftest.py`` sets ``TESTING=1`` unconditionally, and
``config._database_settings._build_databases()`` returns a SQLite database
whenever ``TESTING=1`` is set. SQLite has no real row-level locking, so it
cannot prove that ``ctf.services.submission.submit_flag()``'s
``select_for_update()`` guard (#1135, #1137) actually serializes concurrent
requests — that requires a real PostgreSQL backend.

This conftest overrides pytest-django's session-scoped ``django_db_setup``
fixture, but *only* for tests collected under ``tests/ctf/test_services/``
(pytest resolves a fixture to the closest conftest on the requesting test's
path). It is env-gated on ``TEST_DB_BACKEND=postgres``:

- When unset (the default — used by every normal SQLite run, including every
  *other* module in this same directory, e.g. ``test_submission.py``), this
  override is completely inert: it delegates to pytest-django's stock
  ``django_db_setup`` implementation via ``__wrapped__`` so behavior is
  byte-for-byte identical to not having this file at all.
- When ``TEST_DB_BACKEND=postgres``, it repoints
  ``settings.DATABASES["default"]`` at a PostgreSQL instance described by the
  ``DB_HOST`` / ``DB_PORT`` / ``DB_NAME`` / ``DB_USER`` / ``DB_PASSWORD`` env
  vars and applies migrations directly against it with
  ``call_command("migrate", "--noinput")``. This talks to the target database
  as-is (no Django "test_<name>" wrapper database, no ``setup_databases()``
  create/destroy dance) — the CI Postgres service database is used directly.
  ``TESTING`` stays ``=1`` so unrelated test-mode settings (static-file
  storage, etc.) are unaffected; only the database connection is redirected.

This repo's pytest ``addopts`` run under ``pytest-xdist`` (``-n auto``) by
default, and ``--dist loadscope`` groups by test class, so this module's 3
test classes can land on 3 different worker *processes* running
concurrently. pytest-django's own stock fixture handles that by suffixing
each worker's test database name with its xdist worker id
(``_gw0``/``_gw1``/...) via ``django_db_modify_db_settings``; since this
override replaces ``DATABASES["default"]`` wholesale it must reapply that
suffix itself (`_worker_database_name`), and — unlike SQLite, which
auto-creates its file — explicitly ``CREATE DATABASE`` the per-worker
PostgreSQL database if it doesn't exist yet (`_ensure_database_exists`)
before migrating it. Without this, concurrent workers would migrate/flush
the *same* physical database and corrupt each other's fixtures mid-test.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest
from pytest_django.fixtures import django_db_setup as _stock_django_db_setup

if TYPE_CHECKING:
    from pytest_django import DjangoDbBlocker


def _postgres_backend_requested() -> bool:
    """Whether this run should redirect the ORM at a real PostgreSQL instance."""
    return os.environ.get("TEST_DB_BACKEND", "").strip().lower() == "postgres"


def _worker_database_name() -> str:
    """Base DB name, suffixed with the xdist worker id when running distributed.

    Mirrors pytest-django's own ``_gw0``/``_gw1``/... per-worker test-database
    naming (see ``django_db_modify_db_settings_xdist_suffix`` in
    ``pytest_django.fixtures``) so concurrent workers under ``--dist
    loadscope`` each get an isolated PostgreSQL database instead of racing
    each other's migrate/flush/create calls against the same one.
    """
    base_name = os.environ.get("DB_NAME", "shifter")
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if not worker_id or worker_id == "master":
        return base_name
    return f"{base_name}_{worker_id}"


def _postgres_database_config() -> dict[str, object]:
    """Build the DATABASES["default"] entry from the env vars CI supplies.

    Defaults mirror the values the ``shifter-platform-tests`` CI job's
    ``postgres:16`` service is created with, so a developer can run the same
    command locally against a plain ``docker run postgres:16`` container
    without exporting anything beyond ``TEST_DB_BACKEND=postgres``.
    """
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _worker_database_name(),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"connect_timeout": 10},
    }


def _ensure_database_exists(config: dict[str, object]) -> None:
    """`CREATE DATABASE` the target database if it doesn't exist yet.

    PostgreSQL, unlike SQLite, refuses a connection to a database that
    doesn't exist — needed here because each xdist worker targets its own
    (`_worker_database_name`) database, which is never created by anything
    else in this flow (no ``setup_databases()`` create/destroy dance; see
    module docstring). Connects to the server's default ``postgres``
    maintenance database to issue the (autocommit-required) `CREATE
    DATABASE`.
    """
    import psycopg
    from psycopg import sql

    admin_conn = psycopg.connect(
        host=config["HOST"],
        port=config["PORT"],
        user=config["USER"],
        password=config["PASSWORD"],
        dbname="postgres",
        autocommit=True,
    )
    try:
        with admin_conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (config["NAME"],))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(config["NAME"])))
    finally:
        admin_conn.close()


@pytest.fixture(scope="session")
def django_db_setup(
    request: pytest.FixtureRequest,
    django_test_environment: None,
    django_db_blocker: DjangoDbBlocker,
    django_db_use_migrations: bool,
    django_db_keepdb: bool,
    django_db_createdb: bool,
    django_db_modify_db_settings: None,
) -> Generator[None, None, None]:
    """Override ``django_db_setup`` for ``tests/ctf/test_services/`` only.

    Inert unless ``TEST_DB_BACKEND=postgres`` — see module docstring.
    """
    if not _postgres_backend_requested():
        yield from _stock_django_db_setup.__wrapped__(
            request,
            django_test_environment,
            django_db_blocker,
            django_db_use_migrations,
            django_db_keepdb,
            django_db_createdb,
            django_db_modify_db_settings,
        )
        return

    from django.conf import settings
    from django.core.management import call_command
    from django.db import connections

    # By the time this fixture runs, Django app loading has already opened
    # (thread-locally, on this thread) a "default" DatabaseWrapper pointing
    # at the pre-override SQLite settings. `close_all()` only closes its
    # underlying DB-API connection — the wrapper object itself stays cached
    # in `connections._connections`, and a wrapper reconnects using the
    # `settings_dict` it captured at *construction* time, not a live lookup.
    # Left in place, every later query on this thread (including
    # `migrate` below and this fixture's own callers) would silently
    # reconnect to SQLite instead of the PostgreSQL config assigned below.
    # Evicting it forces the next `connections["default"]` access to build a
    # fresh wrapper from current settings.
    connections.close_all()
    if hasattr(connections._connections, "default"):
        del connections["default"]

    # `ConnectionHandler.settings` is a `cached_property`: the first time
    # it's touched, Django's `configure_settings()` fills in required
    # defaults (`TIME_ZONE`, `CONN_HEALTH_CHECKS`, `ATOMIC_REQUESTS`, `TEST`,
    # etc.) into the *current* DATABASES dict and caches that exact dict
    # object. Dropping the cached value here forces it to recompute — and
    # re-fill those defaults — against our PostgreSQL replacement dict
    # below, instead of silently keeping the stale (defaulted) SQLite dict.
    connections.__dict__.pop("settings", None)

    postgres_config = _postgres_database_config()
    settings.DATABASES["default"] = postgres_config

    # Drop the cache again: assigning a new dict for "default" above doesn't
    # itself invalidate an already-cached `ConnectionHandler.settings`.
    connections.__dict__.pop("settings", None)

    with django_db_blocker.unblock():
        _ensure_database_exists(postgres_config)
        call_command("migrate", "--noinput")

    yield
