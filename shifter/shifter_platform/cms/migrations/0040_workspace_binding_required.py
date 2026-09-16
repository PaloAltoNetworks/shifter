"""Schema migration: make the CMS workspace scope bindings mandatory (#1325).

ADR-046-R3/R4. The columns were added nullable in 0038 so historical rows could
be validated and backfilled by 0039 without a model default silently assigning
one tenant to everyone. That work is complete by the time this runs, so the
columns become non-null and "every range ownership projection carries a tenancy
scope" is enforced by the database rather than by convention.

There is deliberately no default. A default would let a new creation path
persist a row with a placeholder tenant -- the failure this migration exists to
prevent. The trusted CMS launch facade supplies the real scope and the Engine
boundary refuses a missing one.

If any row is still NULL here the upgrade fails loudly, which is correct: 0039
either bound it or stopped on divergent ownership evidence, so a NULL at this
point means the database was modified outside the migration path and needs an
operator decision rather than a guessed tenant.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Require a workspace binding on CMS request intent and the range projection."""

    dependencies = [
        ("cms", "0039_backfill_workspace_bindings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="request",
            name="workspace_id",
            field=models.IntegerField(
                db_index=True,
                help_text="Workspace this request was launched in (soft reference; see ADR-046).",
            ),
        ),
        migrations.AlterField(
            model_name="rangeinstance",
            name="workspace_id",
            field=models.IntegerField(
                db_index=True,
                help_text="Workspace this range is scoped to (soft reference; see ADR-046).",
            ),
        ),
    ]
