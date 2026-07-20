"""Event and event-status forms for CTF management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib.auth.password_validation import validate_password

from ctf.models import CTFEvent

from ._common import CANCEL_EVENT_LABEL, DATETIME_LOCAL_FORMAT, DATETIME_SECONDS_FORMAT

if TYPE_CHECKING:
    from django.contrib.auth.models import User


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
        """Model/field configuration for `CTFEventForm`."""

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
            "participant_password_override",
            "range_spinup_minutes",
            "max_participants",
            "team_mode",
            "team_size_limit",
            "submission_cooldown_seconds",
            "attempt_limit_mode",
            "attempt_limit_cooldown_seconds",
            "rating_visibility",
            "scoring_mode",
            "scoreboard_visibility",
            "scoreboard_freeze_at",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "participant_password_override": forms.PasswordInput(
                attrs={"autocomplete": "new-password"},
                render_value=True,
            ),
            "event_start": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format=DATETIME_LOCAL_FORMAT,
            ),
            "event_end": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format=DATETIME_LOCAL_FORMAT,
            ),
            "registration_deadline": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format=DATETIME_LOCAL_FORMAT,
            ),
            "scoreboard_freeze_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format=DATETIME_LOCAL_FORMAT,
            ),
        }

    def clean_participant_password_override(self) -> str:
        value = self.cleaned_data.get("participant_password_override", "")
        if value:
            validate_password(value)
        return value

    def __init__(self, *args: Any, user: User | None = None, **kwargs: Any) -> None:
        """Initialize form with scenario dropdown and datetime-local format support.

        Args:
            user: The requesting user, used to filter available scenarios.
        """
        super().__init__(*args, **kwargs)
        self._user = user

        self._populate_scenario_choices(user)
        self._apply_datetime_input_formats()

        # Populate ngfw_enabled from range_config on edit
        if self.instance and self.instance.pk:
            rc = self.instance.range_config or {}
            self.fields["ngfw_enabled"].initial = rc.get("ngfw_enabled", False)

        self._apply_bootstrap_css_classes()

    def _populate_scenario_choices(self, user: User | None) -> None:
        """Populate the scenario dropdown from the CMS registry, or accept any value."""
        if user is not None:
            from ctf.bridges import cms_list_scenarios

            scenario_choices = [("", "Select a scenario...")]
            scenario_choices += cms_list_scenarios(user)
            self.fields["scenario_id"].choices = scenario_choices  # type: ignore[attr-defined]
        else:
            # No user context — accept any value (used in tests / programmatic use)
            self.fields["scenario_id"] = forms.CharField(max_length=50)

    def _apply_datetime_input_formats(self) -> None:
        datetime_fields = ["event_start", "event_end", "registration_deadline", "scoreboard_freeze_at"]
        for field_name in datetime_fields:
            if field_name in self.fields:
                self.fields[field_name].input_formats = [  # type: ignore[attr-defined]
                    DATETIME_LOCAL_FORMAT,
                    DATETIME_SECONDS_FORMAT,
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M",
                ]

    def _apply_bootstrap_css_classes(self) -> None:
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

    def clean(self) -> dict[str, Any]:
        """Validate form data."""
        cleaned_data = super().clean()
        if cleaned_data is None:
            return {}

        self._validate_event_times(cleaned_data)
        self._validate_team_settings(cleaned_data)
        self._validate_scenario(cleaned_data)
        return cleaned_data

    def _validate_event_times(self, cleaned_data: dict[str, Any]) -> None:
        event_start = cleaned_data.get("event_start")
        event_end = cleaned_data.get("event_end")
        registration_deadline = cleaned_data.get("registration_deadline")

        if event_start and event_end and event_end <= event_start:
            self.add_error(
                "event_end",
                "Event end must be after event start.",
            )

        if registration_deadline and event_start and registration_deadline > event_start:
            self.add_error(
                "registration_deadline",
                "Registration deadline must be before event start.",
            )

    def _validate_team_settings(self, cleaned_data: dict[str, Any]) -> None:
        team_mode = cleaned_data.get("team_mode", False)
        team_size_limit = cleaned_data.get("team_size_limit")

        if team_mode:
            if not team_size_limit:
                self.add_error(
                    "team_size_limit",
                    "Team size limit is required when team mode is enabled.",
                )
        elif team_size_limit:
            # Clear team_size_limit if team_mode is disabled
            cleaned_data["team_size_limit"] = None

    def _validate_scenario(self, cleaned_data: dict[str, Any]) -> None:
        scenario_id = cleaned_data.get("scenario_id")
        if scenario_id and self._user is not None:
            from ctf.bridges import cms_list_scenarios

            valid_ids = {sid for sid, _ in cms_list_scenarios(self._user)}
            if scenario_id not in valid_ids:
                self.add_error("scenario_id", "Selected scenario is not available.")

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
            ("cancel", CANCEL_EVENT_LABEL),
        ],
    )

    def __init__(self, *args: Any, event: CTFEvent | None = None, **kwargs: Any) -> None:
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
                available_actions = [("schedule", "Open Registration"), ("cancel", CANCEL_EVENT_LABEL)]
            elif status == EventStatus.REGISTRATION.value:
                available_actions = [("activate", "Activate Event"), ("cancel", CANCEL_EVENT_LABEL)]
            elif status == EventStatus.ACTIVE.value:
                available_actions = [
                    ("pause", "Pause Event"),
                    ("complete", "End Event"),
                    ("cancel", CANCEL_EVENT_LABEL),
                ]
            elif status == EventStatus.PAUSED.value:
                available_actions = [("resume", "Resume Event"), ("cancel", CANCEL_EVENT_LABEL)]
            elif status == EventStatus.ENDED.value:
                available_actions = [("archive", "Archive Event")]

            self.fields["action"].choices = available_actions  # type: ignore[attr-defined]
