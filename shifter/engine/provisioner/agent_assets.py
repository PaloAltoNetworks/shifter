"""Provisioner helpers for optional per-instance agent assets."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def get_agent_presigned_url(inst_config: dict[str, Any]) -> str | None:
    """Generate a presigned download URL for an instance's configured agent."""
    agent_data = inst_config.get("agent") or {}
    s3_key = agent_data.get("s3_key")
    if not s3_key:
        return None

    bucket = os.environ.get("AGENT_STORAGE_BUCKET") or os.environ.get("AGENT_S3_BUCKET", "")
    presigned_url: str | None = None
    if bucket:
        try:
            from cloud import get_object_storage

            storage = get_object_storage()
            presigned_url = storage.generate_presigned_download_url(
                bucket=bucket,
                key=s3_key,
                expires_in=3600,
            )
        except Exception:
            logger.exception("Failed to generate presigned URL for %s", s3_key)
    else:
        logger.warning("AGENT_STORAGE_BUCKET/AGENT_S3_BUCKET not set, cannot generate presigned URL")

    return presigned_url
