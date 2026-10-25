"""Bounded form for the public event-registration browser surface."""

from django import forms

from ctf.exceptions import CTFValidationError
from ctf.services.participant.accounts import normalize_participant_username


class PublicRegistrationForm(forms.Form):
    """The complete public signup input allowlist.

    The participant's single identity is the ``username``: it is the login handle
    and the public scoreboard display name (#2455). Email is only a delivery
    channel for login details.
    """

    username = forms.CharField(
        max_length=32,
        strip=True,
        label="Username",
        help_text="Your username will be publicly visible on scoreboards.",
    )
    email = forms.EmailField(max_length=254)

    def clean_username(self) -> str:
        """Validate the chosen handle with the canonical participant policy."""
        try:
            return normalize_participant_username(self.cleaned_data["username"])
        except CTFValidationError as exc:
            raise forms.ValidationError(str(exc)) from exc
