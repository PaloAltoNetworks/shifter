"""OIDC utilities for Cognito integration."""


def generate_username(email: str) -> str:
    """Use email as username instead of default sha1 hash.

    mozilla-django-oidc defaults to base64(sha1(email)) for privacy
    (usernames are often public). For this internal tool, readable
    emails in admin/logs/queries are more useful than hash obfuscation.
    """
    return email
