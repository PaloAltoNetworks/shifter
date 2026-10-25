"""Compute Engine metadata identity and Secret Manager access, standard library only.

The VM's attached service account is the server's only credential: an access
token reads the server material, and a Google-signed identity token for the
portal audience authenticates every control call.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request

from . import transport

_METADATA = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
_HEADERS = {"Metadata-Flavor": "Google"}
_TIMEOUT = 5


def _metadata(path: str) -> str:
    """Return one metadata-server value for the attached service account."""
    # Fixed metadata URL, opened only through the http/https-only transport.
    request = urllib.request.Request(f"{_METADATA}/{path}", headers=_HEADERS)  # noqa: S310
    with transport.OPENER.open(request, timeout=_TIMEOUT) as response:
        return str(response.read().decode("utf-8"))


def identity_token(audience: str) -> str:
    """Return a Google-signed identity token for ``audience`` (includes the email claim)."""
    query = urllib.parse.urlencode({"audience": audience, "format": "full"})
    return _metadata(f"identity?{query}").strip()


def access_token() -> str:
    """Return a short-lived OAuth access token for the attached service account."""
    payload = json.loads(_metadata("token"))
    return str(payload["access_token"])


def read_secret(name: str) -> str:
    """Return the latest version of a Secret Manager secret."""
    url = f"https://secretmanager.googleapis.com/v1/{name}/versions/latest:access"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token()}"})
    with transport.OPENER.open(request, timeout=10) as response:
        payload = json.loads(response.read())
    return base64.b64decode(payload["payload"]["data"]).decode("utf-8")
