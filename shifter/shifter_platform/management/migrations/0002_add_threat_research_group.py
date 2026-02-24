"""Data migration: create the Threat Research user group."""

from django.db import migrations


def create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="Threat Research")


def delete_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="Threat Research").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_group, delete_group),
    ]
