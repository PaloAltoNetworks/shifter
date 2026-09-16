"""Data migration: bind existing engine ranges to their owner's workspace (#1325).

ADR-046-R3/R4. A range's owner is ``Range.user``; the workspace it belongs to
after the upgrade is that owner's personal workspace, so no existing range
changes hands and no lifecycle, admission, or remote-access behavior changes.

Only unbound rows are filled. A range that already carries a scope is left
alone: this migration closes a gap, it never rewrites tenancy.
"""

from django.db import migrations


def _personal_workspace_ids(workspace_model) -> dict[int, int]:
    """Map user id -> personal workspace id for every user that has one."""
    return dict(
        workspace_model.objects.filter(personal_for_user__isnull=False).values_list("personal_for_user_id", "id")
    )


def backfill_workspace_bindings(apps, schema_editor):  # noqa: ARG001 - migration signature
    """Set ``Range.workspace_id`` from each range owner's personal workspace."""
    range_model = apps.get_model("engine", "Range")
    workspace_model = apps.get_model("workspaces", "Workspace")

    personal = _personal_workspace_ids(workspace_model)
    if not personal:
        return

    for range_id, user_id in range_model.objects.filter(workspace_id__isnull=True).values_list("id", "user_id"):
        workspace_id = personal.get(user_id)
        if workspace_id is None:
            # The personal-workspace backfill runs first and covers every user,
            # so a miss means the range references a user that no longer exists.
            # Report the row, never the account identity.
            msg = (
                f"engine range {range_id} references user {user_id}, which has no personal workspace. "
                "Resolve the range's ownership before migrating (#1325)."
            )
            raise RuntimeError(msg)
        range_model.objects.filter(id=range_id).update(workspace_id=workspace_id)


class Migration(migrations.Migration):
    """Bind pre-#1325 engine ranges to their owner's personal workspace."""

    dependencies = [
        ("engine", "0040_range_workspace_id"),
        ("workspaces", "0002_backfill_personal_workspaces"),
    ]

    operations = [
        migrations.RunPython(backfill_workspace_bindings, migrations.RunPython.noop),
    ]
