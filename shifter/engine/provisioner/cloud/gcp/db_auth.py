"""Google Cloud SQL IAM adapter implementing DBAuth protocol."""

from __future__ import annotations

import logging

from cloud.exceptions import CloudDBAuthError
from cloud.gcp.base import import_google_module

logger = logging.getLogger(__name__)


class GCPDBAuth:
    """Cloud SQL IAM database auth implementation.

    For PostgreSQL IAM auth on Cloud SQL, the access token is presented as the
    password when opening the database connection.
    """

    def generate_auth_token(
        self,
        hostname: str,
        port: int,
        username: str,
    ) -> str:
        del hostname, port, username
        logger.debug("generate_auth_token: generating Cloud SQL IAM token")
        try:
            google_auth = import_google_module("google.auth")
            google_auth_transport = import_google_module("google.auth.transport.requests")
            credentials, _project = google_auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            request = google_auth_transport.Request()
            credentials.refresh(request)
            token = getattr(credentials, "token", None)
            if not token:
                raise CloudDBAuthError("Google credentials did not return an access token")
            return str(token)
        except ImportError as e:
            raise CloudDBAuthError("GCP DB auth support requires google-auth") from e
        except Exception as e:
            logger.error("generate_auth_token: failed error=%s", e)
            raise CloudDBAuthError(f"Failed to generate Cloud SQL IAM auth token: {e}") from e
