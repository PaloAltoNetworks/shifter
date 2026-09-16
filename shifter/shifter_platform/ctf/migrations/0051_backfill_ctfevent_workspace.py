"""Data migration: bind existing CTF events to their creator's workspace (#2048).

ADR-051. Every event is owned by ``created_by`` (a PROTECTed, non-null FK), and
issue #1325 gave every user a personal workspace, so an event's compatibility
tenant is unambiguous: its creator's personal workspace. Nothing changes hands.

Only unbound rows are filled; an existing scope is never rewritten. A creator
without a resolvable personal workspace stops the migration loudly rather than
guessing a tenant -- placing someone's event in the wrong scope is not a
decision a migration gets to make. Diagnostics name the row and the user id,
never an email or credential.
"""

from django.db import migrations


def _personal_workspace_ids(workspace_model) -> dict[int, int]:
    """Map user id -> personal workspace id for every user that has one."""
    return dict(
        workspace_model.objects.filter(personal_for_user__isnull=False).values_list("personal_for_user_id", "id")
    )


def backfill_ctfevent_workspace(apps, schema_editor):  # noqa: ARG001 - migration signature
    """Bind unbound CTF events to their creator's personal workspace."""
    event_model = apps.get_model("ctf", "CTFEvent")
    workspace_model = apps.get_model("workspaces", "Workspace")

    unbound = list(event_model.objects.filter(workspace_id__isnull=True).values_list("id", "created_by_id"))
    if not unbound:
        return

    personal = _personal_workspace_ids(workspace_model)
    for event_id, creator_id in unbound:
        workspace_id = personal.get(creator_id)
        if workspace_id is None:
            msg = (
                f"CTF event {event_id} is owned by user {creator_id}, which has no personal workspace. "
                "Resolve the event's ownership before migrating (ADR-051, #2048)."
            )
            raise RuntimeError(msg)
        event_model.objects.filter(id=event_id).update(workspace_id=workspace_id)


class Migration(migrations.Migration):
    """Backfill pre-#2048 CTF events with their creator's personal workspace."""

    dependencies = [
        ("ctf", "0050_ctfevent_workspace_id"),
        ("workspaces", "0002_backfill_personal_workspaces"),
    ]

    operations = [
        migrations.RunPython(backfill_ctfevent_workspace, migrations.RunPython.noop),
    ]
