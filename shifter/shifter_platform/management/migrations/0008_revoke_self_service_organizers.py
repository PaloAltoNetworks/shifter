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

from django.db import migrations

ORGANIZER_GROUP = "CTF Organizer"


def revoke_self_service_organizers(apps, schema_editor):
    """Remove CTF Organizer from all current members, auditing each removal."""
    Group = apps.get_model("auth", "Group")
    AuditLog = apps.get_model("risk_register", "AuditLog")

    try:
        organizer_group = Group.objects.get(name=ORGANIZER_GROUP)
    except Group.DoesNotExist:
        return

    for user in list(organizer_group.user_set.all()):
        previous = sorted(user.groups.values_list("name", flat=True))
        user.groups.remove(organizer_group)
        new = sorted(user.groups.values_list("name", flat=True))
        AuditLog.objects.create(
            entity_type="user",
            entity_id=user.id,
            action="role_sync",
            actor_type="system",
            actor_id=None,
            previous_state={"groups": previous},
            new_state={"groups": new},
            context="CTF Organizer revoked: authority separated from self-service identity (issue #1516)",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0007_userprofile_organizer_grant_source"),
        ("risk_register", "0005_alter_auditlog_action"),
    ]

    operations = [
        migrations.RunPython(revoke_self_service_organizers, migrations.RunPython.noop),
    ]
