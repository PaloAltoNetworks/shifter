"""Data migration: give every existing user a personal workspace (#1325).

ADR-046-R4. The compatibility default is per user: each account gets its own
personal organization, one personal workspace inside it, and an owner
membership. There is deliberately no shared deployment-wide "Default"
organization -- that would make every install single-tenant by construction and
would have to be unpicked before a university or hosting operator could run more
than one tenant.

Idempotent: a user who already owns a personal workspace keeps it, so a re-run
(or a deployment that partially applied) changes nothing. Historical models are
resolved through ``apps.get_model`` and no application startup signal is
involved, so the result does not depend on runtime wiring.

The reverse is a no-op. Deleting personal workspaces would orphan the range
bindings written by the cms/engine backfills that depend on this one.
"""

from django.db import migrations

PERSONAL_NAME = "Personal"
OWNER_ROLE = "owner"


def backfill_personal_workspaces(apps, schema_editor):  # noqa: ARG001 - migration signature
    """Create the per-user personal organization, workspace, and owner membership."""
    user_model = apps.get_model("auth", "User")
    organization_model = apps.get_model("workspaces", "Organization")
    workspace_model = apps.get_model("workspaces", "Workspace")
    membership_model = apps.get_model("workspaces", "WorkspaceMembership")

    already_personal = set(
        workspace_model.objects.filter(personal_for_user__isnull=False).values_list("personal_for_user_id", flat=True)
    )

    for user_id in user_model.objects.values_list("id", flat=True).iterator():
        if user_id in already_personal:
            continue
        organization = organization_model.objects.create(name=PERSONAL_NAME)
        workspace = workspace_model.objects.create(
            organization=organization,
            name=PERSONAL_NAME,
            personal_for_user_id=user_id,
        )
        membership_model.objects.get_or_create(
            workspace=workspace,
            user_id=user_id,
            defaults={"role": OWNER_ROLE},
        )


class Migration(migrations.Migration):
    """Backfill the #1325 per-user compatibility workspaces."""

    dependencies = [
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_personal_workspaces, migrations.RunPython.noop),
    ]
