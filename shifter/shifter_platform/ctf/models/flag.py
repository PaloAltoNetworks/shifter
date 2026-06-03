"""CTFFlag — challenge flags.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging

from django.db import models

from ._base import CTFBaseModel

logger = logging.getLogger(__name__)


class CTFFlag(CTFBaseModel):
    """Individual flag for a CTF challenge.

    Supports multiple flags per challenge where any correct flag constitutes a solve.
    Each flag independently supports different types and case sensitivity.

    Attributes:
        challenge: The challenge this flag belongs to.
        flag_hash: Hashed flag value (static), regex pattern (regex), or sentinel
            value for programmable/http types.
        flag_type: Type of flag verification.
        case_sensitive: Whether flag comparison is case-sensitive.
        order: Display order for admin UI.
        validator_config: JSON configuration for programmable/http validators.
    """

    FLAG_TYPE_CHOICES = [
        ("static", "Static (hashed comparison)"),
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
    flag_hash = models.CharField(
        max_length=255,
        help_text="Hashed flag value (static), regex pattern (regex), or sentinel for programmable/http",
    )
    flag_type = models.CharField(
        max_length=20,
        choices=FLAG_TYPE_CHOICES,
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

    def __str__(self) -> str:
        """Return flag description."""
        return f"Flag #{self.order} ({self.flag_type}) for {self.challenge.name}"
