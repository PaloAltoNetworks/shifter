"""Instance utilities for Shifter range provisioning.

Utility functions for instance configuration:
- S3 path validation for shell injection prevention
- Hostname sanitization for EC2 instances
"""

import re


def validate_s3_path(value: str) -> bool:
    """Validate S3 bucket name or key doesn't contain shell injection characters.

    Args:
        value: S3 bucket name or key to validate.

    Returns:
        True if safe, False if potentially dangerous.
    """
    # Allow alphanumeric, hyphens, underscores, forward slashes, dots, and equals
    # This covers valid S3 bucket names and common key patterns
    safe_pattern = re.compile(r"^[a-zA-Z0-9._/=-]+$")
    return bool(safe_pattern.match(value))


def sanitize_hostname(name: str, max_length: int = 20) -> str:
    """Sanitize a display name for use in a hostname.

    Args:
        name: Display name to sanitize (e.g., "Attacker", "Domain Controller").
        max_length: Maximum length for the sanitized name portion.

    Returns:
        Lowercase string with only a-z, 0-9, and hyphens, truncated to max_length.
    """
    # Lowercase and replace spaces/underscores with hyphens
    sanitized = name.lower().replace(" ", "-").replace("_", "-")
    # Remove any character that's not alphanumeric or hyphen
    sanitized = re.sub(r"[^a-z0-9-]", "", sanitized)
    # Collapse multiple consecutive hyphens into one
    sanitized = re.sub(r"-+", "-", sanitized)
    # Strip leading/trailing hyphens
    sanitized = sanitized.strip("-")
    # Truncate to max length
    return sanitized[:max_length]
