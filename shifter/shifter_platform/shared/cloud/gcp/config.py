"""Shared client configuration for request-adjacent GCP clients.

The GCP counterpart to ``shared.cloud.aws.config``. Secret Manager reads happen
on (or one hop off) the portal request path, so a stalled backend must fail fast
rather than hang on the client's long default deadline (#929). The timeout policy
lives here so the GCP adapters stop hand-rolling per-call deadlines.
"""

from __future__ import annotations

from django.conf import settings

_DEFAULT_SECRETS_REQUEST_TIMEOUT_SECONDS = 5.0


def secrets_request_timeout() -> float:
    """Return the bounded per-request timeout (seconds) for Secret Manager calls.

    Applied as the ``timeout`` argument to ``access_secret_version`` so a stalled
    Secret Manager backend fails fast instead of hanging the calling thread.
    """
    return max(
        1.0, float(getattr(settings, "GCP_SECRETS_REQUEST_TIMEOUT_SECONDS", _DEFAULT_SECRETS_REQUEST_TIMEOUT_SECONDS))
    )
