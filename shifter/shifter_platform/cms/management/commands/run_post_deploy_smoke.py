"""Run a live post-deploy range smoke test inside the portal Django context."""

from __future__ import annotations

import logging
import os
import time
from argparse import ArgumentParser
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.crypto import get_random_string

from cms import services as cms_services
from cms.post_deploy_smoke.probe import probe_rdp_endpoint, probe_ssh_endpoint
from cms.post_deploy_smoke.smoke_runner import build_agents_by_os, select_probe_target
from cms.post_deploy_smoke.variants import SmokeVariant, parse_variant
from engine.services import get_rdp_connection_info, get_ssh_connection_info
from shared.enums import ResourceStatus
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class Command(BaseCommand):
    """Provision, probe, and destroy a catalog range for post-deploy smoke."""

    help = "Provision a dev range, verify connectivity, and tear it down for post-deploy smoke"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--variant",
            default="linux",
            help="Smoke variant: linux (basic) or windows (ad_attack_lab)",
        )
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=15,
            help="Seconds between readiness polls",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        variant = parse_variant(str(options["variant"]))
        poll_interval = int(options["poll_interval"])
        user = self._load_smoke_user()
        request_id: UUID | None = None
        failure: Exception | None = None
        try:
            request_id = self._provision_range(user, variant)
            self._wait_until_ready(request_id, variant, poll_interval)
            self._verify_connectivity(user, request_id, variant)
            self.stdout.write(self.style.SUCCESS(f"post-deploy smoke passed ({variant.name})"))
        except Exception as exc:
            failure = exc
            logger.exception("post-deploy smoke failed")
        finally:
            if request_id is not None:
                try:
                    self._destroy_range(user, request_id)
                except Exception:
                    logger.exception("post-deploy smoke cleanup failed for request_id=%s", request_id)
        if failure is not None:
            raise CommandError(str(failure)) from failure

    def _load_smoke_user(self) -> User:
        """Resolve or create the portal user that owns smoke-provisioned ranges."""
        email = os.environ.get("SMOKE_TEST_USER_EMAIL", "").strip()
        if not email:
            raise CommandError("SMOKE_TEST_USER_EMAIL is required")
        user_model = get_user_model()
        user = user_model.objects.filter(email__iexact=email).first()
        if user is not None:
            return user
        user = user_model.objects.create_user(
            username=email,
            email=email,
            password=get_random_string(32),
        )
        logger.info(
            "run_post_deploy_smoke: created smoke user id=%s email=%s",
            user.id,
            safe_log_value(email),
        )
        self.stdout.write(f"created smoke user email={email}")
        return user

    def _provision_range(self, user: User, variant: SmokeVariant) -> UUID:
        agents_by_os = build_agents_by_os(variant)
        context = cms_services.create_range(
            user,
            variant.scenario_id,
            agents_by_os,
            ngfw_enabled=False,
        )
        if context.request_id is None:
            raise CommandError("create_range returned no request_id")
        request_id = UUID(str(context.request_id))
        self.stdout.write(f"provisioned request_id={request_id} scenario={variant.scenario_id}")
        return request_id

    def _wait_until_ready(self, request_id: UUID, variant: SmokeVariant, poll_interval: int) -> None:
        deadline = time.monotonic() + variant.provision_timeout_seconds
        while time.monotonic() < deadline:
            instance_pk = cms_services.find_range_instance_id_by_request(request_id)
            if instance_pk is not None:
                status = cms_services.get_range_status_by_id(instance_pk)
                if status == ResourceStatus.READY.value:
                    self.stdout.write(f"range READY request_id={request_id}")
                    return
            time.sleep(poll_interval)
        raise CommandError(
            f"timed out after {variant.provision_timeout_seconds}s waiting for READY (request_id={request_id})"
        )

    def _verify_connectivity(
        self,
        user: User,
        request_id: UUID,
        variant: SmokeVariant,
    ) -> None:
        range_context = cms_services.get_range_by_request_id(user, str(request_id))
        if range_context.status != ResourceStatus.READY:
            raise CommandError(f"range not READY for connectivity probe (status={range_context.status})")

        attacker_uuid = ""
        windows_uuid = None
        for inst in range_context.instances:
            if inst.role == "attacker" and inst.uuid:
                attacker_uuid = inst.uuid
            elif inst.role == "dc" and inst.uuid:
                windows_uuid = inst.uuid

        protocol, target_uuid = select_probe_target(
            variant,
            attacker_uuid=attacker_uuid,
            windows_uuid=windows_uuid,
        )
        deadline = time.monotonic() + variant.connectivity_timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if protocol == "ssh":
                    info = get_ssh_connection_info(user, target_uuid)
                    probe_ssh_endpoint(str(info["host"]), int(info["port"]))
                else:
                    info = get_rdp_connection_info(user, target_uuid)
                    probe_rdp_endpoint(str(info["host"]), 3389)
                self.stdout.write(f"{protocol} probe succeeded for instance {target_uuid}")
                return
            except Exception as exc:
                last_error = exc
                time.sleep(15)
        raise CommandError(f"connectivity probe failed: {last_error}")

    def _destroy_range(self, user: User, request_id: UUID) -> None:
        cms_services.destroy_range_by_request_id(user, str(request_id))
        self.stdout.write(f"destroy requested for request_id={request_id}")
