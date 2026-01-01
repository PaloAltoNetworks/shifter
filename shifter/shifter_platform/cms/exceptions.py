"""CMS service exceptions."""


class CMSError(Exception):
    """Base exception for CMS service errors.

    Raised for business logic failures such as:
    - Resource not found
    - Access denied / ownership violation
    - Resource is deleted
    """

    pass
