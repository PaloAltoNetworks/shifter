"""Migrate credentials from mission_control to cms.

Copies data from:
- mission_control.SCMCredential -> cms.Credential (type=scm)
- mission_control.NGFWDeploymentProfile -> cms.Credential (type=deployment_profile)
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def migrate_credentials_forward(apps, schema_editor):
    """Copy credentials from old tables to unified Credential table."""
    # Get models via apps registry (historical versions)
    SCMCredential = apps.get_model("mission_control", "SCMCredential")
    NGFWDeploymentProfile = apps.get_model("mission_control", "NGFWDeploymentProfile")
    Credential = apps.get_model("cms", "Credential")

    scm_count = 0
    dp_count = 0

    # Migrate SCM credentials
    for scm in SCMCredential.objects.all():
        Credential.objects.create(
            user_id=scm.user_id,
            name=scm.name,
            credential_type="scm",
            scm_folder_name=scm.scm_folder_name,
            scm_pin_id=scm.scm_pin_id,
            scm_pin_value=scm.scm_pin_value,
            sls_region=scm.sls_region,
            authcode="",
            created_at=scm.created_at,
            deleted_at=scm.deleted_at,
            expires_at=scm.expires_at,
            last_verified_at=scm.last_verified_at,
            last_used_at=scm.last_used_at,
        )
        scm_count += 1

    # Migrate deployment profiles
    for dp in NGFWDeploymentProfile.objects.all():
        Credential.objects.create(
            user_id=dp.user_id,
            name=dp.name,
            credential_type="deployment_profile",
            scm_folder_name="",
            scm_pin_id="",
            scm_pin_value="",
            sls_region="",
            authcode=dp.authcode,
            created_at=dp.created_at,
            deleted_at=dp.deleted_at,
            expires_at=dp.expires_at,
            last_verified_at=dp.last_verified_at,
            last_used_at=dp.last_used_at,
        )
        dp_count += 1

    logger.info(
        "Migrated credentials: %d SCM credentials, %d deployment profiles",
        scm_count,
        dp_count,
    )


def migrate_credentials_reverse(apps, schema_editor):
    """Remove migrated credentials (reverse migration)."""
    Credential = apps.get_model("cms", "Credential")

    # Only delete credentials that were migrated (have matching old records)
    # For safety, we delete all cms.Credential records
    count = Credential.objects.count()
    Credential.objects.all().delete()

    logger.info("Reversed credential migration: deleted %d records", count)


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0001_initial"),
        ("mission_control", "0030_ngfw_models"),  # Contains SCMCredential, NGFWDeploymentProfile
    ]

    operations = [
        migrations.RunPython(
            migrate_credentials_forward,
            migrate_credentials_reverse,
        ),
    ]
