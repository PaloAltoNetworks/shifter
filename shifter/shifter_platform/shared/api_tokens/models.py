"""Platform API token model (PLAT-102).

``ApiToken`` is the platform-wide programmatic auth principal. It is stored as a
random, high-entropy opaque token: an identifying ``token_id`` (used for lookup)
plus a non-reversible SHA-256 verifier of a separate secret. The raw token is
shown exactly once at creation and never persisted.

The model is intentionally free of app-layer imports so the ``shared`` layer
owns the principal cleanly; audit writes happen at the authentication/admin edge
(see :mod:`shared.api_tokens.audit`), not in the model.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.utils import timezone

from shared.api_tokens.scopes import validate_scopes

if TYPE_CHECKING:
    from datetime import datetime

    from django.contrib.auth.models import AbstractBaseUser

# Opaque token format: ``<TOKEN_PREFIX><token_id><_PART_DELIMITER><secret>``,
# e.g. ``shf_<token_id>.<secret>``. ``_SCHEME`` is composed into the prefix so
# the public scheme name lives in one place; the delimiter is ``.`` because it
# never appears in ``secrets.token_urlsafe`` output (base64url: ``[A-Za-z0-9_-]``).
_SCHEME = "shf"
TOKEN_PREFIX = f"{_SCHEME}_"
_PART_DELIMITER = "."
_TOKEN_ID_BYTES = 8
_SECRET_BYTES = 32
_MAX_TOKEN_ID_ATTEMPTS = 5


def _hash_secret(secret: str) -> str:
    """Return the hex SHA-256 verifier for ``secret``.

    A SHA-256 verifier is sound here because the secret is 32 bytes of CSPRNG
    output — there is no low-entropy brute-force surface that would require a
    password KDF.
    """
    return hashlib.sha256(secret.encode()).hexdigest()


def _split_raw_token(raw_token: str) -> tuple[str, str] | None:
    """Split a raw token into ``(token_id, secret)``, or ``None`` if malformed."""
    if not raw_token or not raw_token.startswith(TOKEN_PREFIX):
        return None
    body = raw_token[len(TOKEN_PREFIX) :]
    token_id, separator, secret = body.partition(_PART_DELIMITER)
    if not separator or not token_id or not secret:
        return None
    return token_id, secret


class ApiToken(models.Model):
    """A scoped, revocable API token for programmatic platform access."""

    name = models.CharField(max_length=100, help_text="Human-friendly name for this token")
    token_id = models.CharField(
        max_length=32,
        unique=True,
        help_text="Public lookup id (the part after the prefix); not a secret",
    )
    verifier_hash = models.CharField(max_length=64, help_text="SHA-256 verifier of the token secret")
    scopes = models.JSONField(default=list, help_text="Granted scopes from the central registry")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_api_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model metadata: table name, ordering, and lookup indexes."""

        db_table = "shared_api_token"
        ordering = ["-created_at"]
        verbose_name = "API Token"
        verbose_name_plural = "API Tokens"
        indexes = [
            models.Index(fields=["token_id"]),
            models.Index(fields=["created_by", "revoked_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"{self.name} ({self.display_id}) - {status}"

    @property
    def is_active(self) -> bool:
        """Return True if the token is neither revoked nor expired."""
        if self.revoked_at is not None:
            return False
        return not (self.expires_at is not None and self.expires_at < timezone.now())

    @property
    def display_id(self) -> str:
        """Return the safe, non-secret display form (``shf_<token_id>``)."""
        return f"{TOKEN_PREFIX}{self.token_id}"

    def revoke(self) -> None:
        """Revoke this token."""
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])

    def touch_last_used(self, *, coalesce_seconds: int) -> bool:
        """Update ``last_used_at`` at most once per ``coalesce_seconds``.

        Returns True when a write happened. Coalescing avoids a database write
        on every authenticated request once tokens drive high-frequency
        automation (preflight guardrail against write amplification).
        """
        now = timezone.now()
        if self.last_used_at is not None and (now - self.last_used_at).total_seconds() < coalesce_seconds:
            return False
        self.last_used_at = now
        self.save(update_fields=["last_used_at"])
        return True

    @classmethod
    def create_token(
        cls,
        *,
        name: str,
        created_by: AbstractBaseUser | None,
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> tuple[ApiToken, str]:
        """Create a token, returning ``(instance, raw_token)``.

        The raw token is only available here, at creation time. ``scopes`` is
        validated against the central registry before any row is written.
        """
        granted = validate_scopes(scopes)

        token_id = cls._generate_unique_token_id()
        secret = secrets.token_urlsafe(_SECRET_BYTES)
        raw_token = f"{TOKEN_PREFIX}{token_id}{_PART_DELIMITER}{secret}"

        token = cls.objects.create(
            name=name,
            token_id=token_id,
            verifier_hash=_hash_secret(secret),
            scopes=granted,
            created_by=created_by,
            expires_at=expires_at,
        )
        return token, raw_token

    @classmethod
    def _generate_unique_token_id(cls) -> str:
        for _ in range(_MAX_TOKEN_ID_ATTEMPTS):
            candidate = secrets.token_urlsafe(_TOKEN_ID_BYTES)
            if not cls.objects.filter(token_id=candidate).exists():
                return candidate
        raise RuntimeError("could not generate a unique token id")

    @classmethod
    def authenticate(cls, raw_token: str) -> ApiToken | None:
        """Resolve a raw token to an active ``ApiToken``, or ``None``.

        Fails closed: malformed input, unknown id, a verifier mismatch, or an
        inactive (revoked/expired) token all return ``None``. The verifier
        comparison is constant-time.
        """
        parsed = _split_raw_token(raw_token)
        if parsed is None:
            return None
        token_id, secret = parsed
        token = cls.objects.filter(token_id=token_id).first()
        if token is None or not hmac.compare_digest(token.verifier_hash, _hash_secret(secret)) or not token.is_active:
            return None
        return token
