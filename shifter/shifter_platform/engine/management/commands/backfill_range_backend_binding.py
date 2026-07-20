"""Operator backfill for a legacy range's #1666 backend/purpose ownership binding.

Pre-#1666 ranges carry no persisted backend binding. Destroy/reconcile of such a
range must not guess the backend from the mutable ``GCP_RANGE_BACKEND`` selector
(after a ``gdc -> gce`` flip that would strand the range), so the provisioner
fails closed with a ``prerequisite`` diagnostic when it cannot prove the backend
from durable ownership evidence.

This command is the explicit operator remediation the preflight prescribes: while
the historical selector is still known, set the range's backend (and trusted
purpose) under a row lock. It is write-once -- it refuses to overwrite an existing
binding -- and validates values through the single shared policy parser/enum.
"""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from engine.models import Range
from shared.range_instantiation_policy import (
    GcpRangeBackendError,
    InstantiationPurpose,
    normalize_gcp_range_backend,
)


class Command(BaseCommand):
    """Set the #1666 backend/purpose binding on a legacy range (write-once)."""

    help = "Back-fill a legacy range's range_backend/instantiation_purpose ownership binding (#1666)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Register the range selector and the binding values."""
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--request-id", help="engine_request.request_id (UUID) of the range")
        selector.add_argument("--range-id", type=int, help="engine Range primary key")
        parser.add_argument("--backend", required=True, help="Admitted backend: gce or gdc")
        parser.add_argument(
            "--purpose",
            default=InstantiationPurpose.LIVE_FIRE.value,
            help="Instantiation purpose (default: live_fire)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Validate the values and persist the binding under a row lock, write-once."""
        try:
            backend = normalize_gcp_range_backend(options["backend"])
        except GcpRangeBackendError as exc:
            raise CommandError(str(exc)) from exc
        try:
            purpose = InstantiationPurpose(str(options["purpose"]).strip().lower()).value
        except ValueError as exc:
            valid = ", ".join(p.value for p in InstantiationPurpose)
            raise CommandError(f"purpose must be one of: {valid}") from exc

        with transaction.atomic():
            range_obj = self._locked_range(options)
            if range_obj.range_backend or range_obj.instantiation_purpose:
                raise CommandError(
                    f"Range {range_obj.id} already has a backend binding "
                    f"({range_obj.range_backend}/{range_obj.instantiation_purpose}); the binding is "
                    "write-once and will not be overwritten."
                )
            range_obj.range_backend = backend
            range_obj.instantiation_purpose = purpose
            range_obj.save(update_fields=["range_backend", "instantiation_purpose", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"Set range {range_obj.id} binding to {backend}/{purpose} (#1666)"))

    def _locked_range(self, options: dict[str, Any]) -> Range:
        """Return the target range locked FOR UPDATE, or raise CommandError."""
        qs = Range.objects.select_for_update()
        request_id = options.get("request_id")
        try:
            if request_id:
                return qs.get(request__request_id=request_id)
            return qs.get(id=options["range_id"])
        except Range.DoesNotExist as exc:
            raise CommandError("No matching range found for the given selector") from exc
