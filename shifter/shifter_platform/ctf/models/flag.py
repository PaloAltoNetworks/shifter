"""CTFFlag — challenge flags.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import models

from ._base import CTFBaseModel

logger = logging.getLogger(__name__)

# A static flag is accepted with or without its wrapper: ``FLAG{v}`` (any case of
# "flag"), ``{v}``, or bare ``v``. Stored and submitted values both pass through
# ``normalize_static_flag`` so they compare in one canonical form.
_FLAG_WRAPPER_PREFIX = "flag{"


def normalize_static_flag(value: str) -> str:
    """Return the canonical inner value of a static flag.

    Strips surrounding whitespace and one outer ``FLAG{...}`` (case-insensitive
    prefix) or ``{...}`` wrapper. Braces inside the value are left untouched.
    """
    normalized = value.strip()
    if normalized.endswith("}"):
        if normalized[: len(_FLAG_WRAPPER_PREFIX)].lower() == _FLAG_WRAPPER_PREFIX:
            normalized = normalized[len(_FLAG_WRAPPER_PREFIX) : -1]
        elif normalized.startswith("{"):
            normalized = normalized[1:-1]
    return normalized


def _flag_type_choices() -> list[tuple[str, str]]:
    """Built-in flag types plus extension-registered ones (CTF-1401)."""
    from ctf.extensions import registered_flag_types

    return list(CTFFlag.FLAG_TYPE_CHOICES) + [(t, t.title()) for t in sorted(registered_flag_types())]


class CTFFlag(CTFBaseModel):
    """Individual flag for a CTF challenge.

    Supports multiple flags per challenge where any correct flag constitutes a solve.
    Each flag independently supports different types and case sensitivity.

    Attributes:
        challenge: The challenge this flag belongs to.
        value: Normalized plaintext flag (static), regex pattern (regex), or
            sentinel value for programmable/http types.
        flag_type: Type of flag verification.
        case_sensitive: Whether flag comparison is case-sensitive.
        order: Display order for admin UI.
        validator_config: JSON configuration for programmable/http validators.
    """

    FLAG_TYPE_CHOICES = [
        ("static", "Static (exact match)"),
        ("regex", "Regex (pattern match)"),
        ("programmable", "Programmable (custom validator)"),
        ("http", "HTTP (external endpoint)"),
    ]

    challenge = models.ForeignKey(
        "CTFChallenge",
        on_delete=models.CASCADE,
        related_name="flags",
        help_text="Challenge this flag belongs to",
    )
    value = models.CharField(
        max_length=255,
        help_text="Plaintext static flag (normalized), regex pattern, or programmable/http sentinel",
    )
    flag_type = models.CharField(
        max_length=20,
        choices=_flag_type_choices,
        default="static",
        help_text="Flag verification type",
    )
    case_sensitive = models.BooleanField(
        default=True,
        help_text="Whether flag comparison is case-sensitive",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order in admin UI",
    )
    validator_config = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="Configuration for programmable/http validators",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_flag"
        ordering = ["order", "created_at"]
        verbose_name = "CTF Flag"
        verbose_name_plural = "CTF Flags"
        indexes = [
            models.Index(fields=["challenge", "flag_type"]),
        ]

    def clean(self) -> None:
        """Keep every static flag in its canonical stored form, whatever the write path."""
        super().clean()
        if self.flag_type == "static":
            self.value = normalize_static_flag(self.value)
            if not self.value:
                raise ValidationError({"value": "A static flag needs a value inside its wrapper."})

    def __str__(self) -> str:
        """Return flag description."""
        return f"Flag #{self.order} ({self.flag_type}) for {self.challenge.name}"
