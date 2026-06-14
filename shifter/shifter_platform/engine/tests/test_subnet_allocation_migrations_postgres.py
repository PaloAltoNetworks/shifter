"""PostgreSQL migration proof for SubnetAllocation schema evolution."""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 -- test harness shells out to fixed local docker/python binaries only
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
PLATFORM_DIR = REPO_ROOT / "shifter" / "shifter_platform"
POSTGRES_IMAGE = "postgres:16-alpine"
POSTGRES_DATABASE = "shifter"
POSTGRES_PASSWORD = "postgres"  # nosec B105 -- disposable local test container credential
DJANGO_TEST_SECRET_KEY = "test-secret-key"  # nosec B105 -- disposable local Django test setting
DOCKER_BIN = shutil.which("docker") or "docker"
PYTHON_BIN = shutil.which("python3") or "python3"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603 -- args are fixed binary paths and test-controlled constants
        [DOCKER_BIN, *args],
        check=check,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def _wait_for_postgres(container_name: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = _docker(
            "exec",
            container_name,
            "pg_isready",
            "-h",
            "127.0.0.1",
            "-U",
            "postgres",
            "-d",
            "postgres",
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise TimeoutError(f"PostgreSQL container {container_name} did not become ready in time")


def _docker_psql(container_name: str, database: str, sql: str) -> str:
    result = _docker(
        "exec",
        "-e",
        "PGPASSWORD=postgres",
        container_name,
        "psql",
        "-h",
        "127.0.0.1",
        "-U",
        "postgres",
        "-d",
        database,
        "-At",
        "-c",
        sql,
    )
    return result.stdout.strip()


def _run_manage_py(database_name: str, port: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "DJANGO_SECRET_KEY": DJANGO_TEST_SECRET_KEY,
            "DJANGO_DEBUG": "true",
            "SITE_URL": "http://localhost",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": port,
            "DB_NAME": database_name,
            "DB_USER": "postgres",
            "DB_PASSWORD": POSTGRES_PASSWORD,
            "FIELD_ENCRYPTION_KEY": "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=",
        }
    )
    return subprocess.run(  # noqa: S603  # nosec B603 -- manage.py invocation is fixed and test-controlled
        [PYTHON_BIN, "manage.py", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=PLATFORM_DIR,
        env=env,
    )


def _assert_schema_after_0019(container_name: str, database_name: str) -> None:
    assert _docker_psql(
        container_name,
        database_name,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'engine_subnetallocation'
        ORDER BY column_name;
        """,
    ).splitlines() == [
        "cidr",
        "created_at",
        "id",
        "range_id",
        "request_id",
        "subnet_size",
        "vpc_id",
    ]
    assert (
        _docker_psql(
            container_name,
            database_name,
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'engine_subnetallocation'::regclass
              AND conname = 'unique_cidr_per_vpc';
            """,
        )
        == "unique_cidr_per_vpc"
    )


def _assert_schema_after_0020(container_name: str, database_name: str) -> None:
    _assert_schema_after_0019(container_name, database_name)
    assert (
        _docker_psql(
            container_name,
            database_name,
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'engine_subnetallocation'
              AND column_name = 'id';
            """,
        )
        == "bigint"
    )
    assert (
        _docker_psql(
            container_name,
            database_name,
            """
            SELECT column_default
            FROM information_schema.columns
            WHERE table_name = 'engine_subnetallocation'
              AND column_name = 'range_id';
            """,
        )
        == "0"
    )
    assert (
        _docker_psql(
            container_name,
            database_name,
            """
            SELECT column_default
            FROM information_schema.columns
            WHERE table_name = 'engine_subnetallocation'
              AND column_name = 'request_id';
            """,
        )
        == "''::character varying"
    )


def _prepare_migration_prerequisites(port: str) -> None:
    """Create non-engine tables referenced by engine data migrations."""

    _run_manage_py(POSTGRES_DATABASE, port, "migrate", "cms", "--noinput")


@pytest.fixture(scope="module")
def postgres_container() -> Iterator[tuple[str, str]]:
    """Start a disposable PostgreSQL container for migration-proof tests."""

    container_name = f"shifter-migrations-{uuid.uuid4().hex[:10]}"
    _docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        container_name,
        "-e",
        "POSTGRES_PASSWORD=postgres",
        "-p",
        "127.0.0.1::5432",
        POSTGRES_IMAGE,
    )
    try:
        _wait_for_postgres(container_name)
        port_mapping = _docker("port", container_name, "5432/tcp").stdout.strip()
        port = port_mapping.rsplit(":", maxsplit=1)[-1]
        _docker_psql(
            container_name,
            "postgres",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'provisioner_lambda') THEN
                    CREATE ROLE provisioner_lambda;
                END IF;
            END
            $$;
            """,
        )
        yield container_name, port
    finally:
        _docker("rm", "-f", container_name, check=False)


def _reset_database(container_name: str) -> None:
    _docker_psql(
        container_name,
        "postgres",
        f'DROP DATABASE IF EXISTS "{POSTGRES_DATABASE}" WITH (FORCE);',
    )
    _docker_psql(
        container_name,
        "postgres",
        f'CREATE DATABASE "{POSTGRES_DATABASE}";',
    )


def test_engine_migrations_reach_0020_from_zero(postgres_container: tuple[str, str]) -> None:
    container_name, port = postgres_container
    _reset_database(container_name)
    _prepare_migration_prerequisites(port)

    _run_manage_py(POSTGRES_DATABASE, port, "migrate", "engine", "0020", "--noinput")
    _assert_schema_after_0020(container_name, POSTGRES_DATABASE)

    shell_result = _run_manage_py(
        POSTGRES_DATABASE,
        port,
        "shell",
        "-c",
        (
            "from engine.models import SubnetAllocation; "
            "obj = SubnetAllocation.objects.create("
            "vpc_id='vpc-1', cidr='10.0.0.0/24', subnet_size=24, range_id=7, request_id='req-1'"
            "); "
            "print(obj.id); "
            "print(obj.created_at is not None)"
        ),
    )
    assert "True" in shell_result.stdout


def test_engine_migrations_resume_cleanly_from_0019(postgres_container: tuple[str, str]) -> None:
    container_name, port = postgres_container
    _reset_database(container_name)
    _prepare_migration_prerequisites(port)

    _run_manage_py(POSTGRES_DATABASE, port, "migrate", "engine", "0019", "--noinput")
    _assert_schema_after_0019(container_name, POSTGRES_DATABASE)

    _run_manage_py(POSTGRES_DATABASE, port, "migrate", "engine", "0020", "--noinput")
    _assert_schema_after_0020(container_name, POSTGRES_DATABASE)
