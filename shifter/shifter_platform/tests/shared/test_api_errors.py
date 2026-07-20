"""Tests for shared DRF API error-envelope helpers."""

from __future__ import annotations

from types import SimpleNamespace

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, Throttled, ValidationError

from shared.api.errors import api_error_response, api_exception_handler


def _context(request_id: str = "req-test"):
    return {"request": SimpleNamespace(META={"HTTP_X_REQUEST_ID": request_id})}


def test_validation_errors_use_standard_api_envelope() -> None:
    response = api_exception_handler(
        ValidationError({"name": ["This field is required."]}),
        _context(),
    )

    assert response is not None
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {
        "error": {
            "code": "invalid",
            "message": "Invalid request",
            "details": {"name": ["This field is required."]},
            "request_id": "req-test",
        }
    }


def test_authentication_errors_do_not_echo_raw_exception_text() -> None:
    response = api_exception_handler(AuthenticationFailed("Invalid or expired API token"), _context("req-auth"))

    assert response is not None
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.data == {
        "error": {
            "code": "authentication_failed",
            "message": "Authentication failed",
            "request_id": "req-auth",
        }
    }


def test_throttled_errors_render_a_stable_throttle_message() -> None:
    # DRF's Throttled detail ("...Expected available in N seconds") contains the
    # token "expected", which the keyword classifier would otherwise mislabel as
    # a validation error ("Invalid request"). A 429 must render the stable
    # throttle message instead (issue #322 surfaced the first 429 responses).
    response = api_exception_handler(Throttled(wait=60), _context("req-throttle"))

    assert response is not None
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.data == {
        "error": {
            "code": "throttled",
            "message": "Request was throttled",
            "request_id": "req-throttle",
        }
    }


def test_manual_error_response_uses_same_shape() -> None:
    response = api_error_response(
        code="bad_request",
        message="Risk is not deleted",
        status_code=status.HTTP_400_BAD_REQUEST,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {"error": {"code": "bad_request", "message": "Risk is not deleted"}}
