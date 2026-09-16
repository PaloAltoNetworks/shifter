"""Validated public site origin for credential-free outbound links (#1943).

The single seam that validates ``settings.SITE_URL`` into a safe, credential-free
public origin for outbound email links (workspace invitations, administrator
password reset). Kept in ``shared`` so no domain copies the validator or imports
another domain's private helper.
"""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit

from django.conf import settings


class SiteUrlUnavailable(RuntimeError):
    """Raised when ``SITE_URL`` is missing or not a safe credential-free origin."""


def site_origin_is_safe(parsed: SplitResult) -> bool:
    """Return whether a parsed URL is an allowed credential-free origin.

    Production requires an ``https`` origin with no path/query/fragment/userinfo;
    ``http://localhost`` / ``http://127.0.0.1`` are allowed only under ``DEBUG``.
    """
    development_http = (
        settings.DEBUG
        and parsed.scheme == "http"
        and parsed.hostname
        in {
            "localhost",
            "127.0.0.1",
        }
    )
    allowed_scheme = parsed.scheme == "https" or development_http
    no_credentials = parsed.username is None and parsed.password is None
    origin_only = parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
    return bool(allowed_scheme and parsed.netloc and no_credentials and origin_only)


def validated_site_url() -> str:
    """Return the validated public origin (scheme + netloc, no trailing slash).

    Raises:
        SiteUrlUnavailable: If ``SITE_URL`` is unset or not a safe origin.
    """
    site_url = str(getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")
    if not site_origin_is_safe(urlsplit(site_url)):
        raise SiteUrlUnavailable("SITE_URL is not a safe public origin")
    return site_url
