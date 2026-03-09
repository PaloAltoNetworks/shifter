"""Text utility functions for the provisioner."""

import re


def validate_s3_path(value: str) -> bool:
    """Validate S3 bucket name or key doesn't contain shell injection characters.

    Args:
        value: S3 bucket name or key to validate.

    Returns:
        True if safe, False if potentially dangerous.
    """
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
    sanitized = name.lower().replace(" ", "-").replace("_", "-")
    sanitized = re.sub(r"[^a-z0-9-]", "", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip("-")
    return sanitized[:max_length]
