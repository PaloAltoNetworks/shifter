"""GCP Cloud SQL IAM auth adapter implementing DBAuth protocol.

Uses google-auth to generate an OAuth2 access token that Cloud SQL accepts
as a database password when IAM database authentication is enabled.
"""

from __future__ import annotations

import logging

from cloud.exceptions import CloudDBAuthError

from .base import BaseGCPAdapter

logger = logging.getLogger(__name__)


class GCPDBAuth(BaseGCPAdapter):
    """Cloud SQL IAM auth implementation of DBAuth protocol."""

    def generate_auth_token(
        self,
        hostname: str,
        port: int,
        username: str,
    ) -> str:
        logger.debug("generate_auth_token: hostname=%s port=%d username=%s", hostname, port, username)
        try:
            import google.auth  # type: ignore[import-untyped]
            import google.auth.transport.requests  # type: ignore[import-untyped]

            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            request = google.auth.transport.requests.Request()
            credentials.refresh(request)
            token: str = credentials.token
            return token
        except Exception as e:
            logger.error("generate_auth_token: failed hostname=%s error=%s", hostname, e)
            raise CloudDBAuthError(f"Failed to generate Cloud SQL IAM auth token: {e}") from e
