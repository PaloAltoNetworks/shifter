"""CTF-specific exceptions.

Custom exception hierarchy for CTF operations, providing clear error categorization
and context for error handling.
"""

from __future__ import annotations

from typing import Any


class CTFError(Exception):
    """Base exception for all CTF-related errors.

    Attributes:
        message: Human-readable error description.
        code: Machine-readable error code for API responses.
        details: Additional context for debugging.
    """

    default_code: str = "CTF_ERROR"

    def __init__(
        self,
        message: str,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize CTF error.

        Args:
            message: Human-readable error description.
            code: Machine-readable error code. Defaults to class default_code.
            details: Additional context for debugging.
        """
        self.message = message
        self.code = code or self.default_code
        self.details = details or {}
        super().__init__(message)

    def __str__(self) -> str:
        """Return string representation with code and message."""
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses.

        Returns:
            Dictionary with error details.
        """
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class CTFValidationError(CTFError):
    """Validation error for CTF data.

    Raised when input data fails validation (e.g., invalid dates, missing fields).
    """

    default_code: str = "CTF_VALIDATION_ERROR"


class CTFNotFoundError(CTFError):
    """Resource not found error.

    Raised when a requested CTF resource (event, challenge, participant) doesn't exist.
    """

    default_code: str = "CTF_NOT_FOUND"


class CTFPermissionError(CTFError):
    """Permission denied error.

    Raised when a user attempts an action they're not authorized to perform.
    """

    default_code: str = "CTF_PERMISSION_DENIED"


class CTFStateError(CTFError):
    """Invalid state transition error.

    Raised when an operation is invalid for the current state
    (e.g., starting an already active event).
    """

    default_code: str = "CTF_INVALID_STATE"


class CTFRateLimitError(CTFError):
    """Rate limit exceeded error.

    Raised when a user exceeds allowed request rate (e.g., flag submissions).
    """

    default_code: str = "CTF_RATE_LIMIT_EXCEEDED"


class CTFRangeError(CTFError):
    """Range provisioning/management error.

    Raised when range operations fail.
    """

    default_code: str = "CTF_RANGE_ERROR"


class CTFNotificationError(CTFError):
    """Notification sending error.

    Raised when email/notification sending fails.
    """

    default_code: str = "CTF_NOTIFICATION_ERROR"
