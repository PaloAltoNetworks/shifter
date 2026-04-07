"""GCP Cloud Storage object storage adapter (stub).

Will replace AWS S3 for object storage operations.
"""

from __future__ import annotations

from cloud.exceptions import CloudProviderNotImplementedError

from .base import BaseGCPAdapter


class GCPObjectStorage(BaseGCPAdapter):
    """Cloud Storage — stub, not yet implemented."""

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        raise CloudProviderNotImplementedError("gcp", "ObjectStorage")

    def object_exists(self, bucket: str, key: str) -> bool:
        raise CloudProviderNotImplementedError("gcp", "ObjectStorage")

    def delete_object(self, bucket: str, key: str) -> None:
        raise CloudProviderNotImplementedError("gcp", "ObjectStorage")
