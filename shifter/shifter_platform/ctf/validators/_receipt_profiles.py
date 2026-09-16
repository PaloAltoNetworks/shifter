"""Deployment-owned registry for authenticated receipt verifier profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import ParseResult, urlparse

from shared.receipt_validation import ReceiptKeyMode

_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_INVALID_KEY_MODES = "allowed_key_modes must be a non-empty tuple of unique key modes"
_PROFILES: dict[str, ReceiptVerifierProfile] = {}


class ReceiptProfileError(ValueError):
    """A verifier profile is malformed, unsafe, or conflicts with the registry."""


@dataclass(frozen=True, slots=True)
class ReceiptVerifierProfile:
    """Closed deployment profile for one authenticated verifier endpoint."""

    profile_id: str
    deployment_id: str
    provider_contract: str
    endpoint_url: str
    audience: str
    service_auth_secret_ref: str
    issuer_id: str
    allowed_key_modes: tuple[ReceiptKeyMode, ...]
    allowed_algorithms: tuple[str, ...]
    permitted_objectives: tuple[str, ...]
    total_timeout_seconds: int = 10
    max_addresses: int = 2
    max_request_bytes: int = 8192
    max_response_bytes: int = 4096
    max_receipt_ttl_seconds: int = 900

    def __post_init__(self) -> None:
        """Validate the closed profile before it enters the registry."""
        for name in ("profile_id", "deployment_id", "provider_contract", "issuer_id"):
            _require_identifier(name, getattr(self, name))
        _require_endpoint(self.endpoint_url)
        _require_audience(self.audience)
        _require_secret_ref(self.service_auth_secret_ref)
        _require_key_modes(self.allowed_key_modes)
        _require_identifier_tuple("allowed_algorithms", self.allowed_algorithms, item_name="algorithm", maximum=16)
        _require_identifier_tuple("permitted_objectives", self.permitted_objectives, item_name="objective", maximum=64)
        _require_bound("total_timeout_seconds", self.total_timeout_seconds, 1, 30)
        _require_bound("max_addresses", self.max_addresses, 1, 8)
        _require_bound("max_request_bytes", self.max_request_bytes, 1024, 16384)
        _require_bound("max_response_bytes", self.max_response_bytes, 256, 16384)
        _require_bound("max_receipt_ttl_seconds", self.max_receipt_ttl_seconds, 1, 3600)


def register_receipt_profile(profile: ReceiptVerifierProfile) -> None:
    """Register a trusted deployment profile, allowing only exact idempotent replay."""
    if not isinstance(profile, ReceiptVerifierProfile):
        raise ReceiptProfileError("profile must be a ReceiptVerifierProfile")
    existing = _PROFILES.get(profile.profile_id)
    if existing is not None and existing != profile:
        raise ReceiptProfileError(f"receipt profile {profile.profile_id!r} is already registered differently")
    _PROFILES[profile.profile_id] = profile


def get_receipt_profile(profile_id: str) -> ReceiptVerifierProfile | None:
    """Return an exact registered profile without fallback or inference."""
    return _PROFILES.get(profile_id)


def _require_identifier(name: str, value: object) -> None:
    """Require one canonical deployment identifier."""
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ReceiptProfileError(f"{name} is not a canonical identifier")


def _require_endpoint(value: object) -> None:
    """Require an HTTPS endpoint without ambient request components."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ReceiptProfileError("endpoint_url is invalid")
    try:
        parsed = urlparse(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ReceiptProfileError("endpoint_url is invalid") from exc
    if _unsafe_url_components(parsed) or port not in (None, 443):
        raise ReceiptProfileError("endpoint_url must be an HTTPS endpoint without credentials, query, or fragment")


def _require_audience(value: object) -> None:
    """Require a bounded HTTPS service identity."""
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ReceiptProfileError("audience is invalid")
    parsed = urlparse(value)
    if _unsafe_url_components(parsed):
        raise ReceiptProfileError("audience must be an HTTPS service identity")


def _require_secret_ref(value: object) -> None:
    """Require a bounded provider-owned secret reference."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 500
        or value != value.strip()
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ReceiptProfileError("service_auth_secret_ref must be a bounded provider reference")


def _unsafe_url_components(parsed: ParseResult) -> bool:
    """Return whether a parsed URL violates the closed HTTPS identity shape."""
    return bool(
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    )


def _require_bound(name: str, value: object, minimum: int, maximum: int) -> None:
    """Require an integer profile bound inside an inclusive range."""
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ReceiptProfileError(f"{name} must be between {minimum} and {maximum}")


def _require_key_modes(value: object) -> None:
    """Require a non-empty tuple of unique closed key modes."""
    if not isinstance(value, tuple):
        raise ReceiptProfileError(_INVALID_KEY_MODES)
    key_modes: tuple[object, ...] = value
    if not key_modes or len(set(key_modes)) != len(key_modes):
        raise ReceiptProfileError(_INVALID_KEY_MODES)
    if not all(isinstance(mode, ReceiptKeyMode) for mode in key_modes):
        raise ReceiptProfileError(_INVALID_KEY_MODES)


def _require_identifier_tuple(
    field_name: str,
    value: object,
    *,
    item_name: str,
    maximum: int,
) -> None:
    """Require a bounded tuple of unique canonical identifiers."""
    if not isinstance(value, tuple):
        raise ReceiptProfileError(f"{field_name} must contain 1-{maximum} unique identifiers")
    if not value or len(value) > maximum or len(set(value)) != len(value):
        raise ReceiptProfileError(f"{field_name} must contain 1-{maximum} unique identifiers")
    for item in value:
        _require_identifier(item_name, item)
