"""GCP Cloud SQL IAM auth adapter (stub).

Will replace AWS RDS IAM authentication for database connections.
"""

from __future__ import annotations

from cloud.exceptions import CloudProviderNotImplementedError

from .base import BaseGCPAdapter


class GCPDBAuth(BaseGCPAdapter):
    """Cloud SQL IAM auth — stub, not yet implemented."""

    def generate_auth_token(
        self,
        hostname: str,
        port: int,
        username: str,
    ) -> str:
        raise CloudProviderNotImplementedError("gcp", "DBAuth")
