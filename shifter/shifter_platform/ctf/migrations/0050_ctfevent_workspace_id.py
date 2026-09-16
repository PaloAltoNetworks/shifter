"""Schema migration: add the CTF event workspace scope, nullable (ADR-051, #2048).

ADR-046 kept CTF events unbound; cross-event workspace confinement cannot be
proved under that posture, so events gain an immutable scalar ``workspace_id``
tenancy boundary. The column is added nullable here so existing rows can be
backfilled by 0051 from their creator's personal workspace without a model
default silently assigning one tenant to everyone; 0052 then makes it required.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add ``CTFEvent.workspace_id`` as a nullable soft reference."""

    dependencies = [
        ("ctf", "0049_ctf_co_organizer_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="ctfevent",
            name="workspace_id",
            field=models.IntegerField(
                blank=True,
                db_index=True,
                null=True,
                help_text=(
                    "Workspace this event is scoped to (immutable soft reference; "
                    "ADR-046/ADR-051, #2048). Resolved at creation from an authorized workspace "
                    "or the creator's personal workspace (existing events are backfilled). Never "
                    "a cross-layer foreign key and, once set, never changed. Cross-event campaign "
                    "confinement is enforced against this scalar at the campaign boundary; an "
                    "event without a scope simply cannot be targeted by a campaign."
                ),
            ),
        ),
    ]
