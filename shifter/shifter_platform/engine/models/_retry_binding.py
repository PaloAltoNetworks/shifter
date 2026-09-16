"""Public-operation retry binding: a caller retry key -> one server-owned operation.

ADR-063 (#2086). Public clients supply a retry key so a lost launch response can
be recovered without duplicating effects. This row is the idempotency/admission
*index* for the retry identity ``(deployment_scope, actor_key, action,
caller_key)`` bound to an existing server-owned ``request_id`` + ``operation_id``
generation and the canonical intent digest.

It is NOT a second execution ledger (ADR-043-R3/R4): it never owns lifecycle,
status truth, results, or effects -- those stay in ``Request``/``Range`` and the
``OperationInput``/``OperationResultInbox`` operation state. PostgreSQL uniqueness
on the retry identity arbitrates concurrent first use.
"""

from django.db import models


class RetryBindingStatus(models.TextChoices):
    """Binding lifecycle, distinct from operation, launch, and range status."""

    ACTIVE = "ACTIVE", "Active"
    # A tombstone retains the key -> operation association (and its recovery
    # obligations) for the advertised retry window even after the operation is
    # terminal, so a late lost-response replay still recovers the same operation
    # rather than minting a duplicate. Reuse of an expired key must be explicit.
    TOMBSTONE = "TOMBSTONE", "Tombstone"


class PublicOperationRetryBinding(models.Model):
    """Bind one caller retry key to one operation generation and its intent."""

    deployment_scope = models.CharField(max_length=190)
    # Stable actor identity (a session and a user-owned token for the same actor
    # share it; resolved via shared.api.principals.active_actor_user).
    actor_key = models.CharField(max_length=64)
    # ``<resource>:<operation>`` -- e.g. ``raes-range:provision``.
    action = models.CharField(max_length=64)
    caller_key = models.CharField(max_length=200)
    request_id = models.UUIDField(editable=False, db_index=True)
    # The operation generation bound at first use. Nullable because the generation
    # can be minted asynchronously after the request is created; the current
    # generation is always resolvable from the request's range, and this column
    # caches the association once known (ADR-063-R1).
    operation_id = models.UUIDField(editable=False, null=True, blank=True, db_index=True)
    # "sha256:" + 64 hex characters -- the canonical immutable-intent digest.
    intent_digest = models.CharField(max_length=71)
    intent_projection_version = models.CharField(max_length=16)
    status = models.CharField(
        max_length=16,
        default=RetryBindingStatus.ACTIVE,
        choices=RetryBindingStatus.choices,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        """Table configuration for public-operation retry bindings."""

        db_table = "engine_public_operation_retry_binding"
        constraints = [
            models.UniqueConstraint(
                fields=["deployment_scope", "actor_key", "action", "caller_key"],
                name="uq_public_operation_retry_key",
            )
        ]

    def __str__(self) -> str:
        return f"PublicOperationRetryBinding {self.action}:{self.caller_key} -> {self.operation_id}"
