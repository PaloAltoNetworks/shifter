"""Closed configuration contract for HTTP flag validators."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import ParseResult

from ._ssrf import _safe_parse_url, is_blocked_url

DEFAULT_HTTP_TIMEOUT = 10
MAX_HTTP_TIMEOUT = 30
MAX_HTTP_HEADERS = 16
MAX_HTTP_URL_LENGTH = 2048

_ALLOWED_CONFIG_KEYS = frozenset({"url", "method", "timeout", "headers"})
_RECEIPT_CONFIG_KEYS = frozenset({"protocol", "profile_id", "objective_id"})
_ALLOWED_METHODS = frozenset({"GET", "POST"})
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_INVALID_URL_ERROR = "validator_config.url is invalid"
_RESERVED_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
    }
)


class HTTPValidatorConfigError(ValueError):
    """Raised when HTTP validator configuration violates its closed contract."""


def _normalize_url(value: object, *, check_destination: bool) -> str:
    """Validate one HTTPS URL and optionally its current destination."""
    if not isinstance(value, str) or not value:
        raise HTTPValidatorConfigError("validator_config.url is required")
    if len(value) > MAX_HTTP_URL_LENGTH or "\x00" in value:
        raise HTTPValidatorConfigError(_INVALID_URL_ERROR)
    if not value.startswith("https://"):
        raise HTTPValidatorConfigError("validator_config.url must use HTTPS")

    parsed_tuple = _safe_parse_url(value)
    if parsed_tuple is None:
        raise HTTPValidatorConfigError(_INVALID_URL_ERROR)
    parsed, _hostname, _port = parsed_tuple
    if not _parsed_url_is_canonical_https(parsed):
        raise HTTPValidatorConfigError(_INVALID_URL_ERROR)
    if check_destination and is_blocked_url(value):
        raise HTTPValidatorConfigError("validator_config.url must not target private or reserved addresses")
    return value


def _normalize_method(value: object) -> str:
    """Return a supported HTTP method without coercion."""
    if not isinstance(value, str) or value not in _ALLOWED_METHODS:
        raise HTTPValidatorConfigError("validator_config.method must be GET or POST")
    return value


def _normalize_timeout(value: object) -> int:
    """Return a bounded integer timeout without Boolean coercion."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HTTP_TIMEOUT:
        raise HTTPValidatorConfigError("validator_config.timeout must be an integer between 1 and 30")
    return value


def _normalize_headers(value: object) -> dict[str, str]:
    """Validate bounded non-reserved headers with case-insensitive uniqueness."""
    if not isinstance(value, dict):
        raise HTTPValidatorConfigError("validator_config.headers must be an object")
    if len(value) > MAX_HTTP_HEADERS:
        raise HTTPValidatorConfigError("validator_config.headers has too many entries")

    normalized: dict[str, str] = {}
    seen_names: set[str] = set()
    for name, header_value in value.items():
        lowered_name = _normalize_header_name(name, seen_names)
        _validate_header_value(header_value)
        seen_names.add(lowered_name)
        normalized[name] = header_value
    return normalized


def _parsed_url_is_canonical_https(parsed: ParseResult) -> bool:
    """Return whether a parsed URL keeps HTTPS and contains no userinfo."""
    return parsed.scheme == "https" and parsed.username is None and parsed.password is None


def _normalize_header_name(name: object, seen_names: set[str]) -> str:
    """Return one canonical comparison name or reject it."""
    if not isinstance(name, str) or len(name) > 100 or not _HEADER_NAME_RE.fullmatch(name):
        raise HTTPValidatorConfigError("validator_config contains an invalid header name")
    lowered_name = name.lower()
    if lowered_name in _RESERVED_HEADERS:
        raise HTTPValidatorConfigError("validator_config contains a reserved header name")
    if lowered_name in seen_names:
        raise HTTPValidatorConfigError("validator_config contains duplicate header names")
    return lowered_name


def _validate_header_value(value: object) -> None:
    """Reject non-string, oversized, or framing-unsafe header values."""
    if not isinstance(value, str) or len(value) > 2048 or any(char in value for char in ("\x00", "\r", "\n")):
        raise HTTPValidatorConfigError("validator_config contains an invalid header value")


def normalize_http_validator_config(
    value: object,
    *,
    check_destination: bool = True,
) -> dict[str, Any]:
    """Validate and return the canonical HTTP validator configuration.

    Runtime callers disable the edit-time destination check because their
    pinned resolver is the sole DNS decision and independently rejects every
    unsafe address. Write callers keep the default and reject an unsafe
    destination before persistence.
    """
    if not isinstance(value, dict):
        raise HTTPValidatorConfigError("validator_config is required for HTTP flags")
    if "protocol" in value:
        return _normalize_receipt_config(value)
    unknown_keys = set(value) - _ALLOWED_CONFIG_KEYS
    if unknown_keys:
        raise HTTPValidatorConfigError("validator_config contains unknown fields")

    return {
        "url": _normalize_url(value.get("url"), check_destination=check_destination),
        "method": _normalize_method(value.get("method", "POST")),
        "timeout": _normalize_timeout(value.get("timeout", DEFAULT_HTTP_TIMEOUT)),
        "headers": _normalize_headers(value.get("headers", {})),
    }


def _normalize_receipt_config(value: dict[str, Any]) -> dict[str, Any]:
    """Validate the selection-only receipt-v1 organizer configuration."""
    if set(value) != _RECEIPT_CONFIG_KEYS or value.get("protocol") != "receipt-v1":
        raise HTTPValidatorConfigError("validator_config receipt protocol is invalid")
    profile_id = value.get("profile_id")
    objective_id = value.get("objective_id")
    if not isinstance(profile_id, str) or not isinstance(objective_id, str):
        raise HTTPValidatorConfigError("validator_config receipt profile and objective are required")
    from ._receipt_profiles import get_receipt_profile

    profile = get_receipt_profile(profile_id)
    if profile is None or objective_id not in profile.permitted_objectives:
        raise HTTPValidatorConfigError("validator_config receipt profile or objective is not available")
    return {
        "protocol": "receipt-v1",
        "profile_id": profile_id,
        "objective_id": objective_id,
    }
