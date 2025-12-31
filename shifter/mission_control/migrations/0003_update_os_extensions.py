"""Update operating system extensions to match validation service."""

from django.db import migrations


def update_extensions(apps, schema_editor):
    """Update OS extensions to match supported file formats."""
    OperatingSystem = apps.get_model("mission_control", "OperatingSystem")

    updates = {
        "windows": [".msi", ".zip"],
        "linux-generic": [".tar.gz", ".tgz"],
    }

    for slug, extensions in updates.items():
        OperatingSystem.objects.filter(slug=slug).update(extensions=extensions)


def revert_extensions(apps, schema_editor):
    """Revert to original extensions."""
    OperatingSystem = apps.get_model("mission_control", "OperatingSystem")

    reverts = {
        "windows": [".msi"],
        "linux-generic": [".sh"],
    }

    for slug, extensions in reverts.items():
        OperatingSystem.objects.filter(slug=slug).update(extensions=extensions)


class Migration(migrations.Migration):
    dependencies = [
        ("mission_control", "0002_seed_operating_systems"),
    ]

    operations = [
        migrations.RunPython(update_extensions, revert_extensions),
    ]
