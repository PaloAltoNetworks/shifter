"""
Custom template filters for user-related display.
"""

from django import template

register = template.Library()


@register.filter
def initials(email):
    """
    Extract initials from an email address.

    Examples:
        - "john.doe@example.com" -> "JD"
        - "alice@example.com" -> "AL"
        - "bob.smith.jr@example.com" -> "BS"

    Returns two uppercase characters for the user avatar display.
    """
    if not email:
        return "??"

    # Get the local part before @
    local_part = email.split("@")[0] if "@" in email else email

    # Try to split by common separators
    parts = []
    for sep in [".", "_", "-"]:
        if sep in local_part:
            parts = [p for p in local_part.split(sep) if p]
            break

    if len(parts) >= 2:
        # Use first char of first two parts
        return (parts[0][0] + parts[1][0]).upper()
    elif local_part:
        # Use first two chars of the local part
        return local_part[:2].upper()
    else:
        return "??"
