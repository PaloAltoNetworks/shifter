"""OIDC utilities for Cognito integration."""


def generate_username(email: str) -> str:
    """Generate username from email address.

    Cognito provides email in claims, use it as the username.
    """
    return email
