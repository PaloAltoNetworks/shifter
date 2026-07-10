"""Tests for shared DRF API error-envelope helpers."""

from __future__ import annotations

from types import SimpleNamespace

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError

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


def test_manual_error_response_uses_same_shape() -> None:
    response = api_error_response(
        code="bad_request",
        message="Risk is not deleted",
        status_code=status.HTTP_400_BAD_REQUEST,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {"error": {"code": "bad_request", "message": "Risk is not deleted"}}
