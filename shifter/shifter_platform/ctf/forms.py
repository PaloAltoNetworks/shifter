"""CTF forms - Form classes for CTF management.

This module provides Django forms for:
- Event creation and editing
- Challenge creation and editing
- Participant management
- Notification creation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django import forms
from django.core.exceptions import ValidationError

from ctf.models import CTFBracket, CTFChallenge, CTFEvent, CTFNotification, CTFParticipant

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CTFEventForm(forms.ModelForm):
    """Form for creating and editing CTF events.

    Handles validation of:
    - Event timing (end after start, registration before start)
    - Team mode settings (team_size_limit required if team_mode)
    - Cleanup settings
    - Range configuration (ngfw_enabled)
    - Scenario selection (dropdown populated from CMS registry)
    """

    ngfw_enabled = forms.BooleanField(
        required=False,
        label="Enable NGFW",
        help_text="Provision a Next-Generation Firewall for each participant range",
    )

    scenario_id = forms.ChoiceField(
        label="Scenario",
        help_text="Select the range scenario template to use",
        widget=forms.Select(),
    )

    class Meta:
        model = CTFEvent
        fields = [
            "name",
            "description",
            "event_start",
            "event_end",
            "registration_deadline",
            "scenario_id",
            "auto_cleanup",
            "cleanup_delay_hours",
            "range_spinup_minutes",
            "max_participants",
            "team_mode",
            "team_size_limit",
            "submission_cooldown_seconds",
            "attempt_limit_mode",
            "attempt_limit_cooldown_seconds",
            "rating_visibility",
            "scoreboard_visible",
            "scoreboard_freeze_at",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "event_start": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "event_end": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "registration_deadline": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "scoreboard_freeze_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        """Initialize form with scenario dropdown and datetime-local format support.

        Args:
            user: The requesting user, used to filter available scenarios.
        """
        super().__init__(*args, **kwargs)
        self._user = user

        # Populate scenario dropdown from CMS registry
        if user is not None:
            from ctf.bridges import cms_list_scenarios

            scenario_choices = [("", "Select a scenario...")]
            scenario_choices += cms_list_scenarios(user)
            self.fields["scenario_id"].choices = scenario_choices
        else:
            # No user context — accept any value (used in tests / programmatic use)
            self.fields["scenario_id"] = forms.CharField(max_length=50)

        # Set input formats for datetime fields
        datetime_fields = ["event_start", "event_end", "registration_deadline", "scoreboard_freeze_at"]
        for field_name in datetime_fields:
            if field_name in self.fields:
                self.fields[field_name].input_formats = [
                    "%Y-%m-%dT%H:%M",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M",
                ]

        # Populate ngfw_enabled from range_config on edit
        if self.instance and self.instance.pk:
            rc = self.instance.range_config or {}
            self.fields["ngfw_enabled"].initial = rc.get("ngfw_enabled", False)

        # Add CSS classes for styling
        for _field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} form-control".strip()

        # Add is-invalid CSS class to fields with errors (Bootstrap 5 pattern)
        if self.is_bound and self.errors:
            for field_name in self.errors:
                if field_name in self.fields:
                    css = self.fields[field_name].widget.attrs.get("class", "")
                    self.fields[field_name].widget.attrs["class"] = f"{css} is-invalid".strip()

    def clean(self) -> dict:
        """Validate form data."""
        cleaned_data = super().clean()
        if cleaned_data is None:
            return {}

        # Only validate if we have the values (required field errors handled separately)
        event_start = cleaned_data.get("event_start")
        event_end = cleaned_data.get("event_end")
        registration_deadline = cleaned_data.get("registration_deadline")
        team_mode = cleaned_data.get("team_mode", False)
        team_size_limit = cleaned_data.get("team_size_limit")

        # Validate event times
        if event_start and event_end and event_end <= event_start:
            self.add_error(
                "event_end",
                "Event end must be after event start.",
            )

        # Validate registration deadline
        if registration_deadline and event_start and registration_deadline > event_start:
            self.add_error(
                "registration_deadline",
                "Registration deadline must be before event start.",
            )

        # Validate team settings
        if team_mode:
            if not team_size_limit:
                self.add_error(
                    "team_size_limit",
                    "Team size limit is required when team mode is enabled.",
                )
        elif team_size_limit:
            # Clear team_size_limit if team_mode is disabled
            cleaned_data["team_size_limit"] = None

        # Validate scenario_id exists in the registry
        scenario_id = cleaned_data.get("scenario_id")
        if scenario_id and self._user is not None:
            from ctf.bridges import cms_list_scenarios

            valid_ids = {sid for sid, _ in cms_list_scenarios(self._user)}
            if scenario_id not in valid_ids:
                self.add_error("scenario_id", "Selected scenario is not available.")

        return cleaned_data

    def save(self, commit: bool = True) -> CTFEvent:
        """Save event with range_config packed from form fields."""
        event = super().save(commit=False)

        # Pack ngfw_enabled into range_config
        rc = event.range_config or {}
        rc["ngfw_enabled"] = self.cleaned_data.get("ngfw_enabled", False)
        event.range_config = rc

        if commit:
            event.save()

        return event


class CTFChallengeForm(forms.ModelForm):
    """Form for creating and editing CTF challenges.

    Handles:
    - Flag hashing (plain flag input -> bcrypt hash)
    - Hint validation
    - Release time validation
    """

    # Plain flag input - will be hashed on save
    flag = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="Enter the flag value (will be hashed for storage)",
    )

    # Comma-separated tag names (M2M handled in save)
    tag_list = forms.CharField(
        max_length=500,
        required=False,
        help_text="Comma-separated tags (e.g. XDR, Linux, Windows)",
    )

    # Comma-separated topic names (M2M handled in save)
    topic_list = forms.CharField(
        max_length=500,
        required=False,
        help_text="Comma-separated topics (e.g. SQL Injection, Privilege Escalation)",
    )

    class Meta:
        model = CTFChallenge
        fields = [
            "name",
            "description",
            "category",
            "points",
            "difficulty",
            "flag_format",
            "solution",
            "max_attempts",
            "release_time",
            "order",
            "target_instance_name",
            "target_port",
            "next_challenge",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "solution": forms.Textarea(attrs={"rows": 6}),
            "release_time": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, event=None, **kwargs):
        """Initialize form with event context.

        Args:
            event: The CTFEvent this challenge belongs to.
        """
        super().__init__(*args, **kwargs)
        self.event = event

        # Set input formats for datetime fields
        if "release_time" in self.fields:
            self.fields["release_time"].input_formats = [
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ]

        # Populate tag_list and topic_list from existing M2M on edit
        if self.instance.pk and not self.instance._state.adding:
            self.fields["tag_list"].initial = ", ".join(self.instance.tags.values_list("name", flat=True))
            self.fields["topic_list"].initial = ", ".join(self.instance.topics.values_list("name", flat=True))

        # Filter next_challenge to same-event challenges, excluding self
        if event:
            qs = CTFChallenge.objects.filter(event=event, deleted_at__isnull=True)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            self.fields["next_challenge"].queryset = qs
        self.fields["next_challenge"].required = False

        # Flag is required for new challenges
        if self.instance._state.adding:
            self.fields["flag"].required = True
        else:
            self.fields["flag"].help_text = "Leave blank to keep existing flag"

        # Add CSS classes
        for _field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} form-control".strip()

    def clean(self) -> dict:
        """Validate form data."""
        cleaned_data = super().clean()
        if cleaned_data is None:
            return {}

        release_time = cleaned_data.get("release_time")

        # Validate release time within event bounds
        if release_time and self.event:
            if release_time < self.event.event_start:
                self.add_error(
                    "release_time",
                    "Release time cannot be before event start.",
                )
            if release_time > self.event.event_end:
                self.add_error(
                    "release_time",
                    "Release time cannot be after event end.",
                )

        return cleaned_data

    def save(self, commit: bool = True) -> CTFChallenge:
        """Save challenge with flag hashing.

        Creates a CTFFlag record for the flag. Also sets the legacy flag_hash
        field on the challenge for backward compatibility.

        Args:
            commit: Whether to save to database.

        Returns:
            The saved challenge instance.
        """
        from ctf.services.challenge import hash_flag

        challenge = super().save(commit=False)
        is_new = challenge._state.adding

        # Hash the flag if provided
        flag = self.cleaned_data.get("flag")
        if flag:
            challenge.flag_hash = hash_flag(flag)

        # Set event if provided
        if self.event:
            challenge.event = self.event

        if commit:
            challenge.save()

            # Create a CTFFlag record for the flag
            if flag:
                from ctf.models import CTFFlag

                if is_new:
                    # New challenge: create the first flag record
                    CTFFlag.objects.create(
                        challenge=challenge,
                        flag_hash=challenge.flag_hash,
                        flag_type="static",
                        case_sensitive=True,
                        order=0,
                    )

            # Handle tags (M2M)
            tag_list_str = self.cleaned_data.get("tag_list", "")
            if tag_list_str is not None:
                from ctf.services.challenge import _resolve_tags

                tag_names = [t.strip() for t in tag_list_str.split(",") if t.strip()]
                event = self.event or challenge.event
                tag_objects = _resolve_tags(event, tag_names)
                challenge.tags.set(tag_objects)

            # Handle topics (M2M)
            topic_list_str = self.cleaned_data.get("topic_list", "")
            if topic_list_str is not None:
                from ctf.services.challenge import _resolve_topics

                topic_names = [t.strip() for t in topic_list_str.split(",") if t.strip()]
                topic_objects = _resolve_topics(topic_names)
                challenge.topics.set(topic_objects)

        return challenge


class CTFParticipantForm(forms.ModelForm):
    """Form for adding/editing individual participants."""

    class Meta:
        model = CTFParticipant
        fields = [
            "email",
            "name",
            "bracket",
        ]

    def __init__(self, *args, event=None, **kwargs):
        """Initialize form with event context.

        Args:
            event: The CTFEvent this participant belongs to.
        """
        super().__init__(*args, **kwargs)
        self.event = event

        # Filter bracket choices to this event's brackets
        if event:
            self.fields["bracket"].queryset = CTFBracket.objects.filter(event=event)
        else:
            self.fields["bracket"].queryset = CTFBracket.objects.none()

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

    def clean_csv_file(self):
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


class CTFNotificationForm(forms.ModelForm):
    """Form for creating notifications."""

    class Meta:
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
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, event=None, **kwargs):
        """Initialize form with event context.

        Args:
            event: The CTFEvent this notification belongs to.
        """
        super().__init__(*args, **kwargs)
        self.event = event

        # Set input formats for datetime fields
        if "scheduled_at" in self.fields:
            self.fields["scheduled_at"].input_formats = [
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ]

        # Add CSS classes
        for _field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} form-control".strip()


class EventStatusForm(forms.Form):
    """Form for changing event status."""

    action = forms.ChoiceField(
        choices=[
            ("schedule", "Open Registration"),
            ("activate", "Activate Event"),
            ("pause", "Pause Event"),
            ("resume", "Resume Event"),
            ("complete", "End Event"),
            ("archive", "Archive Event"),
            ("cancel", "Cancel Event"),
        ],
    )

    def __init__(self, *args, event=None, **kwargs):
        """Initialize form with event context.

        Args:
            event: The CTFEvent to change status for.
        """
        super().__init__(*args, **kwargs)
        self.event = event

        # Filter available actions based on current status
        if event:
            from ctf.enums import EventStatus

            available_actions = []
            status = event.status

            if status == EventStatus.DRAFT.value:
                available_actions = [("schedule", "Open Registration"), ("cancel", "Cancel Event")]
            elif status == EventStatus.REGISTRATION.value:
                available_actions = [("activate", "Activate Event"), ("cancel", "Cancel Event")]
            elif status == EventStatus.ACTIVE.value:
                available_actions = [
                    ("pause", "Pause Event"),
                    ("complete", "End Event"),
                    ("cancel", "Cancel Event"),
                ]
            elif status == EventStatus.PAUSED.value:
                available_actions = [("resume", "Resume Event"), ("cancel", "Cancel Event")]
            elif status == EventStatus.ENDED.value:
                available_actions = [("archive", "Archive Event")]

            self.fields["action"].choices = available_actions


class CTFBracketForm(forms.ModelForm):
    """Form for creating and editing brackets."""

    class Meta:
        model = CTFBracket
        fields = [
            "name",
            "description",
            "display_order",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, event=None, **kwargs):
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
