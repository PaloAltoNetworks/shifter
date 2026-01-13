# Generated manually for seeding CredentialType entries

from django.db import migrations


def seed_credential_types(apps, schema_editor):
    """Seed default credential types."""
    CredentialType = apps.get_model("cms", "CredentialType")

    CredentialType.objects.get_or_create(
        slug="scm",
        defaults={
            "name": "SCM",
            "spec_class": "shared.schemas.SCMCredentialSpec",
        },
    )

    CredentialType.objects.get_or_create(
        slug="deployment_profile",
        defaults={
            "name": "Deployment Profile",
            "spec_class": "shared.schemas.DeploymentProfileSpec",
        },
    )


def remove_credential_types(apps, schema_editor):
    """Remove seeded credential types (for migration rollback)."""
    CredentialType = apps.get_model("cms", "CredentialType")
    CredentialType.objects.filter(slug__in=["scm", "deployment_profile"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0017_remove_ngfw_model"),
    ]

    operations = [
        migrations.RunPython(seed_credential_types, remove_credential_types),
    ]
