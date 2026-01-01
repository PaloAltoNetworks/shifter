"""Seed operating system reference data.

This migration creates initial OperatingSystem records for supported platforms.
"""

from django.db import migrations


def seed_operating_systems(apps, schema_editor):
    """Create initial operating system records."""
    OperatingSystem = apps.get_model("cms", "OperatingSystem")

    operating_systems = [
        {"slug": "windows", "name": "Windows", "extensions": [".msi"]},
        {
            "slug": "linux-debian",
            "name": "Linux (Debian/Ubuntu)",
            "extensions": [".deb"],
        },
        {"slug": "linux-rhel", "name": "Linux (RHEL/CentOS)", "extensions": [".rpm"]},
        {"slug": "linux-generic", "name": "Linux (Generic)", "extensions": [".sh"]},
    ]

    for os_data in operating_systems:
        OperatingSystem.objects.update_or_create(
            slug=os_data["slug"],
            defaults={"name": os_data["name"], "extensions": os_data["extensions"]},
        )


def remove_operating_systems(apps, schema_editor):
    """Remove seeded operating systems (for migration rollback)."""
    OperatingSystem = apps.get_model("cms", "OperatingSystem")
    OperatingSystem.objects.filter(
        slug__in=["windows", "linux-debian", "linux-rhel", "linux-generic"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0004_add_operatingsystem"),
    ]

    operations = [
        migrations.RunPython(seed_operating_systems, remove_operating_systems),
    ]
