"""Provider-neutral verified identity contract (issue #1521).

Both production authentication providers (Cognito/OIDC via
``config.oidc.ShifterOIDCBackend`` and GCP Identity Platform via
``config.identity_platform.IdentityPlatformBackend``) must converge on this
one dependency-neutral value before a login may bind or change
bootstrap-admin flags: a non-empty ``issuer``, ``subject``, ``email``, and the
literal ``email_verified is True``. No provider adapter, and no downstream
binding/policy/audit code, may accept a truthy-but-wrong ``email_verified``
value (``"false"``, ``1``, ...) -- only the Python literal ``True`` passes.

Provider-specific claim shapes differ (an OIDC UserInfo response vs. a
decoded Firebase ID token), so this module intentionally does not parse a raw
claims mapping itself: each provider adapter extracts its own
``issuer`` / ``subject`` / ``email`` / ``email_verified`` values from its own
verified evidence and constructs this dataclass directly. Validation is
enforced by the constructor itself (``__post_init__``), so there is exactly
one way to end up with a ``VerifiedIdentity`` instance and it is always
strictly valid.

Kept free of Django and provider imports (stdlib / ``typing`` only) so
``shared`` stays dependency-neutral per ``.importlinter``.
"""

from __future__ import annotations

from dataclasses import dataclass


class VerifiedIdentityError(ValueError):
    """Raised when raw provider evidence fails strict verified-identity checks."""


def _require_nonblank(field_name: str, value: object) -> None:
    """Raise :class:`VerifiedIdentityError` unless ``value`` is a non-blank string."""
    if not isinstance(value, str) or not value.strip():
        raise VerifiedIdentityError(f"VerifiedIdentity requires a non-empty {field_name}")


@dataclass(frozen=True)
class VerifiedIdentity:
    """Strictly verified provider identity evidence.

    ``issuer`` and ``subject`` are opaque, case-sensitive identifiers taken
    from already-protocol-verified evidence (an OIDC ID token's ``iss`` /
    ``sub``, or a Firebase-verified token's ``iss`` / ``sub``) -- never
    lowercased or otherwise normalized. Account identity is keyed on the
    ``(issuer, subject)`` pair, never on ``email``.

    ``email_verified`` must be the Python literal ``True``; any other raw
    value (``"true"``, ``"false"``, ``1``, ``0``, ``None``, missing) is
    rejected by the constructor rather than coerced with ``bool(...)``, which
    would silently accept a truthy string like ``"false"``.

    ``source`` is an optional, bounded provenance label (e.g. ``"oidc"`` /
    ``"identity_platform"``) for audit attribution; it carries no raw claim
    data.
    """

    issuer: str
    subject: str
    email: str
    email_verified: bool
    source: str = ""

    def __post_init__(self) -> None:
        _require_nonblank("issuer", self.issuer)
        _require_nonblank("subject", self.subject)
        _require_nonblank("email", self.email)
        if self.email_verified is not True:
            raise VerifiedIdentityError("VerifiedIdentity requires email_verified is True (literal boolean)")
