"""Shared exceptions for cross-layer error handling.

These exceptions are raised by service layers and caught by
presentation layers.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CMSError(Exception):
    """Base exception for CMS service errors.

    Raised for business logic failures such as:
    - Resource not found
    - Access denied / ownership violation
    - Resource is deleted

    Attributes:
        message: Human-readable error description.
        details: Optional structured details for logging/debugging.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize CMSError.

        Args:
            message: Human-readable error description.
            details: Optional structured details for logging/debugging.
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation."""
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class AssetError(Exception):
    """Error raised when an asset operation fails.

    Raised for failures such as:
    - Invalid operating system
    - S3 storage failures
    - Asset validation errors

    Attributes:
        message: Human-readable error description.
        asset_type: Type of asset that failed (e.g., 'agent', 'image').
        details: Optional structured details for logging/debugging.
    """

    def __init__(
        self,
        message: str,
        asset_type: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize AssetError.

        Args:
            message: Human-readable error description.
            asset_type: Type of asset that failed.
            details: Optional structured details for logging/debugging.
        """
        super().__init__(message)
        self.message = message
        self.asset_type = asset_type
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation."""
        parts = [self.message]
        if self.asset_type:
            parts.append(f"asset_type={self.asset_type}")
        if self.details:
            parts.append(f"details={self.details}")
        return " ".join(parts)


class ValidationError(Exception):
    """Error raised when data validation fails.

    Raised for failures such as:
    - Invalid field values
    - Missing required fields
    - Schema validation errors

    Attributes:
        message: Human-readable error description.
        field: Name of the field that failed validation.
        value: The invalid value (sanitized for logging).
    """

    def __init__(
        self,
        message: str,
        field: str | None = None,
        value: Any = None,
    ) -> None:
        """Initialize ValidationError.

        Args:
            message: Human-readable error description.
            field: Name of the field that failed validation.
            value: The invalid value (will be sanitized).
        """
        super().__init__(message)
        self.message = message
        self.field = field
        # Sanitize value to avoid logging sensitive data
        self.value = self._sanitize_value(value)

    @staticmethod
    def _sanitize_value(value: Any) -> str:
        """Sanitize value for safe logging."""
        if value is None:
            return "None"
        str_value = str(value)
        if len(str_value) > 50:
            return f"{str_value[:50]}..."
        return str_value

    def __str__(self) -> str:
        """Return string representation."""
        parts = [self.message]
        if self.field:
            parts.append(f"field={self.field}")
        if self.value:
            parts.append(f"value={self.value}")
        return " ".join(parts)


class ProvisioningError(Exception):
    """Error raised during resource provisioning.

    Raised for failures such as:
    - Infrastructure creation failures
    - Resource configuration errors
    - Timeout during provisioning

    Attributes:
        message: Human-readable error description.
        resource_type: Type of resource being provisioned (e.g., 'range', 'ngfw').
        resource_id: Identifier of the resource that failed.
        details: Optional structured details for logging/debugging.
    """

    def __init__(
        self,
        message: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize ProvisioningError.

        Args:
            message: Human-readable error description.
            resource_type: Type of resource being provisioned.
            resource_id: Identifier of the resource that failed.
            details: Optional structured details for logging/debugging.
        """
        super().__init__(message)
        self.message = message
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation."""
        parts = [self.message]
        if self.resource_type:
            parts.append(f"resource_type={self.resource_type}")
        if self.resource_id:
            parts.append(f"resource_id={self.resource_id}")
        if self.details:
            parts.append(f"details={self.details}")
        return " ".join(parts)
