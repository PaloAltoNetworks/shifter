"""Seed operating system reference data."""

from django.db import migrations


def seed_operating_systems(apps, schema_editor):
    """Create initial operating system records."""
    OperatingSystem = apps.get_model("mission_control", "OperatingSystem")

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
    OperatingSystem = apps.get_model("mission_control", "OperatingSystem")
    OperatingSystem.objects.filter(
        slug__in=["windows", "linux-debian", "linux-rhel", "linux-generic"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("mission_control", "0001_initial_models"),
    ]

    operations = [
        migrations.RunPython(seed_operating_systems, remove_operating_systems),
    ]
