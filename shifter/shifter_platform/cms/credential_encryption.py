"""Helpers for encrypting sensitive values inside credential JSON payloads."""

from __future__ import annotations

from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

SENSITIVE_CREDENTIAL_DATA_KEYS = frozenset({"authcode", "scm_pin_value"})
ENCRYPTED_VALUE_PREFIX = "enc:v1:"


def encrypt_sensitive_credential_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of credential data with sensitive values encrypted."""
    return _transform_sensitive_credential_data(data, encrypt=True)


def decrypt_sensitive_credential_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of credential data with sensitive values decrypted."""
    return _transform_sensitive_credential_data(data, encrypt=False)


class EncryptedCredentialDataField(models.JSONField):
    """JSONField that encrypts credential secret values before database writes."""

    def get_prep_value(self, value):
        if isinstance(value, dict):
            encrypted_value = encrypt_sensitive_credential_data(value)
            return super().get_prep_value(encrypted_value)
        return super().get_prep_value(value)

    def from_db_value(self, value, expression, connection):
        value = super().from_db_value(value, expression, connection)
        if isinstance(value, dict):
            return decrypt_sensitive_credential_data(value)
        return value

    def to_python(self, value):
        value = super().to_python(value)
        if isinstance(value, dict):
            return decrypt_sensitive_credential_data(value)
        return value

    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        return name, "django.db.models.JSONField", args, kwargs


def _transform_sensitive_credential_data(data: dict[str, Any], *, encrypt: bool) -> dict[str, Any]:
    transformed = data.copy()
    for key in SENSITIVE_CREDENTIAL_DATA_KEYS:
        value = transformed.get(key)
        if not isinstance(value, str) or value == "":
            continue
        transformed[key] = _encrypt_value(value) if encrypt else _decrypt_value(value)
    return transformed


def _encrypt_value(value: str) -> str:
    if value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value
    encrypted = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTED_VALUE_PREFIX}{encrypted}"


def _decrypt_value(value: str) -> str:
    if not value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value
    token = value.removeprefix(ENCRYPTED_VALUE_PREFIX)
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Credential data contains an invalid encrypted value") from exc


def _fernet() -> Fernet:
    return Fernet(settings.FIELD_ENCRYPTION_KEY.encode("utf-8"))
