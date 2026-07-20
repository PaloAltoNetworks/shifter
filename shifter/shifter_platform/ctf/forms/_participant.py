"""Participant management forms for CTF management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.core.exceptions import ValidationError

from ctf.models import CTFBracket, CTFEvent, CTFParticipant

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile


class CTFParticipantForm(forms.ModelForm):
    """Form for adding/editing individual participants."""

    class Meta:
        """Model/field configuration for `CTFParticipantForm`."""

        model = CTFParticipant
        fields = [
            "email",
            "name",
            "bracket",
        ]

    def __init__(self, *args: Any, event: CTFEvent | None = None, **kwargs: Any) -> None:
        """Initialize form with event context.

        Args:
            event: The CTFEvent this participant belongs to.
        """
        super().__init__(*args, **kwargs)
        self.event = event

        # Filter bracket choices to this event's brackets
        if event:
            self.fields["bracket"].queryset = CTFBracket.objects.filter(event=event)  # type: ignore[attr-defined]
        else:
            self.fields["bracket"].queryset = CTFBracket.objects.none()  # type: ignore[attr-defined]

        # Add CSS classes
        for _field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} form-control".strip()

    def save(self, commit: bool = True) -> CTFParticipant:
        """Save participant with event assignment.

        Args:
            commit: Whether to save to database.

        Returns:
            The saved participant instance.
        """
        participant = super().save(commit=False)

        if self.event:
            participant.event = self.event

        if commit:
            participant.save()

        return participant


class CTFParticipantImportForm(forms.Form):
    """Form for bulk importing participants via CSV."""

    csv_file = forms.FileField(
        help_text="CSV file with columns: email, name",
        widget=forms.FileInput(attrs={"accept": ".csv"}),
    )

    def clean_csv_file(self) -> UploadedFile | None:
        """Validate CSV file format."""
        csv_file = self.cleaned_data.get("csv_file")

        if csv_file:
            # Check file extension
            if not csv_file.name.endswith(".csv"):
                raise ValidationError("File must be a CSV file.")

            # Check file size (max 1MB)
            if csv_file.size > 1024 * 1024:
                raise ValidationError("File size must be less than 1MB.")

        return csv_file


class CTFParticipantBatchForm(forms.Form):
    """Bounded generated-account batch request."""

    count = forms.IntegerField(min_value=1, max_value=100, initial=10)


class CTFParticipantRenameForm(forms.Form):
    """Organizer-controlled username rename."""

    username = forms.CharField(max_length=49)


class CTFParticipantEmailForm(forms.Form):
    """Optional delivery-email attachment."""

    email = forms.EmailField(required=False)
