# Revoke the provisioner's residual domain-table and outbox grants (ADR-043 phase 7,
# #1839).
#
# The cyberscript range provision/destroy path still writes a reviewed allowlist of
# domain columns directly; everything else — especially the range-event outbox the
# provisioner used to INSERT into — is revoked here. Reconcile against the live
# catalog for objects that may already be gone; naming an absent relation in a
# REVOKE is a hard error in PostgreSQL (see mission_control 0042 for the pattern).
#
# Deliberately narrow: do not touch the operation-boundary grants (0036), the
# coordination-routine EXECUTE grants (0046), or the cyberscript writers listed in
# the phase-7 allowlist. Historical grant migrations are evidence, not edit targets.

from django.db import migrations

_ROLE = "provisioner_lambda"

_REVOKE_ENGINE_TABLES = ("engine_subnet",)

_REVOKE_ENGINE_TABLE_PRIVS = ("SELECT",)


def _role_exists(schema_editor, role: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        return cursor.fetchone() is not None


def _table_exists(schema_editor, table: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
            """,
            [table],
        )
        return cursor.fetchone() is not None


def _sequence_exists(schema_editor, sequence: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.sequences
            WHERE sequence_schema = 'public' AND sequence_name = %s
            """,
            [sequence],
        )
        return cursor.fetchone() is not None


def _applies(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql" and _role_exists(schema_editor, _ROLE)


def _revoke_outbox(apps, schema_editor):
    if not _applies(schema_editor):
        return
    if not _table_exists(schema_editor, "engine_range_event_outbox"):
        return
    schema_editor.execute(f"REVOKE INSERT, SELECT ON engine_range_event_outbox FROM {_ROLE};")  # nosec B608
    schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.engine_range_event_outbox_id_seq FROM {_ROLE};")  # nosec B608


def _grant_outbox(apps, schema_editor):
    if not _applies(schema_editor):
        return
    if _table_exists(schema_editor, "engine_range_event_outbox"):
        schema_editor.execute(
            f"""
            GRANT INSERT ON engine_range_event_outbox TO {_ROLE};
            GRANT SELECT ON engine_range_event_outbox TO {_ROLE};
            """
        )  # nosec B608
    if _sequence_exists(schema_editor, "engine_range_event_outbox_id_seq"):
        schema_editor.execute(f"GRANT USAGE ON SEQUENCE engine_range_event_outbox_id_seq TO {_ROLE};")  # nosec B608


def _revoke_engine_table_reads(apps, schema_editor):
    if not _applies(schema_editor):
        return
    for table in _REVOKE_ENGINE_TABLES:
        if not _table_exists(schema_editor, table):
            continue
        privs = ", ".join(_REVOKE_ENGINE_TABLE_PRIVS)
        schema_editor.execute(f"REVOKE {privs} ON {table} FROM {_ROLE};")  # nosec B608


def _grant_engine_table_reads(apps, schema_editor):
    if not _applies(schema_editor):
        return
    for table in _REVOKE_ENGINE_TABLES:
        if not _table_exists(schema_editor, table):
            continue
        schema_editor.execute(f"GRANT SELECT ON {table} TO {_ROLE};")  # nosec B608


class Migration(migrations.Migration):
    """Revoke the provisioner's outbox write path and other non-allowlisted engine grants."""

    dependencies = [
        ("engine", "0046_subnet_reservation_coordination"),
    ]

    operations = [
        migrations.RunPython(_revoke_outbox, _grant_outbox),
        migrations.RunPython(_revoke_engine_table_reads, _grant_engine_table_reads),
    ]
