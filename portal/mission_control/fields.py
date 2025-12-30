"""Custom Django model fields for mission_control app."""

import base64

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models


def get_fernet():
    """Get Fernet cipher using the encryption key from settings.

    The key should be a URL-safe base64-encoded 32-byte key.
    Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    Returns:
        Fernet cipher instance
    """
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        raise ValueError(
            "FIELD_ENCRYPTION_KEY not set in settings. "
            "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


class EncryptedCharField(models.CharField):
    """CharField that encrypts data at rest using Fernet symmetric encryption.

    Values are encrypted before saving to database and decrypted when loaded.
    Uses Django settings.FIELD_ENCRYPTION_KEY for the encryption key.

    Example usage:
        class MyModel(models.Model):
            secret = EncryptedCharField(max_length=255)
    """

    description = "An encrypted CharField"

    def __init__(self, *args, **kwargs):
        # Encrypted values are longer than plaintext, adjust max_length
        # Fernet encryption adds ~45 bytes overhead + base64 encoding
        # For a 255 char input, output is ~400 chars max
        if "max_length" in kwargs:
            kwargs["max_length"] = max(kwargs["max_length"], 512)
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        """Encrypt value before saving to database."""
        if value is None:
            return value
        if value == "":
            return value

        fernet = get_fernet()
        encrypted = fernet.encrypt(value.encode("utf-8"))
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    def from_db_value(self, value, expression, connection):
        """Decrypt value when loading from database."""
        if value is None:
            return value
        if value == "":
            return value

        try:
            fernet = get_fernet()
            encrypted = base64.urlsafe_b64decode(value.encode("ascii"))
            return fernet.decrypt(encrypted).decode("utf-8")
        except Exception:
            # If decryption fails, return the raw value
            # This handles migration scenarios where old data isn't encrypted
            return value

    def to_python(self, value):
        """Convert value to Python string (no decryption needed here)."""
        if isinstance(value, str) or value is None:
            return value
        return str(value)
