"""Remove Range and UserNGFW from mission_control state.

This migration removes Range and UserNGFW models from mission_control's
Django state. The models have been moved to engine app.
The database tables remain unchanged (handled by engine.0001_initial).

See Issue #437.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("mission_control", "0034_cleanup_moved_models"),
        # Ensure engine migration runs first to create the models in engine's state
        ("engine", "0001_initial"),
    ]

    operations = [
        # Use SeparateDatabaseAndState: state_operations update Django's model registry
        # but don't touch the database (tables are now managed by engine app)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="Range"),
                migrations.DeleteModel(name="UserNGFW"),
            ],
            database_operations=[],
        ),
    ]
