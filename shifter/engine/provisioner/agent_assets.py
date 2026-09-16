"""Provisioner helpers for signed-URL delivery of per-range host artifacts.

Both helpers mint a short-lived, provisioner-signed GET URL so a
participant-controllable range guest can fetch a specific platform object without
holding any Cloud Storage identity of its own:

* :func:`get_agent_presigned_url` -- the optional per-instance XDR agent installer.
* :func:`get_polaris_tests_presigned_url` -- the POLARIS smoketest tarball, which
  used to be fetched with the range-host SA's ADC and project-level
  ``storage.objectViewer`` (a cross-tenant read from a participant-reachable
  guest, #1644). The grant is gone; the object is now delivered as an exact,
  generation-bound, short-expiry signed URL minted here.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Default object path for the POLARIS smoketest tarball inside the assets bucket.
POLARIS_TESTS_DEFAULT_KEY = "polaris/tests/polaris-tests.tar.gz"

# Signed URLs for range-guest artifact delivery are consumed immediately during
# bootstrap, so they carry a short expiry rather than the hour used for the
# operator-facing XDR installer.
_POLARIS_TESTS_URL_EXPIRY_SECONDS = 900


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


def _resolve_polaris_tests_object() -> tuple[str, str]:
    """Resolve the (bucket, key) of the POLARIS smoketest tarball.

    Reuses the existing non-secret object-selection contract
    (``POLARIS_TESTS_BUCKET``/``POLARIS_TESTS_KEY``, falling back to the shared
    assets bucket wired as ``AGENT_STORAGE_BUCKET``/``AGENT_S3_BUCKET``).

    Raises:
        ValueError: If no bucket is configured (fail closed -- never fall back to
            guest ADC or an unsigned URL).
    """
    bucket = (
        os.environ.get("POLARIS_TESTS_BUCKET")
        or os.environ.get("AGENT_STORAGE_BUCKET")
        or os.environ.get("AGENT_S3_BUCKET")
        or ""
    )
    if not bucket:
        raise ValueError(
            "POLARIS_TESTS_BUCKET (or AGENT_STORAGE_BUCKET / AGENT_S3_BUCKET) must "
            "be set so the range host can fetch the smoketest tarball via a signed URL"
        )
    key = os.environ.get("POLARIS_TESTS_KEY", POLARIS_TESTS_DEFAULT_KEY)
    return bucket, key


def get_polaris_tests_presigned_url() -> str:
    """Mint a short-lived, generation-bound signed URL for the POLARIS tarball.

    The range host is participant-controllable, so it holds no Cloud Storage
    identity (#1644). The provisioner -- which does have scoped assets-bucket read
    and a self-``signBlob`` grant -- signs an exact, immutable-version-bound GET
    URL that the guest simply ``curl``s. The URL is a private bootstrap input; it
    is never logged, persisted, or placed on process argv.

    Raises:
        ValueError: No bucket is configured.
        CloudStorageError: The object is missing or the URL cannot be signed. The
            caller fails the setup closed rather than falling back to guest ADC or
            an unsigned URL.
    """
    bucket, key = _resolve_polaris_tests_object()
    from cloud import get_object_storage

    storage = get_object_storage()
    # Bind the URL to the current immutable object version so an object swapped
    # between minting and download fails closed instead of being served. The
    # version selector is opaque (GCS generation / S3 VersionId), carried as a
    # string per the ObjectStorage contract.
    identity = storage.head_object(bucket, key)
    object_version = identity.get("generation")
    return storage.generate_presigned_download_url(
        bucket=bucket,
        key=key,
        expires_in=_POLARIS_TESTS_URL_EXPIRY_SECONDS,
        object_version=None if object_version is None else str(object_version),
    )
