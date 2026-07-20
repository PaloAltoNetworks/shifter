"""Challenge form for CTF management."""

from __future__ import annotations

from typing import Any

from django import forms

from ctf.models import CTFChallenge, CTFEvent

from ._common import DATETIME_LOCAL_FORMAT, DATETIME_SECONDS_FORMAT


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
        """Model/field configuration for `CTFChallengeForm`."""

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
                format=DATETIME_LOCAL_FORMAT,
            ),
        }

    def __init__(self, *args: Any, event: CTFEvent | None = None, **kwargs: Any) -> None:
        """Initialize form with event context.

        Args:
            event: The CTFEvent this challenge belongs to.
        """
        super().__init__(*args, **kwargs)
        self.event = event

        # Set input formats for datetime fields
        if "release_time" in self.fields:
            self.fields["release_time"].input_formats = [  # type: ignore[attr-defined]
                DATETIME_LOCAL_FORMAT,
                DATETIME_SECONDS_FORMAT,
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ]

        # Populate tag_list and topic_list from existing M2M on edit
        if self.instance.pk and not self.instance._state.adding:
            self.fields["tag_list"].initial = ", ".join(self.instance.tags.values_list("name", flat=True))
            self.fields["topic_list"].initial = ", ".join(self.instance.topics.values_list("name", flat=True))

        # Filter next_challenge to same-event challenges, excluding self
        if event:
            # CTFChallenge.objects is a SoftDeleteManager, so deleted rows
            # are already excluded by default — no inline deleted_at filter
            # needed.
            qs = CTFChallenge.objects.filter(event=event)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            self.fields["next_challenge"].queryset = qs  # type: ignore[attr-defined]
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

    def clean(self) -> dict[str, Any]:
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

    # Persistence DELIBERATELY NOT in the form (codex review #765 cycle 5):
    # all challenge writes — JSON API and HTML admin — go through
    # `ctf.services.challenge.create_challenge` / `update_challenge` so the
    # actor-checked, allowlisted, multi-flag- and release-task-aware
    # service contract is the single source of truth. Admin views call
    # `to_service_data()` on a validated form, then pass the result to
    # the service with `actor_id=request.user.pk`.
    #
    # Override the inherited ModelForm.save() to fail loudly (codex cycle
    # 7): without this, a future caller (or test) calling `form.save()`
    # would silently fall back to `ModelForm.save()` and bypass the actor
    # check, the field allowlist, flag hashing, multi-flag handling,
    # tag/topic resolution, and release-task syncing the service contract
    # owns.
    def save(self, commit: bool = True) -> CTFChallenge:
        raise NotImplementedError(
            "CTFChallengeForm.save() is intentionally not implemented. Use "
            "`ctf.services.challenge.create_challenge` or `update_challenge` "
            "with the form's `to_service_data()` and an `actor_id`."
        )

    def to_service_data(self) -> dict[str, Any]:
        """Return a dict suitable for `create_challenge`/`update_challenge`.

        Must be called only after `is_valid()`.
        """
        cleaned = self.cleaned_data
        # Start from the ModelForm field set, drop the form-only helpers,
        # and add service-shape fields (flag, tags, topics).
        data: dict[str, Any] = {}
        for field in self.Meta.fields:
            if field in cleaned:
                data[field] = cleaned[field]
        flag = cleaned.get("flag")
        if flag:
            data["flag"] = flag
        tag_list_str = cleaned.get("tag_list")
        if tag_list_str is not None:
            data["tags"] = [t.strip() for t in tag_list_str.split(",") if t.strip()]
        topic_list_str = cleaned.get("topic_list")
        if topic_list_str is not None:
            data["topics"] = [t.strip() for t in topic_list_str.split(",") if t.strip()]
        return data
