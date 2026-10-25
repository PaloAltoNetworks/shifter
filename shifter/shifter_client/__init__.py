"""Supported native-Google Shifter service transport; no application internals."""

from dataclasses import dataclass
from urllib.parse import urlsplit

import google.auth
from google.auth import impersonated_credentials
from google.auth.compute_engine import credentials as compute_credentials
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2 import service_account

_CLOUD_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


@dataclass
class ServiceClient:
    """Separate automatically refreshed app and cloud transports from native ADC."""

    audience: str
    application: AuthorizedSession
    cloud: AuthorizedSession

    @classmethod
    def from_adc(
        cls, audience: str, *, target_principal: str | None = None
    ) -> "ServiceClient":
        """Use attached identity, impersonated ADC, or explicit ADC impersonation.

        Source credentials must themselves remain renewable. External federation
        uses google-auth's external-account ADC support and an explicitly named
        target service account. Service-account JSON keys are not supported.
        """
        parsed = urlsplit(audience)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Application audience must be an absolute HTTPS URL")
        source, _ = google.auth.default(scopes=_CLOUD_SCOPES)
        if isinstance(source, service_account.Credentials):
            raise ValueError("Static service-account keys are not supported")
        cloud = source
        if target_principal is not None:
            if (
                not target_principal.endswith(".gserviceaccount.com")
                or "@" not in target_principal
            ):
                raise ValueError("An explicit service-account email is required")
            cloud = impersonated_credentials.Credentials(
                source_credentials=source,
                target_principal=target_principal,
                target_scopes=_CLOUD_SCOPES,
                lifetime=3600,
            )
        if isinstance(cloud, impersonated_credentials.Credentials):
            application = impersonated_credentials.IDTokenCredentials(
                cloud,
                target_audience=audience,
                include_email=True,
            )
        elif isinstance(cloud, compute_credentials.Credentials):
            application = compute_credentials.IDTokenCredentials(
                Request(),
                target_audience=audience,
                use_metadata_identity_endpoint=True,
            )
        else:
            raise ValueError(
                "Non-attached ADC requires an explicit target service account"
            )
        # Native before_request refreshes expired proof. Do not replay arbitrary
        # mutations after a 401: retries require application idempotency semantics.
        return cls(
            audience,
            AuthorizedSession(application, max_refresh_attempts=0),
            AuthorizedSession(cloud, max_refresh_attempts=0),
        )

    def request(self, method: str, path: str, **kwargs):
        """Send one app request to the bound audience; never follow redirects."""
        parsed = urlsplit(path)
        if (
            parsed.scheme
            or parsed.netloc
            or not path.startswith("/")
            or path.startswith("//")
        ):
            raise ValueError("Application requests require a relative absolute path")
        if "allow_redirects" in kwargs or "auth" in kwargs:
            raise ValueError(
                "Application authentication and redirects are transport-owned"
            )
        kwargs.setdefault("timeout", 30)
        return self.application.request(
            method, self.audience.rstrip("/") + path, allow_redirects=False, **kwargs
        )

    def close(self) -> None:
        """Release both native HTTP connection pools."""
        self.application.close()
        self.cloud.close()
