"""Provisioner-side object-storage config for #1564 source-backed content delivery."""

from __future__ import annotations

import os
from dataclasses import dataclass

from ._env import _get_int_env

#: Default cap on a delivered content payload (256 MiB), mirroring the CMS-side
#: ``SHIFTER_RAES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES`` default in
#: shifter_platform/config/_raes_settings.py -- the provisioner enforces its own
#: independent bound on download, not merely trusting the CMS-side cap.
_RAES_CONTENT_DELIVERY_DEFAULT_MAX_BYTES = 268435456


@dataclass(frozen=True)
class RaesContentDeliveryConfig:
    """Provisioner-side object-storage config for post-boot content delivery.

    ``bucket`` is the same platform assets bucket the CMS side promotes
    source-backed content payloads to (``settings.STORAGE_BUCKET_NAME`` /
    ``shared.raes.content_delivery_prep``); the byte-free delivery binding carries
    only a ``storage_key`` + ``sha256`` + ``byte_count`` (never a bucket), so the
    provisioner resolves the bucket from its own config (ADR-032-R3).
    ``max_bytes`` bounds ``ObjectStorage.download_object`` -- defense in depth
    against a corrupted/oversized ``byte_count``.
    """

    bucket: str
    max_bytes: int = _RAES_CONTENT_DELIVERY_DEFAULT_MAX_BYTES


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
    max_bytes = _get_int_env("RAES_CONTENT_DELIVERY_MAX_BYTES", _RAES_CONTENT_DELIVERY_DEFAULT_MAX_BYTES)
    return RaesContentDeliveryConfig(bucket=bucket, max_bytes=max_bytes)
