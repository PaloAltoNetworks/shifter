# Wrap persisted engine JSON blobs with spec_schema/spec_version discriminators.

from django.db import migrations

SPEC_SCHEMA_KEY = "spec_schema"
SPEC_VERSION_KEY = "spec_version"
PAYLOAD_KEY = "payload"
SPEC_VERSION = "1"

INSTANCE_SPEC_SLUG = "instance_spec"
SUBNET_SPEC_SLUG = "subnet_spec"
NGFW_APP_SPEC_SLUG = "ngfw_app_spec"
RANGE_SPEC_SLUG = "range_spec"


def _is_wrapped(blob):
    return isinstance(blob, dict) and SPEC_SCHEMA_KEY in blob and PAYLOAD_KEY in blob


def _wrap_blob(slug, blob):
    if not blob or _is_wrapped(blob):
        return blob
    return {
        SPEC_SCHEMA_KEY: slug,
        SPEC_VERSION_KEY: SPEC_VERSION,
        PAYLOAD_KEY: blob,
    }


def _unwrap_blob(blob):
    if not blob or not _is_wrapped(blob):
        return blob
    return blob[PAYLOAD_KEY]


def _wrap_persisted_specs(apps, schema_editor):
    range_model = apps.get_model("engine", "Range")
    for row in range_model.objects.exclude(range_config__isnull=True).iterator():
        wrapped = _wrap_blob(RANGE_SPEC_SLUG, row.range_config)
        if wrapped != row.range_config:
            row.range_config = wrapped
            row.save(update_fields=["range_config"])

    for model_name, slug in (
        ("Instance", INSTANCE_SPEC_SLUG),
        ("App", NGFW_APP_SPEC_SLUG),
        ("Subnet", SUBNET_SPEC_SLUG),
    ):
        model = apps.get_model("engine", model_name)
        for row in model.objects.exclude(spec__isnull=True).iterator():
            wrapped = _wrap_blob(slug, row.spec)
            if wrapped != row.spec:
                row.spec = wrapped
                row.save(update_fields=["spec"])


def _unwrap_persisted_specs(apps, schema_editor):
    range_model = apps.get_model("engine", "Range")
    for row in range_model.objects.exclude(range_config__isnull=True).iterator():
        unwrapped = _unwrap_blob(row.range_config)
        if unwrapped != row.range_config:
            row.range_config = unwrapped
            row.save(update_fields=["range_config"])

    for model_name in ("Instance", "App", "Subnet"):
        model = apps.get_model("engine", model_name)
        for row in model.objects.exclude(spec__isnull=True).iterator():
            unwrapped = _unwrap_blob(row.spec)
            if unwrapped != row.spec:
                row.spec = unwrapped
                row.save(update_fields=["spec"])


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0020_remove_subnetallocation_unique_active_cidr_per_vpc_and_more"),
    ]

    operations = [
        migrations.RunPython(_wrap_persisted_specs, _unwrap_persisted_specs),
    ]
