"""Environment variable validation utilities."""

import os
from typing import List


def validate_env_vars(required: List[str]) -> None:
    """
    Validate that required environment variables are set.

    Args:
        required: List of required environment variable names

    Raises:
        EnvironmentError: If any required variables are missing
    """
    missing = [var for var in required if var not in os.environ]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {missing}")


def get_env(name: str, default: str = None) -> str:
    """
    Get an environment variable with optional default.

    Args:
        name: Environment variable name
        default: Default value if not set (None means required)

    Returns:
        Environment variable value

    Raises:
        EnvironmentError: If variable is required (no default) and not set
    """
    value = os.environ.get(name, default)
    if value is None:
        raise EnvironmentError(f"Required environment variable not set: {name}")
    return value
