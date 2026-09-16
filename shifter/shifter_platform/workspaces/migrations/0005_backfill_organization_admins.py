"""Data migration: seed each personal organization's bootstrap admin (#1939).

ADR-048. Organization authority is a persisted ``admin``
``OrganizationMembership`` rather than an inference from a workspace role. The
bootstrap for every existing personal organization (ADR-046-R4) is its personal
workspace owner: this migration seeds one ``admin`` membership per personal
organization so authority is read from the row afterwards.

Idempotent: ``get_or_create`` keyed on ``(organization, user)`` means a re-run
or a partially applied deployment changes nothing. Historical models are
resolved through ``apps.get_model`` and no application startup signal is
involved. The reverse is a no-op -- removing the seeded admins would strand the
organizations with no authority source.
"""

from django.db import migrations

ADMIN_ROLE = "admin"


def backfill_organization_admins(apps, schema_editor):  # noqa: ARG001 - migration signature
    """Seed the bootstrap ``admin`` membership for every personal organization."""
    workspace_model = apps.get_model("workspaces", "Workspace")
    membership_model = apps.get_model("workspaces", "OrganizationMembership")

    personal = workspace_model.objects.filter(personal_for_user__isnull=False).values_list(
        "organization_id", "personal_for_user_id"
    )
    for organization_id, user_id in personal.iterator():
        membership_model.objects.get_or_create(
            organization_id=organization_id,
            user_id=user_id,
            defaults={"role": ADMIN_ROLE},
        )


class Migration(migrations.Migration):
    """Backfill the #1939 per-personal-organization bootstrap admins."""

    dependencies = [
        ("workspaces", "0004_organization_profile_and_membership"),
    ]

    operations = [
        migrations.RunPython(backfill_organization_admins, migrations.RunPython.noop),
    ]
