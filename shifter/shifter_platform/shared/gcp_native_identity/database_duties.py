"""Reconcile standard PostgreSQL duties under the installation's schema owner."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from shared.gcp_native_identity import NATIVE_APPLICATION_WORKLOADS, NATIVE_POLICY_WORKLOADS

_LEGACY_RUNTIME_LOGINS = ("portal_runtime", "provisioner_runtime", "guacamole_admin")


class _DutyCursor(Protocol):
    """The SQL operations shared by Django's wrapper and a psycopg cursor."""

    def execute(self, query: str | sql.SQL | sql.Composed, params: Sequence[str] | None = None, /) -> object: ...

    def fetchone(self) -> TupleRow | None: ...

    def fetchall(self) -> list[TupleRow]: ...


def _required_row(cursor: _DutyCursor) -> TupleRow:
    """Fail closed when a required role or privilege query returns no row."""
    row = cursor.fetchone()
    if row is None:
        raise ValueError("Database duty query returned no result")
    return row


def _role_exists(cursor: _DutyCursor, role: str) -> bool:
    """Return whether the PostgreSQL instance registers this role."""
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
    return cursor.fetchone() is not None


def _assert_narrow_login(cursor: _DutyCursor, login: str, *, provisioner: bool = False) -> None:
    """Reject inherited administrative authority on an application runtime login."""
    cursor.execute(
        """SELECT EXISTS (
            SELECT FROM pg_roles r WHERE pg_has_role(%s, r.oid, 'MEMBER')
            AND (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls
                 OR has_schema_privilege(r.oid, 'public', 'CREATE')
                 OR has_database_privilege(r.oid, current_database(), 'CREATE'))
        )""",
        [login],
    )
    if _required_row(cursor)[0]:
        raise ValueError("Runtime SQL login has unexpected inherited or owner authority")
    if provisioner:
        cursor.execute("SELECT has_table_privilege(%s, 'django_migrations', 'INSERT,UPDATE,DELETE')", [login])
        if _required_row(cursor)[0]:
            raise ValueError("Provisioner SQL login has unexpected application DML authority")


def _reconcile_legacy_runtime_duties(cursor: _DutyCursor) -> None:
    """Remove documented provider defaults from the designated runtime logins."""
    for role in _LEGACY_RUNTIME_LOGINS:
        if not _role_exists(cursor, role):
            continue
        cursor.execute(sql.SQL("ALTER ROLE {} NOCREATEROLE NOCREATEDB").format(sql.Identifier(role)))
        if _role_exists(cursor, "cloudsqlsuperuser"):
            cursor.execute(sql.SQL("REVOKE cloudsqlsuperuser FROM {}").format(sql.Identifier(role)))
        _assert_narrow_login(cursor, role, provisioner=role == "provisioner_runtime")


def _grant_native_application_duties(cursor: _DutyCursor, native_users: Mapping[str, str]) -> None:
    """Attach each native application identity to its existing database duty."""
    for workload in NATIVE_APPLICATION_WORKLOADS:
        if workload not in native_users:
            continue
        login = native_users[workload]
        if not _role_exists(cursor, login):
            raise ValueError("Native SQL login must first be registered by the owning Terraform module")
        duty = "provisioner_lambda" if workload == "provisioner" else "portal_runtime"
        cursor.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(duty), sql.Identifier(login)))
        _assert_narrow_login(cursor, login, provisioner=workload == "provisioner")


def _assert_policy_application_isolation(cursor: _DutyCursor, native_users: Mapping[str, str]) -> None:
    """Deny policy identities effective application database authority."""
    for workload in NATIVE_POLICY_WORKLOADS:
        if workload in native_users:
            _assert_narrow_login(cursor, native_users[workload], provisioner=True)
            cursor.execute("SELECT has_database_privilege(%s, current_database(), 'CONNECT')", [native_users[workload]])
            if _required_row(cursor)[0]:
                raise ValueError("Policy database identities must not connect to the application database")


def reconcile_application_duties(cursor: _DutyCursor, native_users: Mapping[str, str]) -> None:
    """Run after application migrations, never as a runtime database login."""
    cursor.execute("""SELECT pg_has_role(current_user, relowner, 'USAGE')
                      FROM pg_class WHERE oid = 'public.django_migrations'::regclass""")
    if cursor.fetchone() != (True,):
        raise ValueError("Database duty reconciliation requires the application schema owner")
    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    _reconcile_legacy_runtime_duties(cursor)
    cursor.execute("SELECT current_database()")
    database = sql.Identifier(_required_row(cursor)[0])
    cursor.execute(sql.SQL("REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC").format(database))
    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO portal_runtime, provisioner_lambda").format(database))
    _grant_native_application_duties(cursor, native_users)
    _assert_policy_application_isolation(cursor, native_users)


def _prepare_policy_owner(cursor: _DutyCursor) -> str:
    """Create and qualify the dedicated owner without changing application ownership."""
    owner = "shifter_openfga_owner"
    if not _role_exists(cursor, owner):
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(owner)))
    cursor.execute(
        """SELECT rolcanlogin OR rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls
                      OR EXISTS (SELECT FROM pg_auth_members WHERE member = pg_roles.oid)
                      FROM pg_roles WHERE rolname = %s""",
        [owner],
    )
    owner_state = cursor.fetchone()
    if owner_state is None or owner_state[0]:
        raise ValueError("Policy database owner role has unexpected external authority")
    cursor.execute("SELECT current_user")
    bootstrap_row = cursor.fetchone()
    if bootstrap_row is None:
        raise ValueError("Policy database bootstrap identity could not be resolved")
    bootstrap = bootstrap_row[0]
    cursor.execute(sql.SQL("GRANT {} TO {} WITH ADMIN OPTION").format(sql.Identifier(owner), sql.Identifier(bootstrap)))
    cursor.execute(sql.SQL("ALTER DATABASE openfga OWNER TO {}").format(sql.Identifier(owner)))
    cursor.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(owner)))
    cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    cursor.execute("REVOKE CONNECT, TEMPORARY ON DATABASE openfga FROM PUBLIC")
    return owner


def _assert_no_application_policy_access(cursor: _DutyCursor, native_users: Mapping[str, str]) -> None:
    """Reject explicit or inherited application access to the policy database."""
    application_logins = (
        set(_LEGACY_RUNTIME_LOGINS)
        | {"provisioner_lambda", "mcp_user"}
        | {native_users[workload] for workload in NATIVE_APPLICATION_WORKLOADS if workload in native_users}
    )
    for login in application_logins:
        if _role_exists(cursor, login):
            cursor.execute("SELECT has_database_privilege(%s, 'openfga', 'CONNECT,CREATE,TEMPORARY')", [login])
            privilege = cursor.fetchone()
            if privilege is None or privilege[0]:
                raise ValueError("Application SQL duties must not inherit access to the policy database")


def _transfer_released_policy_tables(cursor: _DutyCursor, owner: str) -> None:
    """Transfer only released datastore tables in the dedicated policy database."""
    # Scope upgrades to released datastore tables in this database. A global
    # REASSIGN OWNED would also move other databases owned by the bootstrap
    # login, so it must never be used here.
    cursor.execute(
        "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
    )
    tables = {row[0] for row in cursor.fetchall()}
    released_tables = {"store", "authorization_model", "assertion", "tuple", "changelog", "goose_db_version"}
    if tables - released_tables:
        raise ValueError("Policy database contains objects outside the released datastore")
    for table in tables:
        cursor.execute(
            sql.SQL("ALTER TABLE public.{} OWNER TO {}").format(sql.Identifier(table), sql.Identifier(owner))
        )


def _grant_policy_migration_duties(cursor: _DutyCursor, owner: str, migrator: str) -> None:
    """Grant policy ownership and group administration to its migration identity."""
    cursor.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(owner), sql.Identifier(migrator)))
    for duty in ("shifter_openfga_runtime", "shifter_openfga_admin"):
        if not _role_exists(cursor, duty):
            cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(duty)))
        cursor.execute(
            sql.SQL("GRANT {} TO {} WITH ADMIN OPTION").format(sql.Identifier(duty), sql.Identifier(migrator))
        )


def reconcile_policy_owner(connection_parameters: dict[str, Any], native_users: Mapping[str, str]) -> None:
    """Bootstrap the dedicated policy owner; API duties follow released migrations."""
    if not NATIVE_POLICY_WORKLOADS.issubset(native_users):
        return
    parameters = {**connection_parameters, "dbname": "openfga", "connect_timeout": 10}
    with psycopg.connect(**parameters) as connection, connection.cursor() as cursor:
        owner = _prepare_policy_owner(cursor)
        _assert_no_application_policy_access(cursor, native_users)
        _transfer_released_policy_tables(cursor, owner)
        _grant_policy_migration_duties(cursor, owner, native_users["openfga-migrator"])
