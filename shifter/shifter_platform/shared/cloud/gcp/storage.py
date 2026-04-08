"""GCP Cloud Storage adapter (stub).

Will replace AWS S3 for object storage operations used by Mission Control
(agent uploads, script uploads, presigned URLs).
"""

from __future__ import annotations

from typing import Any

from shared.cloud.exceptions import CloudProviderNotImplementedError


class GCPObjectStorage:
    """Cloud Storage — stub, not yet implemented."""

    def upload_file(self, file_obj: Any, bucket: str, key: str, content_type: str = "") -> None:
        raise CloudProviderNotImplementedError("gcp")

    def delete_object(self, bucket: str, key: str) -> None:
        raise CloudProviderNotImplementedError("gcp")

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        raise CloudProviderNotImplementedError("gcp")

    def generate_presigned_upload_url(self, bucket: str, key: str, content_type: str, expires_in: int) -> str:
        raise CloudProviderNotImplementedError("gcp")

    def generate_presigned_download_url(self, bucket: str, key: str, expires_in: int) -> str:
        raise CloudProviderNotImplementedError("gcp")

    def tag_object(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        raise CloudProviderNotImplementedError("gcp")
