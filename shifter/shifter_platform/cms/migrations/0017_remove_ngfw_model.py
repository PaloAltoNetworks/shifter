"""Remove NGFW model from CMS.

The NGFW model is no longer used - NGFWs are now tracked via
Request → Instance → App hierarchy.

The actual table is mission_control_userngfw (set via explicit db_table
in migration 0008). We use SeparateDatabaseAndState to cleanly remove
from Django state, then drop the table.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0016_entitybase_and_ngfw_types"),
    ]

    operations = [
        # Remove NGFW model - table is mission_control_userngfw (explicit db_table)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="NGFW"),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP TABLE IF EXISTS mission_control_userngfw;",
                    reverse_sql="",  # Cannot reverse - model definition gone
                ),
            ],
        ),
    ]
