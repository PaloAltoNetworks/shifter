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

from shared import field_encryption as _shared_encryption

ENCRYPTED_VALUE_PREFIX = _shared_encryption.ENCRYPTED_VALUE_PREFIX
EncryptedJSONField = _shared_encryption.EncryptedJSONField


def _encrypt_value(value: str) -> str:
    """Compatibility wrapper for legacy callers and migrations."""
    return _shared_encryption.encrypt_value(value)


def _decrypt_value(value: str) -> str:
    """Compatibility wrapper for legacy callers and migrations."""
    return _shared_encryption.decrypt_value(value)


def _transform_sensitive(data: dict[str, Any], keys: frozenset[str], *, encrypt: bool) -> dict[str, Any]:
    """Compatibility wrapper for legacy tests and migrations."""
    return _shared_encryption._transform_sensitive(data, keys, encrypt=encrypt)


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
