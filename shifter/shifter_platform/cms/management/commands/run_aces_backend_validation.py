"""Live validation for the Shifter ACES-native provisioning path (#1264).

Launches a registered ACES package through the normal portal / CMS / engine /
provisioner path (``create_range_dispatch`` -> ``create_aces_native_range``),
polls it to READY, reads back the redacted operation receipt / status / runtime
snapshot evidence, and asserts the backend really provisioned (an accepted
receipt, a succeeded status, and a snapshot with at least one realized resource:
"no vacuous pass"). It always tears the range down by ``request_id`` and maps
failures to bounded, sanitized diagnostics.

This is the ACES-cutover evidence path (ADR-031): run it in a deployed
environment with ``SHIFTER_ACES_NATIVE_PROVISIONING=true`` against a registered
ACES package to prove the native path end to end. Design source:
``docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md``.
"""

from __future__ import annotations

import logging
import os
import time
from argparse import ArgumentParser
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.crypto import get_random_string

from cms import services as cms_services
from cms.aces.validation import AcesEvidenceError, collect_evidence, validate_evidence
from shared.enums import RangeSource, ResourceStatus
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

_DEFAULT_TIMEOUT_SECONDS = 1800
_DEFAULT_POLL_SECONDS = 15


class Command(BaseCommand):
    """Provision an ACES package natively, verify its evidence, and tear it down."""

    help = "Live-validate the ACES-native provisioning path and its redacted evidence"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--scenario",
            default=os.environ.get("SHIFTER_ACES_VALIDATION_SCENARIO", ""),
            help="Registered ACES scenario_id to launch (or SHIFTER_ACES_VALIDATION_SCENARIO)",
        )
        parser.add_argument("--poll-interval", type=int, default=_DEFAULT_POLL_SECONDS)
        parser.add_argument("--timeout", type=int, default=_DEFAULT_TIMEOUT_SECONDS)
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Do not tear the range down (leave it for manual inspection)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        self._assert_flag_enabled()
        scenario = str(options["scenario"]).strip()
        if not scenario:
            raise CommandError("--scenario (or SHIFTER_ACES_VALIDATION_SCENARIO) is required")

        user = self._load_validation_user()
        request_id: UUID | None = None
        failure: Exception | None = None
        # Any failure is captured and re-raised below as a bounded, sanitized
        # CommandError, so teardown always runs and no raw detail escapes.
        try:
            request_id = self._launch(user, scenario)
            self._wait_until_ready(request_id, int(options["timeout"]), int(options["poll_interval"]))
            self._validate_evidence(request_id)
            self.stdout.write(self.style.SUCCESS(f"ACES backend validation passed (scenario={scenario})"))
        except Exception as exc:
            failure = exc
            logger.exception("ACES backend validation failed")
        finally:
            if request_id is not None and not options["keep"]:
                self._teardown(user, request_id)
        if failure is not None:
            raise CommandError(safe_log_value(str(failure))) from failure

    @staticmethod
    def _assert_flag_enabled() -> None:
        """Refuse to run unless the ACES-native provisioning flag is on."""
        if not settings.ACES_NATIVE_PROVISIONING_ENABLED:
            raise CommandError("SHIFTER_ACES_NATIVE_PROVISIONING must be enabled for ACES backend validation")

    def _load_validation_user(self) -> User:
        """Resolve or create the portal user that owns validation-provisioned ranges."""
        email = os.environ.get("SMOKE_TEST_USER_EMAIL", "").strip()
        if not email:
            raise CommandError("SMOKE_TEST_USER_EMAIL is required")
        user_model = get_user_model()
        user = user_model.objects.filter(email__iexact=email).first()
        if user is not None:
            return user
        user = user_model.objects.create_user(username=email, email=email, password=get_random_string(32))
        logger.info("run_aces_backend_validation: created user id=%s email=%s", user.id, safe_log_value(email))
        return user

    def _launch(self, user: User, scenario: str) -> UUID:
        """Launch the ACES package through the product dispatch (routes to native)."""
        context = cms_services.create_range_dispatch(user, scenario, {}, range_source=RangeSource.MISSION_CONTROL)
        if context.request_id is None:
            raise CommandError("launch returned no request_id")
        request_id = UUID(str(context.request_id))
        self.stdout.write(f"launched request_id={request_id} scenario={scenario}")
        return request_id

    def _wait_until_ready(self, request_id: UUID, timeout: int, poll_interval: int) -> None:
        """Poll the CMS range status by request_id until READY or timeout/FAILED."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            instance_pk = cms_services.find_range_instance_id_by_request(request_id)
            if instance_pk is not None:
                status = cms_services.get_range_status_by_id(instance_pk)
                if status == ResourceStatus.READY.value:
                    self.stdout.write(f"range READY request_id={request_id}")
                    return
                if status == ResourceStatus.FAILED.value:
                    raise CommandError(f"range FAILED before READY (request_id={request_id})")
            time.sleep(poll_interval)
        raise CommandError(f"timed out after {timeout}s waiting for READY (request_id={request_id})")

    def _validate_evidence(self, request_id: UUID) -> None:
        """Read the redacted evidence and assert real, non-vacuous realization."""
        try:
            summary = collect_evidence(request_id)
        except AcesEvidenceError as exc:
            raise CommandError(f"evidence redaction violation: {exc}") from exc
        problems = validate_evidence(summary)
        if problems:
            raise CommandError("ACES evidence incomplete: " + "; ".join(problems))
        self.stdout.write(
            f"evidence ok: receipts={summary.receipt_count} statuses={summary.status_count} "
            f"snapshots={summary.snapshot_count} resources={summary.snapshot_resource_count}"
        )

    def _teardown(self, user: User, request_id: UUID) -> None:
        """Tear the validation range down by request_id (best effort)."""
        try:
            cms_services.destroy_range_by_request_id(user, str(request_id))
            self.stdout.write(f"destroy requested for request_id={request_id}")
        except Exception:
            logger.exception("ACES backend validation cleanup failed for request_id=%s", request_id)
