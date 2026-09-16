"""Unit tests for the ``initials`` user-display template filter."""

import pytest

from mission_control.templatetags.user_extras import initials


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        # Two-part local name -> first char of each part (user_extras.py:37).
        ("john.doe@example.com", "JD"),
        # Same branch via the underscore separator.
        ("bob_smith@example.com", "BS"),
        # Single-word local part -> first two characters.
        ("alice@example.com", "AL"),
        # Empty local part ("@..."): no parts and no local text, so the filter
        # returns the "??" fallback (user_extras.py:42).
        ("@example.com", "??"),
        # Missing / empty email short-circuits to the placeholder.
        (None, "??"),
        ("", "??"),
    ],
)
def test_initials(email, expected):
    assert initials(email) == expected
