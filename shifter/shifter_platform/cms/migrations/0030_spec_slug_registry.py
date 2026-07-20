# Migrate catalog spec_class dotted paths to stable spec_slug values.

from django.db import migrations, models

LEGACY_DOTTED_PATH_TO_SLUG = {
    "shared.schemas.SCMCredentialSpec": "credential.scm",
    "shared.schemas.DeploymentProfileSpec": "credential.deployment_profile",
    "shared.schemas.range.InstanceSpec": "instance.panw-ngfw",
    "shared.schemas.app.NGFWAppSpec": "app.panw-ngfw",
}

CATALOG_MODELS = ("CredentialType", "InstanceType", "AppType")

SPEC_SCHEMA_KEY = "spec_schema"
SPEC_VERSION_KEY = "spec_version"
PAYLOAD_KEY = "payload"
SPEC_VERSION = "1"
RANGE_SPEC_SLUG = "range_spec"


def _is_wrapped(blob):
    return isinstance(blob, dict) and SPEC_SCHEMA_KEY in blob and PAYLOAD_KEY in blob


def _wrap_range_instance_specs(apps, schema_editor):
    range_instance = apps.get_model("cms", "RangeInstance")
    for row in range_instance.objects.exclude(range_spec__isnull=True).iterator():
        if _is_wrapped(row.range_spec):
            continue
        row.range_spec = {
            SPEC_SCHEMA_KEY: RANGE_SPEC_SLUG,
            SPEC_VERSION_KEY: SPEC_VERSION,
            PAYLOAD_KEY: row.range_spec,
        }
        row.save(update_fields=["range_spec"])


def _unwrap_range_instance_specs(apps, schema_editor):
    range_instance = apps.get_model("cms", "RangeInstance")
    for row in range_instance.objects.exclude(range_spec__isnull=True).iterator():
        if not _is_wrapped(row.range_spec):
            continue
        row.range_spec = row.range_spec[PAYLOAD_KEY]
        row.save(update_fields=["range_spec"])


def _migrate_spec_class_to_slug(apps, schema_editor):
    for model_name in CATALOG_MODELS:
        model = apps.get_model("cms", model_name)
        for row in model.objects.all().iterator():
            slug = LEGACY_DOTTED_PATH_TO_SLUG.get(row.spec_class)
            if slug is None:
                msg = f"Unknown spec_class on {model_name} id={row.pk}: {row.spec_class!r}"
                raise ValueError(msg)
            row.spec_class = slug
            row.save(update_fields=["spec_class"])


def _migrate_slug_to_spec_class(apps, schema_editor):
    slug_to_path = {v: k for k, v in LEGACY_DOTTED_PATH_TO_SLUG.items()}
    for model_name in CATALOG_MODELS:
        model = apps.get_model("cms", model_name)
        for row in model.objects.all().iterator():
            path = slug_to_path.get(row.spec_class)
            if path is None:
                msg = f"Unknown spec_slug on {model_name} id={row.pk}: {row.spec_class!r}"
                raise ValueError(msg)
            row.spec_class = path
            row.save(update_fields=["spec_class"])


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0029_encrypt_sensitive_instance_data"),
    ]

    operations = [
        migrations.RunPython(_migrate_spec_class_to_slug, _migrate_slug_to_spec_class),
        migrations.RunPython(_wrap_range_instance_specs, _unwrap_range_instance_specs),
        migrations.RenameField(
            model_name="credentialtype",
            old_name="spec_class",
            new_name="spec_slug",
        ),
        migrations.RenameField(
            model_name="instancetype",
            old_name="spec_class",
            new_name="spec_slug",
        ),
        migrations.RenameField(
            model_name="apptype",
            old_name="spec_class",
            new_name="spec_slug",
        ),
        migrations.AlterField(
            model_name="credentialtype",
            name="spec_slug",
            field=models.CharField(
                help_text="Stable slug for Pydantic spec class (shared.schemas.registry)",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="instancetype",
            name="spec_slug",
            field=models.CharField(
                help_text="Stable slug for Pydantic spec class (shared.schemas.registry)",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="apptype",
            name="spec_slug",
            field=models.CharField(
                help_text="Stable slug for Pydantic spec class (shared.schemas.registry)",
                max_length=255,
            ),
        ),
    ]
