"""Shared exceptions for cross-layer error handling.

These exceptions are raised by service layers and caught by
presentation layers.
"""


class CMSError(Exception):
    """Base exception for CMS service errors.

    Raised for business logic failures such as:
    - Resource not found
    - Access denied / ownership violation
    - Resource is deleted
    """

    pass


class AssetError(Exception):
    """Error raised when an asset operation fails.

    Raised for failures such as:
    - Invalid operating system
    - S3 storage failures
    """

    pass
