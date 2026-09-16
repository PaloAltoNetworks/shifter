"""Schema migration: make the Engine workspace scope binding mandatory (#1325).

ADR-046-R3/R4. Counterpart to ``cms.0040_workspace_binding_required``: the
column was added nullable in 0040 so 0041 could bind historical ranges from
their existing owner, and it becomes non-null once that is done. A range with no
tenancy scope is not a state the platform should be able to reach.

No default, for the same reason as the CMS migration: the trusted CMS launch
facade supplies the real scope and ``engine.services`` refuses a create without
one, so a placeholder tenant must never be substitutable for it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Require a workspace binding on the Engine range."""

    dependencies = [
        ("engine", "0041_backfill_workspace_bindings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="range",
            name="workspace_id",
            field=models.IntegerField(
                db_index=True,
                help_text="Workspace scope (soft reference; ADR-046).",
            ),
        ),
    ]
