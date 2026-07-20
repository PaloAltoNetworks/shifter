"""Operator CLI to register a content pack (#1578, ADR-034).

A thin entrypoint onto :func:`cms.services.register_pack`. The service owns
authorization (WHO may register, not entitlement), foreign-input pack validation,
no-shadow / duplicate rejection, and audit; this command only parses arguments,
resolves the actor, and maps domain failures to a ``CommandError`` (never a
traceback).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError, CommandParser

from cms.exceptions import CMSError
from cms.services import PackRegistrationRequest, register_pack

if TYPE_CHECKING:
    from django.contrib.auth.models import User

user_model = get_user_model()


class Command(BaseCommand):
    """Register a content pack through the uniform ingestion service."""

    help = "Register a content pack through the uniform, entitlement-blind ingestion service (#1578)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the source-agnostic registration arguments."""
        parser.add_argument("--scenario-id", required=True, help="Catalog id for the pack.")
        parser.add_argument("--source-kind", default="repo", help="repo | object (default: repo).")
        parser.add_argument("--contract-kind", default="aces", help="Package contract kind (default: aces).")
        parser.add_argument("--contract-profile", default="shifter", help="Contract profile (default: shifter).")
        parser.add_argument("--package-ref", required=True, help="Pack root path/key.")
        parser.add_argument("--package-version", required=True, help="Immutable package version/ref.")
        parser.add_argument("--package-digest", required=True, help="Package digest 'sha256:<64 hex>'.")
        parser.add_argument("--lock-ref", default="", help="Lock artifact path/key.")
        parser.add_argument("--lock-digest", default="", help="Lock artifact digest.")
        parser.add_argument("--provenance", default="", help="JSON object of bounded provenance references.")
        parser.add_argument("--actor", required=True, help="Username of the registering user.")

    def handle(self, *args: Any, **options: Any) -> None:
        """Resolve the actor and register the pack, surfacing failures cleanly."""
        actor = self._resolve_actor(options["actor"])
        request = PackRegistrationRequest(
            scenario_id=options["scenario_id"],
            source_kind=options["source_kind"],
            contract_kind=options["contract_kind"],
            contract_profile=options["contract_profile"],
            package_ref=options["package_ref"],
            package_version=options["package_version"],
            package_digest=options["package_digest"],
            lock_ref=options["lock_ref"],
            lock_digest=options["lock_digest"],
            provenance=self._parse_provenance(options["provenance"]),
        )
        try:
            result = register_pack(user=actor, request=request)
        except (CMSError, PermissionDenied, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Registered pack '{result.scenario_id}' "
                f"({result.source_kind}, conformance={result.conformance_status})"
            )
        )

    def _resolve_actor(self, username: str) -> User:
        """Return the registering user or raise a clean ``CommandError``."""
        try:
            return user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"actor '{username}' not found") from exc

    def _parse_provenance(self, raw: str) -> dict[str, Any]:
        """Parse the optional ``--provenance`` JSON object argument."""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CommandError("--provenance must be valid JSON") from exc
        if not isinstance(data, dict):
            raise CommandError("--provenance must be a JSON object")
        return data
