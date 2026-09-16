"""Standard DRF error envelope for the platform API."""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from shared.errors import classify_user_message, safe_user_message

_REQUIRED_FIELD_MESSAGE = "This field is required."

_STATUS_MESSAGES = {
    status.HTTP_400_BAD_REQUEST: "Invalid request",
    status.HTTP_401_UNAUTHORIZED: "Authentication failed",
    status.HTTP_403_FORBIDDEN: "Permission denied",
    status.HTTP_404_NOT_FOUND: "Resource not found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Method not allowed",
    status.HTTP_429_TOO_MANY_REQUESTS: "Request was throttled",
}

_VALIDATION_DETAIL_MESSAGES = {
    "blank": "This field may not be blank.",
    "invalid": "Invalid value.",
    "max_length": "Value is too long.",
    "min_length": "Value is too short.",
    "null": "This field may not be null.",
    "required": _REQUIRED_FIELD_MESSAGE,
}

_VALIDATION_DETAIL_TEXT_MESSAGES = {
    "Agent name is required": "Agent name is required",
    "Do not supply a password for generated mode.": "Do not supply a password for generated mode.",
    "Either 'agents' or 'agent_id' is required": "Either 'agents' or 'agent_id' is required",
    "Filename is required": "Filename is required",
    "Invalid agent type.": "Invalid agent type.",
    "Invalid credential type.": "Invalid credential type.",
    "Provide at least one of 'enabled' or 'staff_only'.": "Provide at least one of 'enabled' or 'staff_only'.",
    "Request body must be a JSON object": "Request body must be a JSON object",
    _REQUIRED_FIELD_MESSAGE: _REQUIRED_FIELD_MESSAGE,
    "This field is required for set mode.": "This field is required for set mode.",
    "Unknown event status.": "Unknown event status.",
    "Unknown field.": "Unknown field.",
    "Valid file size is required": "Valid file size is required",
    "agent_id is required": "agent_id is required",
    "from_date must not be later than to_date.": "from_date must not be later than to_date.",
    "request_id or range_id is required": "request_id or range_id is required",
}


def api_exception_handler(exc: Exception, context: dict[str, object]) -> Response | None:
    """Wrap DRF exceptions in the platform API error envelope."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    error: dict[str, object] = {
        "code": _error_code(exc),
        "message": _error_message(exc, response),
    }
    if isinstance(exc, ValidationError):
        error["details"] = _normalize_detail(response.data)
    request_id = _request_id(context.get("request"))
    if request_id:
        error["request_id"] = request_id

    response.data = {"error": error}
    return response


def api_error_response(
    *,
    code: str,
    message: str,
    status_code: int,
    details: object | None = None,
    request: object | None = None,
) -> Response:
    """Return an explicit API error using the same envelope as DRF exceptions."""
    error: dict[str, object] = {
        "code": code,
        "message": safe_user_message(message),
    }
    if details is not None:
        error["details"] = _normalize_detail(details)
    request_id = _request_id(request)
    if request_id:
        error["request_id"] = request_id
    return Response({"error": error}, status=status_code)


def _error_code(exc: Exception) -> str:
    """Return a stable API error code for a DRF exception."""
    code = getattr(exc, "default_code", None)
    if isinstance(code, str) and code:
        return code
    return "api_error"


def _error_message(exc: Exception, response: Response) -> str:
    """Return the safe user-facing message for an exception response."""
    if isinstance(exc, ValidationError):
        return _STATUS_MESSAGES[status.HTTP_400_BAD_REQUEST]
    # 429 has a known safe status message; do not route DRF's throttle detail
    # ("...Expected available in N seconds") through keyword classification,
    # whose "expected" validation token would mislabel it as "Invalid request".
    if response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_429_TOO_MANY_REQUESTS,
    ):
        return _STATUS_MESSAGES[response.status_code]

    default = _STATUS_MESSAGES.get(response.status_code, "Request could not be processed")
    return classify_user_message(_extract_detail(response.data), default=default)


def _extract_detail(data: object) -> object:
    """Extract DRF's conventional detail payload for message classification."""
    if isinstance(data, dict) and "detail" in data:
        return data["detail"]
    if isinstance(data, list):
        return " ".join(str(item) for item in data)
    return data


def _normalize_detail(data: object) -> object:
    """Convert validation details without reflecting exception text.

    ``ErrorDetail`` text can originate in validators and integrations.  Map its
    stable code to authored client text so an exception can never smuggle a
    traceback, credential, or backend response into the API envelope.
    """
    normalized = data
    if isinstance(data, ErrorDetail):
        normalized = _VALIDATION_DETAIL_TEXT_MESSAGES.get(
            str(data),
            _VALIDATION_DETAIL_MESSAGES.get(data.code, "Invalid value."),
        )
    elif isinstance(data, dict):
        normalized = {key: _normalize_detail(value) for key, value in data.items()}
    elif isinstance(data, list):
        normalized = [_normalize_detail(item) for item in data]
    return normalized


def _request_id(request: object | None) -> str | None:
    """Return a request correlation ID when middleware or headers provide one."""
    if request is None:
        return None
    request_id = getattr(request, "request_id", None)
    if request_id:
        return str(request_id)
    meta = getattr(request, "META", {})
    request_id = meta.get("HTTP_X_REQUEST_ID") if isinstance(meta, dict) else None
    return str(request_id) if request_id else None
