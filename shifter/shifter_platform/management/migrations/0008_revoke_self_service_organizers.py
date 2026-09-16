"""Data migration: revoke self-service-derived CTF Organizer memberships.

Issue #1516. Before this change the ``CTF Organizer`` group could be granted from
a self-mutable ``user_type`` claim, so existing memberships cannot be assumed to
be administrator-authorized. This migration removes ``CTF Organizer`` from every
current member and records a strict ROLE_SYNC audit row per removal (fail-closed,
per maintainer decision 2026-07-11). Organizer authority is re-granted only from
administrator-controlled provider group claims or explicit local assignment (see
``config.organizer_authority``): re-run the affected provider login, or a
superuser re-adds the group in the Django admin.

The reverse is intentionally a no-op — re-adding revoked memberships would
reintroduce the unverified authority this migration exists to remove.
"""

import json

from django.db import connection, migrations
from django.utils import timezone

ORGANIZER_GROUP = "CTF Organizer"
AUDIT_TABLES = ("shared_auditlog", "risk" "_register_auditlog")


def _audit_table_name(db_connection) -> str:
    with db_connection.cursor() as cursor:
        tables = set(db_connection.introspection.table_names(cursor))
    for table_name in AUDIT_TABLES:
        if table_name in tables:
            return table_name
    raise RuntimeError("durable audit table is unavailable")


def _insert_audit_row(db_connection, table_name: str, *, user_id: int, previous: list[str], new: list[str]) -> None:
    quoted_table = db_connection.ops.quote_name(table_name)
    query = (
        f"INSERT INTO {quoted_table} "  # nosec B608 -- allowlisted introspected name, quoted by Django
        "(entity_type, entity_id, action, actor_type, actor_id, timestamp, "
        "previous_state, new_state, context, source_ip, user_agent, request_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    with db_connection.cursor() as cursor:
        cursor.execute(
            query,
            [
                "user",
                user_id,
                "role_sync",
                "system",
                None,
                timezone.now(),
                json.dumps({"groups": previous}),
                json.dumps({"groups": new}),
                "CTF Organizer revoked: authority separated from self-service identity (issue #1516)",
                None,
                "",
                "",
            ],
        )


def revoke_self_service_organizers(apps, schema_editor):
    """Remove CTF Organizer from all current members, auditing each removal."""
    Group = apps.get_model("auth", "Group")

    try:
        organizer_group = Group.objects.get(name=ORGANIZER_GROUP)
    except Group.DoesNotExist:
        return

    users = list(organizer_group.user_set.all())
    if not users:
        return

    db_connection = schema_editor.connection if schema_editor is not None else connection
    audit_table = _audit_table_name(db_connection)
    for user in users:
        previous = sorted(user.groups.values_list("name", flat=True))
        user.groups.remove(organizer_group)
        new = sorted(user.groups.values_list("name", flat=True))
        _insert_audit_row(db_connection, audit_table, user_id=user.id, previous=previous, new=new)


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0007_userprofile_organizer_grant_source"),
    ]

    operations = [
        migrations.RunPython(revoke_self_service_organizers, migrations.RunPython.noop),
    ]
