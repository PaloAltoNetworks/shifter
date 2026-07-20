"""Tenant management command for the ACES image registry (#1566, ADR-032-R2).

A headless surface for operators/automation to register, list, and disable
``engine.models.AcesImageMapping`` rows so the realizability registry can be
converged declaratively (for example in a deploy hook) without the SPA. Every
mutation delegates to the single validated write path in ``engine.services``
(``upsert_aces_image_mapping`` / ``disable_aces_image_mapping``); this command
owns only argument shape, the native-provisioning gate, and non-secret stdout
summaries. Bounded failures raise ``CommandError``.

Examples::

    manage.py aces_image_registry --action list
    manage.py aces_image_registry --action register --provider gce \\
        --source-name alpine --source-version 3.19 \\
        --image-ref projects/x/global/images/alpine-3-19 --disk-size-gb 20
    manage.py aces_image_registry --action disable --provider gce \\
        --source-name alpine --source-version 3.19

Gated by ``SHIFTER_ACES_NATIVE_PROVISIONING``: the command refuses when the flag
is off, matching the rest of the native path.
"""

from __future__ import annotations

import logging
from argparse import ArgumentParser
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from engine.services import (
    AcesImageMappingError,
    AcesImageMappingOptions,
    disable_aces_image_mapping,
    list_aces_image_mappings,
    upsert_aces_image_mapping,
)
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from engine.models import AcesImageMapping
    from engine.services import AcesImageMappingView

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Register, list, or disable ACES image registry mappings."""

    help = "Manage the tenant ACES image registry (register / list / disable mappings)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Register the action selector and per-action arguments."""
        parser.add_argument("--action", choices=["register", "list", "disable"], required=True)
        parser.add_argument(
            "--provider", default="", help="Provider (for example 'gce'); required to register/disable."
        )
        parser.add_argument("--source-name", default="", help="Authored ACES image source name (for example 'alpine').")
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
        if not getattr(settings, "ACES_NATIVE_PROVISIONING_ENABLED", False):
            raise CommandError("SHIFTER_ACES_NATIVE_PROVISIONING must be enabled to manage the ACES image registry")
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
            mapping = upsert_aces_image_mapping(
                provider=provider,
                source_name=source_name,
                image_ref=image_ref,
                options=AcesImageMappingOptions(
                    source_version=options["source_version"],
                    machine_type=options["machine_type"],
                    disk_size_gb=options["disk_size_gb"],
                    disk_type=options["disk_type"],
                    enabled=not options["disabled"],
                    notes=options["notes"],
                ),
            )
        except AcesImageMappingError as exc:
            raise CommandError(str(exc)) from exc
        logger.info(
            "aces image mapping registered provider=%s source=%s enabled=%s",
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
            view = disable_aces_image_mapping(
                provider=provider,
                source_name=source_name,
                source_version=options["source_version"],
            )
        except AcesImageMappingError as exc:
            raise CommandError(str(exc)) from exc
        logger.info(
            "aces image mapping disabled provider=%s source=%s",
            safe_log_value(view.provider),
            safe_log_value(view.source_name),
        )
        self.stdout.write(f"disabled {_format_mapping(view)}")

    def _list(self, options: dict[str, Any]) -> None:
        """Print a non-secret single-line summary per mapping, plus a count."""
        provider = options["provider"].strip() or None
        try:
            rows = list_aces_image_mappings(provider=provider, include_disabled=not options["enabled_only"])
        except AcesImageMappingError as exc:
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


def _format_mapping(mapping: AcesImageMappingView | AcesImageMapping) -> str:
    """Render one mapping as a stable single-line summary for stdout.

    Accepts either the read DTO (list/disable) or the model instance the upsert
    write path returns; both expose the same read attributes.
    """
    version = mapping.source_version or "*"
    state = "enabled" if mapping.enabled else "disabled"
    return f"{mapping.provider}:{mapping.source_name}@{version} -> {mapping.image_ref} [{state}]"
