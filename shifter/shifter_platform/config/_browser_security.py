"""Browser document security policy (ADR-036).

Single code-owned artifact for the staged, deny-by-default browser security
policy shared by the legacy Django templates and the platform SPA. It defines
the reviewed CSP candidate, the validated ``report-only | enforce`` rollout
seam, and the global Referrer-Policy / Permissions-Policy / Reporting-Endpoints
header values.

Star-imported by :mod:`config.settings`. The candidate is deployed in
``Content-Security-Policy-Report-Only`` first (this stage); enforcement promotes
the *same* candidate to ``Content-Security-Policy`` by flipping
``BROWSER_CSP_MODE`` after a policy review. Only the bounded mode is
environment-bound; the policy and its source lists stay reviewed code-owned
constants. See ``docs/architecture/browser-security-policy-preflight-1520.md``.

Enforcement readiness
---------------------
The candidate is deployed in report-only mode by this change. The public package
CDNs (jsDelivr/unpkg) raised by the pre-push review are now self-hosted, so the
only remaining external ``script-src`` origin is Google-owned ``gstatic`` (the
Firebase SDK, not a public-publish registry). Before the candidate is promoted to
enforcement (``BROWSER_CSP_MODE=enforce``) the following must still be closed
(tracked as the enforcement follow-up, not report-only-baseline scope):

1. Remove or nonce/hash the inventoried inline scripts, inline event handlers,
   and inline styles that report-only surfaces (including Mermaid's runtime
   ``<style>`` injection under ``style-src``).
2. Verify same-origin ``wss`` is authorized by ``connect-src 'self'`` across the
   platform's supported browsers (CSP Level 3 says it is; older engines differ)
   and pin it with a browser-response test before enforcing.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

from config._cloud import AWS_S3_BUCKET_NAME, AWS_S3_REGION, CLOUD_PROVIDER

__all__ = [
    "BROWSER_CSP_MODE",
    "CSP_REPORT_PATH",
    "PERMISSIONS_POLICY",
    "REPORTING_ENDPOINTS_HEADER",
    "SECURE_CSP",
    "SECURE_CSP_REPORT_ONLY",
    "SECURE_REFERRER_POLICY",
    "build_browser_csp",
    "csp_settings_for_mode",
    "resolve_csp_mode",
]

# ---------------------------------------------------------------------------
# Rollout seam (ADR-036-R1). Only the mode is environment-bound.
# ---------------------------------------------------------------------------
_MODE_REPORT_ONLY = "report-only"
_MODE_ENFORCE = "enforce"
_VALID_MODES = (_MODE_REPORT_ONLY, _MODE_ENFORCE)

# Same-origin collector (ADR-036-R3). Report-only and enforce both report here.
CSP_REPORT_PATH = "/security/csp-report/"
_REPORTING_GROUP = "csp"

# Google Identity Platform / Firebase browser endpoints (fixed, provider-owned).
# The Firebase JS SDK is served from gstatic; the client speaks to the Identity
# Platform REST APIs below. The project-specific ``*.firebaseapp.com`` auth
# domain is deliberately not derived here: it is only used by OAuth popup/redirect
# flows this app does not use, and report-only surfaces any missing origin before
# enforcement rather than the settings module re-reading identity env vars.
_FIREBASE_SDK_ORIGIN = "https://www.gstatic.com"
_AUTH_API_ORIGINS = (
    "https://identitytoolkit.googleapis.com",
    "https://securetoken.googleapis.com",
    "https://www.googleapis.com",
)
_GCS_ORIGIN = "https://storage.googleapis.com"


def resolve_csp_mode(raw: str) -> str:
    """Validate and normalize the rollout mode; fail loud on an unknown value."""
    mode = raw.strip().lower()
    if mode not in _VALID_MODES:
        raise ImproperlyConfigured(f"BROWSER_CSP_MODE must be one of {_VALID_MODES!r}; got {raw!r}.")
    return mode


def _storage_connect_origins() -> list[str]:
    """Exact signed-upload origins for the resolved cloud provider."""
    if CLOUD_PROVIDER == "gcp":
        return [_GCS_ORIGIN]
    if CLOUD_PROVIDER == "aws":
        # Signed uploads use virtual-hosted-style URLs; include the bucket host
        # when known plus the regional S3 host.
        region = AWS_S3_REGION or "us-east-2"
        origins: list[str] = []
        if AWS_S3_BUCKET_NAME:
            origins.append(f"https://{AWS_S3_BUCKET_NAME}.s3.{region}.amazonaws.com")
        origins.append(f"https://s3.{region}.amazonaws.com")
        return origins
    # Unsupported means a startup/configuration error, not AWS-compatible
    # behavior (docs/architecture/root-configured-backend-bundles.md, "Gotchas
    # and anti-patterns").
    raise ImproperlyConfigured(f"Unsupported CLOUD_PROVIDER for browser storage CSP origins: {CLOUD_PROVIDER!r}")


def build_browser_csp() -> dict[str, list[str]]:
    """Return the reviewed deny-by-default CSP candidate (ADR-036-R2).

    No ``unsafe-inline``/``unsafe-eval``/``unsafe-hashes``, wildcards, or broad
    schemes. Inline handlers and styles are denied outright
    (``script-src-attr``/``style-src-attr`` ``'none'``); executable inline
    ``<script>`` elements are surfaced as report-only violations rather than
    silenced. External origins are exact and justified by the browser dependency
    inventory.
    """
    return {
        "default-src": [CSP.NONE],
        "base-uri": [CSP.NONE],
        "object-src": [CSP.NONE],
        "frame-src": [CSP.NONE],
        "media-src": [CSP.NONE],
        "worker-src": [CSP.NONE],
        "frame-ancestors": [CSP.NONE],
        "form-action": [CSP.SELF],
        "font-src": [CSP.SELF],
        "img-src": [CSP.SELF, "data:"],
        # Terminal (xterm/split), scoreboard (Chart.js), and docs (Mermaid) assets
        # are vendored + served same-origin (ADR-036), so no public package CDN is
        # a script authority. ``gstatic`` is the Google-owned Firebase SDK origin.
        "script-src": [CSP.SELF, _FIREBASE_SDK_ORIGIN],
        "script-src-attr": [CSP.NONE],
        "style-src": [CSP.SELF],
        "style-src-attr": [CSP.NONE],
        # ``'self'`` authorizes same-origin ``ws``/``wss`` per CSP Level 3, which
        # covers the portal's terminal/channels WebSockets. Cross-browser ``wss``
        # matching under ``'self'`` is an enforcement-readiness verification item
        # (see "Enforcement readiness" above).
        "connect-src": [CSP.SELF, *_AUTH_API_ORIGINS, *_storage_connect_origins()],
        "report-uri": [CSP_REPORT_PATH],
        "report-to": [_REPORTING_GROUP],
    }


def csp_settings_for_mode(
    mode: str, candidate: dict[str, list[str]]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Map a validated mode to ``(SECURE_CSP, SECURE_CSP_REPORT_ONLY)``.

    Enforcement promotes the *same* candidate; it is never a separately copied
    policy. Reporting stays enabled in both modes.
    """
    if mode == _MODE_ENFORCE:
        return candidate, {}
    return {}, candidate


# ---------------------------------------------------------------------------
# Global header values.
# ---------------------------------------------------------------------------
# Referrer-Policy (ADR-036-R4). Django's framework default is same-origin; make
# it the explicit repository contract. Stricter per-response overrides (the CTF
# invite ``no-referrer``) are preserved by their own views.
SECURE_REFERRER_POLICY = "same-origin"

# Permissions-Policy capability denylist (ADR-036-R4). Clipboard is deliberately
# NOT disabled: terminal copy/paste and participant walkthrough copying use
# ``navigator.clipboard``.
_PERMISSIONS_POLICY_FEATURES = (
    "accelerometer",
    "autoplay",
    "camera",
    "display-capture",
    "encrypted-media",
    "fullscreen",
    "geolocation",
    "gyroscope",
    "magnetometer",
    "microphone",
    "payment",
    "picture-in-picture",
    "publickey-credentials-create",
    "publickey-credentials-get",
    "screen-wake-lock",
    "usb",
    "web-share",
    "xr-spatial-tracking",
)
PERMISSIONS_POLICY = ", ".join(f"{feature}=()" for feature in _PERMISSIONS_POLICY_FEATURES)

# W3C Reporting API named endpoint group -> same-origin collector.
REPORTING_ENDPOINTS_HEADER = f'{_REPORTING_GROUP}="{CSP_REPORT_PATH}"'

# ---------------------------------------------------------------------------
# Resolved settings (read by Django's native CSP middleware).
# ---------------------------------------------------------------------------
BROWSER_CSP_MODE = resolve_csp_mode(os.environ.get("BROWSER_CSP_MODE", "report-only"))
SECURE_CSP, SECURE_CSP_REPORT_ONLY = csp_settings_for_mode(BROWSER_CSP_MODE, build_browser_csp())
