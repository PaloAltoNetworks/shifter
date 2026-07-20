"""Notification and bracket forms for CTF management."""

from __future__ import annotations

from typing import Any

from django import forms

from ctf.models import CTFBracket, CTFEvent, CTFNotification

from ._common import DATETIME_LOCAL_FORMAT, DATETIME_SECONDS_FORMAT


class CTFNotificationForm(forms.ModelForm):
    """Form for creating notifications."""

    class Meta:
        """Model/field configuration for `CTFNotificationForm`."""

        model = CTFNotification
        fields = [
            "notification_type",
            "subject",
            "body",
            "recipient_filter",
            "scheduled_at",
        ]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 6}),
            "scheduled_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format=DATETIME_LOCAL_FORMAT,
            ),
        }

    def __init__(self, *args: Any, event: CTFEvent | None = None, **kwargs: Any) -> None:
        """Initialize form with event context.

        Args:
            event: The CTFEvent this notification belongs to.
        """
        super().__init__(*args, **kwargs)
        self.event = event

        # Set input formats for datetime fields
        if "scheduled_at" in self.fields:
            self.fields["scheduled_at"].input_formats = [  # type: ignore[attr-defined]
                DATETIME_LOCAL_FORMAT,
                DATETIME_SECONDS_FORMAT,
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ]

        # Add CSS classes
        for _field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} form-control".strip()


class CTFBracketForm(forms.ModelForm):
    """Form for creating and editing brackets."""

    class Meta:
        """Model/field configuration for `CTFBracketForm`."""

        model = CTFBracket
        fields = [
            "name",
            "description",
            "display_order",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: Any, event: CTFEvent | None = None, **kwargs: Any) -> None:
        """Initialize form with event context.

        Args:
            event: The CTFEvent this bracket belongs to.
        """
        super().__init__(*args, **kwargs)
        self.event = event

        # Add CSS classes
        for _field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} form-control".strip()

    def save(self, commit: bool = True) -> CTFBracket:
        """Save bracket with event assignment.

        Args:
            commit: Whether to save to database.

        Returns:
            The saved bracket instance.
        """
        bracket = super().save(commit=False)

        if self.event:
            bracket.event = self.event

        if commit:
            bracket.save()

        return bracket
