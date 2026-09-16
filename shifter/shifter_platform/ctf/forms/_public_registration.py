"""Bounded form for the public event-registration browser surface."""

from django import forms


class PublicRegistrationForm(forms.Form):
    """The complete public signup input allowlist."""

    name = forms.CharField(max_length=200, strip=True)
    email = forms.EmailField(max_length=254)
