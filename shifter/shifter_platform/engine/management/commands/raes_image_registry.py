"""Tenant management command for the RAES image registry (#1566, ADR-032-R2).

A headless surface for operators/automation to register, list, and disable
``engine.models.RaesImageMapping`` rows so the realizability registry can be
converged declaratively (for example in a deploy hook) without the SPA. Every
mutation delegates to the single validated write path in ``engine.services``
(``upsert_raes_image_mapping`` / ``disable_raes_image_mapping``); this command
owns only argument shape and non-secret stdout
summaries. Bounded failures raise ``CommandError``.

Examples::

    manage.py raes_image_registry --action list
    manage.py raes_image_registry --action register --provider gce \\
        --source-name alpine --source-version 3.19 \\
        --image-ref projects/x/global/images/alpine-3-19 --disk-size-gb 20
    manage.py raes_image_registry --action disable --provider gce \\
        --source-name alpine --source-version 3.19

"""

from __future__ import annotations

import logging
from argparse import ArgumentParser
from typing import TYPE_CHECKING, Any

from django.core.management.base import BaseCommand, CommandError

from engine.services import (
    RaesImageMappingError,
    RaesImageMappingOptions,
    disable_raes_image_mapping,
    list_raes_image_mappings,
    upsert_raes_image_mapping,
)
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from engine.models import RaesImageMapping
    from engine.services import RaesImageMappingView

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Register, list, or disable RAES image registry mappings."""

    help = "Manage the tenant RAES image registry (register / list / disable mappings)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Register the action selector and per-action arguments."""
        parser.add_argument("--action", choices=["register", "list", "disable"], required=True)
        parser.add_argument(
            "--provider", default="", help="Provider (for example 'gce'); required to register/disable."
        )
        parser.add_argument("--source-name", default="", help="Authored RAES image source name (for example 'alpine').")
        parser.add_argument(
            "--source-version",
            default="",
            help="Authored source version; blank is the any-version fallback.",
        )
        parser.add_argument("--image-ref", default="", help="Concrete provider image; required to register.")
        parser.add_argument("--machine-type", default="", help="Optional provider machine type.")
        parser.add_argument("--disk-size-gb", type=int, default=None, help="Optional boot disk size in GB.")
        parser.add_argument("--disk-type", default="", help="Optional provider disk type.")
        parser.add_argument("--notes", default="", help="Optional free-text notes.")
        # Portable RAES artifact identity + admission evidence (#1580). Supply all
        # five to register a portable mapping that satisfies an authored artifact
        # requirement; omit all five for a legacy alias-only mapping.
        parser.add_argument("--artifact-id", default="", help="Portable RAES ArtifactIdentity id this image realizes.")
        parser.add_argument("--artifact-version", default="", help="Portable ArtifactIdentity version.")
        parser.add_argument(
            "--artifact-digest", default="", help="Portable ArtifactIdentity sha256 digest ('sha256:'+64 hex)."
        )
        parser.add_argument("--media-type", default="", help="Portable ArtifactIdentity media type.")
        parser.add_argument("--integrity-ref", default="", help="Verified integrity evidence reference.")
        parser.add_argument("--provenance-ref", default="", help="Verified provenance evidence reference.")
        parser.add_argument(
            "--disabled",
            action="store_true",
            default=False,
            help="Register the mapping as disabled (enabled=False).",
        )
        parser.add_argument(
            "--enabled-only",
            action="store_true",
            default=False,
            help="List: show only enabled mappings.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Dispatch to the requested action, mapping domain errors to CommandError."""
        action = options["action"]
        if action == "register":
            self._register(options)
        elif action == "disable":
            self._disable(options)
        else:
            self._list(options)

    def _register(self, options: dict[str, Any]) -> None:
        """Create or update a mapping through the single validated write path."""
        provider = _require_option(options, "provider")
        source_name = _require_option(options, "source_name")
        image_ref = _require_option(options, "image_ref")
        try:
            mapping = upsert_raes_image_mapping(
                provider=provider,
                source_name=source_name,
                image_ref=image_ref,
                options=RaesImageMappingOptions(
                    source_version=options["source_version"],
                    machine_type=options["machine_type"],
                    disk_size_gb=options["disk_size_gb"],
                    disk_type=options["disk_type"],
                    enabled=not options["disabled"],
                    notes=options["notes"],
                    artifact_id=options["artifact_id"],
                    artifact_version=options["artifact_version"],
                    artifact_digest=options["artifact_digest"],
                    media_type=options["media_type"],
                    integrity_ref=options["integrity_ref"],
                    provenance_ref=options["provenance_ref"],
                ),
            )
        except RaesImageMappingError as exc:
            raise CommandError(str(exc)) from exc
        logger.info(
            "raes image mapping registered provider=%s source=%s enabled=%s",
            safe_log_value(mapping.provider),
            safe_log_value(mapping.source_name),
            mapping.enabled,
        )
        self.stdout.write(f"registered {_format_mapping(mapping)}")

    def _disable(self, options: dict[str, Any]) -> None:
        """Soft-disable an existing mapping by natural key (disable is not delete)."""
        provider = _require_option(options, "provider")
        source_name = _require_option(options, "source_name")
        try:
            view = disable_raes_image_mapping(
                provider=provider,
                source_name=source_name,
                source_version=options["source_version"],
            )
        except RaesImageMappingError as exc:
            raise CommandError(str(exc)) from exc
        logger.info(
            "raes image mapping disabled provider=%s source=%s",
            safe_log_value(view.provider),
            safe_log_value(view.source_name),
        )
        self.stdout.write(f"disabled {_format_mapping(view)}")

    def _list(self, options: dict[str, Any]) -> None:
        """Print a non-secret single-line summary per mapping, plus a count."""
        provider = options["provider"].strip() or None
        try:
            rows = list_raes_image_mappings(provider=provider, include_disabled=not options["enabled_only"])
        except RaesImageMappingError as exc:
            raise CommandError(str(exc)) from exc
        for row in rows:
            self.stdout.write(_format_mapping(row))
        self.stdout.write(f"{len(rows)} mapping(s)")


def _require_option(options: dict[str, Any], name: str) -> str:
    """Return a non-empty stripped option value or raise CommandError naming it."""
    value = (options.get(name) or "").strip()
    if not value:
        raise CommandError(f"--{name.replace('_', '-')} is required for this action")
    return value


def _format_mapping(mapping: RaesImageMappingView | RaesImageMapping) -> str:
    """Render one mapping as a stable single-line summary for stdout.

    Accepts either the read DTO (list/disable) or the model instance the upsert
    write path returns; both expose the same read attributes.
    """
    version = mapping.source_version or "*"
    state = "enabled" if mapping.enabled else "disabled"
    return f"{mapping.provider}:{mapping.source_name}@{version} -> {mapping.image_ref} [{state}]"
