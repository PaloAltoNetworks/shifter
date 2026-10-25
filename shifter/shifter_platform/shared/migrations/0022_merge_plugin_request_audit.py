"""Join adapter and request-accounting audit vocabulary branches."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("shared", "0021_alter_auditlog_entity_type"),
        ("shared", "0021_alter_auditlog_action_alter_auditlog_entity_type"),
    ]

    operations = []
