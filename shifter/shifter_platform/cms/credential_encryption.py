"""Field-level encryption for sensitive values inside JSON model fields.

Defense in depth (#693): selectively encrypts known sensitive keys within
JSONField blobs at write time, transparently decrypts on read. Non-sensitive
operational keys (names, IDs, roles, regions) remain queryable and visible.

The base ``EncryptedJSONField`` is generic over a frozenset of sensitive keys.
Concrete subclasses bind a key set appropriate to the model they decorate.
``deconstruct()`` masquerades as plain ``JSONField`` so swapping in needs no
schema migration; existing rows are re-encrypted by a data migration that
re-saves each row.
"""

from __future__ import annotations

from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

ENCRYPTED_VALUE_PREFIX = "enc:v1:"


def _transform_sensitive(
    data: dict[str, Any],
    keys: frozenset[str],
    *,
    encrypt: bool,
) -> dict[str, Any]:
    """Return a copy of ``data`` with ``keys`` values en/decrypted.

    Non-string or empty-string values are left alone so partial dicts survive
    intact. The encrypt path is idempotent (already-prefixed values are
    returned unchanged), and so is the decrypt path, which makes the data
    migration safe to re-run.
    """
    transformed = data.copy()
    for key in keys:
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
        raise ValueError("Encrypted JSON field contains an invalid encrypted value") from exc


def _fernet() -> Fernet:
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is not set")
    return Fernet(key.encode("utf-8"))


class EncryptedJSONField(models.JSONField):
    """JSONField that selectively encrypts a configured set of keys.

    Subclasses declare ``sensitive_keys`` (frozenset[str]); any string value
    stored under those keys is encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
    before hitting the database and decrypted on read. Other keys pass through
    so admin views, log diagnostics, and SQL JSON queries on operational
    metadata keep working.

    ``deconstruct()`` returns plain ``JSONField`` so this can be swapped in
    without producing a schema migration; the makemigrations diff is empty.
    """

    sensitive_keys: frozenset[str] = frozenset()

    def get_prep_value(self, value):
        if isinstance(value, dict):
            value = _transform_sensitive(value, self.sensitive_keys, encrypt=True)
        return super().get_prep_value(value)

    def from_db_value(self, value, expression, connection):
        value = super().from_db_value(value, expression, connection)
        if isinstance(value, dict):
            return _transform_sensitive(value, self.sensitive_keys, encrypt=False)
        return value

    def to_python(self, value):
        value = super().to_python(value)
        if isinstance(value, dict):
            return _transform_sensitive(value, self.sensitive_keys, encrypt=False)
        return value

    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        return name, "django.db.models.JSONField", args, kwargs


class EncryptedCredentialDataField(EncryptedJSONField):
    """Credential.data: encrypts secret values in credential payloads.

    Keys mirror the fields flagged secret on the Credential Pydantic specs
    (``cyberscript.schemas.credentials.SCMCredentialSpec.scm_pin_value``,
    ``DeploymentProfileSpec.authcode``). Operational fields (folder name,
    PIN ID, region, profile name) stay plaintext.
    """

    sensitive_keys = frozenset({"authcode", "scm_pin_value"})


class EncryptedInstanceDataField(EncryptedJSONField):
    """Instance.data: encrypts secret values bled into the JSON blob.

    For non-NGFW instances this is effectively a no-op because the spec
    contains no secret-shaped keys. For NGFW instances,
    ``cms.services.create_ngfw`` persists the hydrated
    ``cyberscript.schemas.app.NGFWAppSpec`` directly into ``instance.data``,
    which can include ``authcode``, ``scm_pin_value``, and ``otp_value``.
    Those three keys are encrypted at rest here.
    """

    sensitive_keys = frozenset({"authcode", "scm_pin_value", "otp_value"})
