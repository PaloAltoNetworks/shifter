"""GCP Secret Manager config store adapter (stub).

Will replace AWS SSM Parameter Store for configuration retrieval.
"""

from __future__ import annotations

from cloud.exceptions import CloudProviderNotImplementedError

from .base import BaseGCPAdapter


class GCPConfigStore(BaseGCPAdapter):
    """Secret Manager config store — stub, not yet implemented."""

    def get_parameter(self, name: str) -> str:
        raise CloudProviderNotImplementedError("gcp", "ConfigStore")
