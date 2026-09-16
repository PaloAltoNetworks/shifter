"""Workspace resource-quota policy, decisions, and reservations (PLAT-239, #1946).

Quota is tenant-entitlement policy owned by the ``workspaces`` domain, distinct
from Engine provider-capacity accounting, API throttling, billing, and the
per-``(user, range_source)`` active-range constraint (ADR-046-R10,
``docs/architecture/workspace-resource-quotas-preflight-1946.md``). Only
``workspaces`` imports these models; every other layer goes through
``workspaces.services`` with a scalar ``workspace_id``.

Three cohesive shapes:

* :class:`WorkspaceQuotaPolicy` — the configured limit + enforcement mode for a
  ``(workspace, resource)``. A missing policy means unlimited (compatibility).
* :class:`WorkspaceQuotaDecision` — append-only evidence of every configured-policy
  evaluation, pinning the policy/usage/outcome facts so administrators can see
  when and why a cap applied.
* :class:`WorkspaceQuotaReservation` — a durable, idempotent open reservation for
  count-based resources (initially ``concurrent_ranges``). Open reservations
  (``released_at IS NULL``) are the authoritative concurrent-range usage; a row is
  released only on terminal ``FAILED``/``DESTROYED`` convergence.
"""

from django.db import models

from shared.capacity.contract import EnforcementMode

#: Intra-domain workspace FK target and its shared help text, reused by every
#: quota model so the tenancy boundary is declared in exactly one place.
_WORKSPACE_FK = "workspaces.Workspace"
_WORKSPACE_FK_HELP = "Owning workspace (intra-domain FK)."

#: Closed resource vocabulary. ``concurrent_ranges`` counts open workspace launch
#: reservations; ``member_seats`` counts canonical ``WorkspaceMembership`` rows.
QUOTA_RESOURCE_CONCURRENT_RANGES = "concurrent_ranges"
QUOTA_RESOURCE_MEMBER_SEATS = "member_seats"
QUOTA_RESOURCE_CHOICES = (
    (QUOTA_RESOURCE_CONCURRENT_RANGES, "Concurrent ranges"),
    (QUOTA_RESOURCE_MEMBER_SEATS, "Member seats"),
)
WORKSPACE_QUOTA_RESOURCE_VALUES = frozenset(value for value, _ in QUOTA_RESOURCE_CHOICES)

#: Enforcement vocabulary reuses ``shared.capacity.EnforcementMode`` terms only:
#: ``advisory`` is the soft cap (warn, record, admit); ``enforcing`` is the hard
#: cap (record, block). Reusing the two-value vocabulary does not reuse Engine
#: capacity models, providers, or reason codes.
QUOTA_MODE_ADVISORY = EnforcementMode.ADVISORY.value
QUOTA_MODE_ENFORCING = EnforcementMode.ENFORCING.value
QUOTA_MODE_CHOICES = (
    (QUOTA_MODE_ADVISORY, "Advisory (soft cap)"),
    (QUOTA_MODE_ENFORCING, "Enforcing (hard cap)"),
)
WORKSPACE_QUOTA_MODE_VALUES = frozenset(value for value, _ in QUOTA_MODE_CHOICES)

#: Closed decision-outcome vocabulary.
QUOTA_OUTCOME_ADMITTED = "admitted"
QUOTA_OUTCOME_WARNED = "warned"
QUOTA_OUTCOME_REJECTED = "rejected"
QUOTA_OUTCOME_CHOICES = (
    (QUOTA_OUTCOME_ADMITTED, "Admitted"),
    (QUOTA_OUTCOME_WARNED, "Warned (soft cap applied)"),
    (QUOTA_OUTCOME_REJECTED, "Rejected (hard cap applied)"),
)
WORKSPACE_QUOTA_OUTCOME_VALUES = frozenset(value for value, _ in QUOTA_OUTCOME_CHOICES)


class WorkspaceQuotaPolicy(models.Model):
    """A configured per-``(workspace, resource)`` limit and enforcement mode.

    Policy is a platform guardrail: it is authored only by a superuser-only
    ``workspaces.services`` command and can never be raised or removed by
    workspace-role authority. ``revision`` is bumped on every change so a decision
    row can pin the exact policy it evaluated against.
    """

    workspace = models.ForeignKey(
        _WORKSPACE_FK,
        on_delete=models.CASCADE,
        related_name="quota_policies",
        help_text=_WORKSPACE_FK_HELP,
    )
    resource = models.CharField(
        max_length=32,
        choices=QUOTA_RESOURCE_CHOICES,
        help_text="Closed resource code the limit applies to.",
    )
    limit = models.PositiveIntegerField(help_text="Maximum allowed usage for the resource (non-negative).")
    mode = models.CharField(
        max_length=16,
        choices=QUOTA_MODE_CHOICES,
        help_text="'advisory' warns and records; 'enforcing' blocks the over-limit action.",
    )
    revision = models.PositiveIntegerField(
        default=1,
        help_text="Bumped on every policy change; pinned on each quota decision.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        db_table = "workspaces_quota_policy"
        ordering = ["workspace_id", "resource"]
        verbose_name = "Workspace quota policy"
        verbose_name_plural = "Workspace quota policies"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "resource"],
                name="uniq_quota_policy_per_workspace_resource",
            ),
            models.CheckConstraint(
                condition=models.Q(resource__in=WORKSPACE_QUOTA_RESOURCE_VALUES),
                name="quota_policy_resource_closed_vocabulary",
            ),
            models.CheckConstraint(
                condition=models.Q(mode__in=WORKSPACE_QUOTA_MODE_VALUES),
                name="quota_policy_mode_closed_vocabulary",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return f"{self.resource}<={self.limit} ({self.mode})"


class WorkspaceQuotaDecision(models.Model):
    """Append-only evidence of one configured-policy quota evaluation.

    Every evaluation of a configured policy is recorded — admitted, warned, or
    rejected — pinning the policy limit/mode/revision, the usage observed before
    the requested delta, the outcome, a bounded reason code, trusted actor
    attribution, and the stable correlation key. Rows are never mutated; the
    matching ``shared.audit`` event for a warning or rejection is a cross-cutting
    projection of this evidence, not a second ledger.
    """

    workspace = models.ForeignKey(
        _WORKSPACE_FK,
        on_delete=models.CASCADE,
        related_name="quota_decisions",
        help_text=_WORKSPACE_FK_HELP,
    )
    resource = models.CharField(max_length=32, choices=QUOTA_RESOURCE_CHOICES)
    limit_at_decision = models.PositiveIntegerField(help_text="Policy limit evaluated against.")
    mode_at_decision = models.CharField(max_length=16, choices=QUOTA_MODE_CHOICES)
    policy_revision = models.PositiveIntegerField(help_text="Policy revision evaluated against.")
    usage_before = models.PositiveIntegerField(help_text="Usage observed before the requested delta.")
    requested_delta = models.PositiveIntegerField(default=1, help_text="Units the action would add.")
    outcome = models.CharField(max_length=16, choices=QUOTA_OUTCOME_CHOICES)
    reason_code = models.CharField(max_length=64, help_text="Bounded machine-readable reason.")
    actor_type = models.CharField(max_length=32, blank=True)
    actor_id = models.PositiveIntegerField(null=True, blank=True)
    correlation_key = models.CharField(max_length=64, blank=True, help_text="Stable per-action correlation key.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        """Model metadata."""

        db_table = "workspaces_quota_decision"
        ordering = ["-created_at", "-id"]
        verbose_name = "Workspace quota decision"
        verbose_name_plural = "Workspace quota decisions"
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="idx_quota_decision_ws_time"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(resource__in=WORKSPACE_QUOTA_RESOURCE_VALUES),
                name="quota_decision_resource_closed_vocabulary",
            ),
            models.CheckConstraint(
                condition=models.Q(outcome__in=WORKSPACE_QUOTA_OUTCOME_VALUES),
                name="quota_decision_outcome_closed_vocabulary",
            ),
            models.CheckConstraint(
                condition=models.Q(mode_at_decision__in=WORKSPACE_QUOTA_MODE_VALUES),
                name="quota_decision_mode_closed_vocabulary",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return f"{self.resource}:{self.outcome}"


class WorkspaceQuotaReservation(models.Model):
    """A durable, idempotent open reservation for a count-based resource.

    Used for ``concurrent_ranges``: the CMS launch-admission seam creates one open
    reservation keyed on the pre-minted request UUID under the workspace mutex,
    and the convergent range-status path releases it (sets ``released_at``) only on
    terminal ``FAILED``/``DESTROYED`` state — never at ``DESTROYING`` or CMS soft
    delete. Open reservations are the authoritative usage; the unique constraint
    makes reserve and release idempotent under event redelivery.
    """

    workspace = models.ForeignKey(
        _WORKSPACE_FK,
        on_delete=models.CASCADE,
        related_name="quota_reservations",
        help_text=_WORKSPACE_FK_HELP,
    )
    resource = models.CharField(max_length=32, choices=QUOTA_RESOURCE_CHOICES)
    correlation_key = models.CharField(
        max_length=64, help_text="Stable per-action correlation key (e.g. request UUID)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(
        null=True,
        blank=True,
        default=None,
        db_index=True,
        help_text="Set when the reservation is released on terminal convergence; NULL while open.",
    )

    class Meta:
        """Model metadata."""

        db_table = "workspaces_quota_reservation"
        ordering = ["workspace_id", "resource", "id"]
        verbose_name = "Workspace quota reservation"
        verbose_name_plural = "Workspace quota reservations"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "resource", "correlation_key"],
                name="uniq_quota_reservation_per_correlation",
            ),
            models.CheckConstraint(
                condition=models.Q(resource__in=WORKSPACE_QUOTA_RESOURCE_VALUES),
                name="quota_reservation_resource_closed_vocabulary",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        state = "open" if self.released_at is None else "released"
        return f"{self.resource}:{self.correlation_key} ({state})"
