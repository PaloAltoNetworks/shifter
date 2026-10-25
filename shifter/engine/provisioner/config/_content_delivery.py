"""Provisioner-side object-storage config for #1564 source-backed content delivery."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RaesContentDeliveryConfig:
    """Provisioner-side object-storage config for post-boot content delivery.

    ``bucket`` is the same platform assets bucket the CMS side promotes
    source-backed content payloads to (``settings.STORAGE_BUCKET_NAME`` /
    ``shared.raes.content_delivery_prep``); the byte-free delivery binding carries
    only a ``storage_key`` + ``sha256`` + ``byte_count`` (never a bucket), so the
    provisioner resolves the bucket from its own config (ADR-032-R3). There is no
    payload-size setting: delivery is bounded by each binding's exact byte count
    and the staging and destination free space (ADR-032-R9).
    """

    bucket: str


def load_raes_content_delivery_config() -> RaesContentDeliveryConfig:
    """Load the #1564 content-delivery object-storage config.

    ``RAES_CONTENT_DELIVERY_BUCKET`` is preferred; ``STORAGE_BUCKET_NAME`` (the
    same env var name the Django CMS side reads for the assets bucket) is the
    fallback so a single shared value can configure both deployables. Empty (no
    bucket configured) is a legitimate return -- most ranges carry no
    source-backed content, so the bucket is validated fail-closed only at the
    point a delivery actually needs it, not at load time.
    """
    bucket = (os.environ.get("RAES_CONTENT_DELIVERY_BUCKET") or os.environ.get("STORAGE_BUCKET_NAME", "")).strip()
    return RaesContentDeliveryConfig(bucket=bucket)
