# Generated for issue #693

from __future__ import annotations

from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import migrations

SENSITIVE_INSTANCE_DATA_KEYS = frozenset({"authcode", "scm_pin_value", "otp_value"})
ENCRYPTED_VALUE_PREFIX = "enc:v1:"


def encrypt_existing_instance_data(apps, schema_editor):
    transform_existing_instance_data(apps, encrypt=True)


def decrypt_existing_instance_data(apps, schema_editor):
    transform_existing_instance_data(apps, encrypt=False)


def transform_existing_instance_data(apps, *, encrypt: bool):
    Instance = apps.get_model("cms", "Instance")
    instances_to_update = []

    for instance in Instance.objects.all().iterator(chunk_size=1000):
        data = instance.data
        if not isinstance(data, dict):
            continue

        transformed = transform_sensitive_instance_data(data, encrypt=encrypt)
        if transformed != data:
            instance.data = transformed
            instances_to_update.append(instance)

    if instances_to_update:
        Instance.objects.bulk_update(instances_to_update, ["data"])


def transform_sensitive_instance_data(data: dict[str, Any], *, encrypt: bool) -> dict[str, Any]:
    transformed = data.copy()
    for key in SENSITIVE_INSTANCE_DATA_KEYS:
        value = transformed.get(key)
        if not isinstance(value, str) or value == "":
            continue
        transformed[key] = encrypt_value(value) if encrypt else decrypt_value(value)
    return transformed


def encrypt_value(value: str) -> str:
    if value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value
    encrypted = fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTED_VALUE_PREFIX}{encrypted}"


def decrypt_value(value: str) -> str:
    if not value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value
    token = value.removeprefix(ENCRYPTED_VALUE_PREFIX)
    try:
        return fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Instance data contains an invalid encrypted value") from exc


def fernet() -> Fernet:
    return Fernet(settings.FIELD_ENCRYPTION_KEY.encode("utf-8"))


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0028_encrypt_sensitive_credential_data"),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_instance_data, decrypt_existing_instance_data),
    ]
