"""Remove UserProfile and ActivityLog from mission_control state.

These models have been moved to the management app. This migration
removes them from mission_control's state without dropping the tables
(they're now managed by management app).
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("mission_control", "0031_grant_ngfw_columns_to_provisioner"),
        ("management", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="UserProfile"),
                migrations.DeleteModel(name="ActivityLog"),
            ],
            database_operations=[],
        ),
    ]
