"""Seed the RAES image registry from the tenant's configured base range images.

A headless deploy hook that converges ``engine.models.RaesImageMapping``
any-version rows for the base range images the tenant already exposes through the
``GCP_RANGE_*_IMAGE`` environment (rendered by
``scripts/gcp/render_runtime_env.py`` and passed to the provisioner via
``engine.ecs._env``). Without these rows a RAES pack that references a base image
source name (``kali`` / ``ubuntu`` / ...) is ``NOT_REALIZABLE`` and cannot launch
on a fresh tenant, even though the images are baked and configured.

Each mapping is registered with a blank ``source_version`` (the any-version
fallback) so unpinned pack sources resolve to it. Every mutation delegates to the
single validated write path (``engine.services.upsert_raes_image_mapping``); this
command owns only the source-name -> env-var table and non-secret stdout. It is
idempotent, so a redeploy converges the registry rather than duplicating rows.
"""

from __future__ import annotations

import logging
import os
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from engine.services import RaesImageMappingError, RaesImageMappingOptions, upsert_raes_image_mapping

logger = logging.getLogger(__name__)

# RAES source name -> (image ref, machine type, disk size, disk type) env vars.
# The ``ubuntu`` base is the platform's generic Linux image (GCP_RANGE_LINUX_*).
_IMAGE_SOURCES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "kali",
        "GCP_RANGE_KALI_IMAGE",
        "GCP_RANGE_KALI_MACHINE_TYPE",
        "GCP_RANGE_KALI_DISK_SIZE_GB",
        "GCP_RANGE_KALI_DISK_TYPE",
    ),
    (
        "ubuntu",
        "GCP_RANGE_LINUX_IMAGE",
        "GCP_RANGE_LINUX_MACHINE_TYPE",
        "GCP_RANGE_LINUX_DISK_SIZE_GB",
        "GCP_RANGE_LINUX_DISK_TYPE",
    ),
    (
        "windows",
        "GCP_RANGE_WINDOWS_IMAGE",
        "GCP_RANGE_WINDOWS_MACHINE_TYPE",
        "GCP_RANGE_WINDOWS_DISK_SIZE_GB",
        "GCP_RANGE_WINDOWS_DISK_TYPE",
    ),
    ("dc", "GCP_RANGE_DC_IMAGE", "GCP_RANGE_DC_MACHINE_TYPE", "GCP_RANGE_DC_DISK_SIZE_GB", "GCP_RANGE_DC_DISK_TYPE"),
)


def _parse_disk_size(raw: str, source_name: str) -> int | None:
    """Parse a disk-size env value into a positive int, or None when unset.

    A blank/absent value returns None so the provisioner applies its own default;
    a non-integer or non-positive value raises ``CommandError`` so a misconfigured
    ``GCP_RANGE_*_DISK_SIZE_GB`` fails the deploy hook loudly rather than silently.
    """
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CommandError(f"disk size for '{source_name}' must be an integer, got {value!r}") from exc
    if parsed <= 0:
        raise CommandError(f"disk size for '{source_name}' must be a positive integer, got {parsed}")
    return parsed


class Command(BaseCommand):
    """Converge the RAES image registry from the base range image environment."""

    help = "Seed engine.models.RaesImageMapping any-version rows from the GCP_RANGE_*_IMAGE environment."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--provider",
            default=os.environ.get("GCP_RANGE_BACKEND", "gce") or "gce",
            help="Provider for the mappings (default: GCP_RANGE_BACKEND or 'gce').",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        provider = str(options["provider"]).strip() or "gce"
        seeded = 0
        for source_name, image_env, machine_env, disk_size_env, disk_type_env in _IMAGE_SOURCES:
            image_ref = os.environ.get(image_env, "").strip()
            if not image_ref:
                self.stdout.write(f"skip {source_name}: {image_env} is unset")
                continue
            options_obj = RaesImageMappingOptions(
                source_version="",
                machine_type=os.environ.get(machine_env, "").strip(),
                disk_size_gb=_parse_disk_size(os.environ.get(disk_size_env, ""), source_name),
                disk_type=os.environ.get(disk_type_env, "").strip(),
                notes=f"seeded from {image_env}",
            )
            try:
                upsert_raes_image_mapping(
                    provider=provider, source_name=source_name, image_ref=image_ref, options=options_obj
                )
            except RaesImageMappingError as exc:
                raise CommandError(f"failed to seed '{source_name}' mapping: {exc}") from exc
            seeded += 1
            self.stdout.write(f"seeded {provider}/{source_name} (any-version) -> {image_ref}")
        self.stdout.write(self.style.SUCCESS(f"Seeded {seeded} RAES image mapping(s)."))
