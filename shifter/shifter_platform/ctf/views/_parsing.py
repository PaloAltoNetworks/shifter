"""Request-body parsing helpers and bracket-filter resolution."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFBracket,
    )

logger = logging.getLogger(__name__)


class _BodyUUIDError(ValueError):
    """Raised by `_parse_body_uuid` for missing or malformed request-body UUIDs.

    Used to keep the JSON API error envelope consistent (400 with a
    `{"error": ...}` payload) when a caller posts a non-UUID value. Caught
    locally; never propagates out of a view.
    """


def _parse_body_uuid(value: object, field_name: str) -> UUID:
    """Parse a request-body UUID, raising `_BodyUUIDError` on failure.

    Centralizes the "convert a string from `request.body` JSON into a UUID"
    step so every JSON API endpoint maps malformed values to a 400 response
    instead of leaking `ValueError` / `TypeError` up to Django and returning
    500. Views call this and `except _BodyUUIDError` to render a normal
    400 envelope.
    """
    if not isinstance(value, str) or not value:
        raise _BodyUUIDError(f"{field_name} is required")
    try:
        return UUID(value)
    except (ValueError, TypeError) as e:
        raise _BodyUUIDError(f"Invalid {field_name}") from e


class _BodyParseError(ValueError):
    """Raised by `_parse_body_object` for malformed JSON request bodies.

    Codex review (cycle 3) flagged that JSON endpoints accepted non-object
    bodies (e.g. `[]`, `"x"`, `42`) without validation, then either
    silently fell into default branches or crashed with `AttributeError`
    on `.get(...)` — producing 500s instead of the documented 400 JSON
    envelope.
    """


def _parse_body_object(request: HttpRequest, *, allow_empty: bool = False) -> dict[str, Any]:
    """Parse `request.body` as a JSON object, raising `_BodyParseError`.

    Single source of truth for the "decode a JSON object from a request
    body" step that every JSON write endpoint needs. Returns a `dict`;
    every other top-level JSON value (array, string, number, null) is
    rejected with 400.

    Args:
        request: The Django request whose `body` to decode.
        allow_empty: When True, an empty body returns `{}`. Used by
            endpoints whose POST body is optional (e.g. `api_use_hint`).

    Returns:
        The decoded JSON object as a dict.

    Raises:
        _BodyParseError: when the body is not valid JSON, or when the
            top-level JSON value is not an object.
    """
    drf_body = getattr(request, "_ctf_drf_body_data", None)
    if drf_body is not None:
        if getattr(request, "_ctf_drf_body_empty", False) and not allow_empty:
            raise _BodyParseError("Request body is required")
        if not isinstance(drf_body, dict):
            raise _BodyParseError("Request body must be a JSON object")
        return dict(drf_body)

    raw = request.body
    if not raw:
        if allow_empty:
            return {}
        raise _BodyParseError("Request body is required")
    try:
        decoded = json.loads(raw)
    except ValueError as e:
        # Catches both `json.JSONDecodeError` (subclass of ValueError) and
        # `UnicodeDecodeError` (also a ValueError subclass — non-UTF-8
        # bytes), so every malformed-body call gets the same 400 envelope
        # instead of a leaked 500. Listing the subclasses explicitly is
        # redundant (SonarCloud python:S5713).
        raise _BodyParseError("Invalid JSON") from e
    if not isinstance(decoded, dict):
        raise _BodyParseError("Request body must be a JSON object")
    return decoded


def _get_body_str(body: dict[str, Any], field_name: str, *, default: str = "", required: bool = False) -> str:
    """Pull a string-typed field from a parsed body, raising _BodyParseError on type mismatch.

    Codex review (cycle 6): JSON callers passing `null`, an integer, an
    array, etc. for a field the view treats as a string previously caused
    `AttributeError` on `.strip()` and a 500. Centralise the type check
    so every endpoint produces the same 400 envelope.
    """
    if field_name not in body:
        if required:
            raise _BodyParseError(f"{field_name} is required")
        return default
    value = body[field_name]
    if value is None:
        if required:
            raise _BodyParseError(f"{field_name} is required")
        return default
    if not isinstance(value, str):
        raise _BodyParseError(f"{field_name} must be a string")
    return value


def _resolve_bracket_filter(
    event_id: UUID, bracket_param: str | None
) -> tuple[list[CTFBracket], CTFBracket | None, UUID | None]:
    """Resolve bracket filter from query parameter.

    Args:
        event_id: UUID of the event.
        bracket_param: Raw bracket ID string from request.GET.get("bracket").

    Returns:
        Tuple of (brackets list, selected_bracket object or None, bracket_id UUID or None).
    """
    from ctf.services.bracket import list_brackets

    brackets = list(list_brackets(event_id))
    selected_bracket = None
    bracket_id = None
    if bracket_param:
        for b in brackets:
            if str(b.id) == bracket_param:
                selected_bracket = b
                bracket_id = b.id
                break
    return brackets, selected_bracket, bracket_id
