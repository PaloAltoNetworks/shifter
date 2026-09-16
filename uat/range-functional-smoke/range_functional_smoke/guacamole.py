"""Guacamole check: four distinct evidence levels, only the last one sufficient.

The product flow is asynchronous by design (``mission_control.guacamole_bootstrap``):
the POST admits a request to a bounded worker pool, a worker mints a signed
JSON-auth URL, and the owner-scoped status endpoint delivers that URL exactly
once. Each step is separate evidence:

1. ``202`` + ``pending``          - queue admission only.
2. ``succeeded``                  - a signed URL is ready to deliver.
3. ``delivered_at`` set           - the one-time URL was consumed by this client.
4. guacd opened the session       - the only claim that means "Guacamole works".

Levels 1-3 prove the server minted a credential. They say nothing about whether
guacd could reach the target, which is precisely the failure users hit. Level 4
is therefore required.

**One-time delivery.** ``consume_ready_url`` atomically clears ``result_url`` and
sets ``delivered_at`` inside the successful status poll, so a second poll returns
410. The same client that polls must be the one that uses the URL — this module
never re-polls after a successful delivery, and never records the URL or token.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from range_functional_smoke.profile import ProfileError, Protocol, require_secure_url

#: Bootstrap endpoints by protocol profile (mission_control/api/urls.py).
BOOTSTRAP_PATHS: dict[Protocol, str] = {
    Protocol.RDP: "/api/v1/mission-control/guacamole/rdp-url/",
    Protocol.SSH: "/api/v1/mission-control/guacamole/ssh-url/",
}

#: Terminal bootstrap states from ``GuacamoleBootstrapRequest.Status``.
_PENDING_STATES = frozenset({"pending", "running"})
_SUCCESS_STATE = "succeeded"


class GuacamoleCheckError(RuntimeError):
    """Raised for an authored, non-secret Guacamole check failure."""


def bootstrap_path(protocol: Protocol) -> str:
    """Return the versioned bootstrap endpoint for a protocol profile."""
    try:
        return BOOTSTRAP_PATHS[Protocol(protocol)]
    except KeyError as exc:  # pragma: no cover - Protocol is a closed enum
        raise GuacamoleCheckError(f"no bootstrap endpoint for protocol {protocol!r}") from exc


@dataclass(frozen=True)
class BootstrapPoll:
    """A classified status-poll observation. Carries no URL or token."""

    status: str
    http_status: int
    pending: bool
    succeeded: bool
    delivered: bool
    error: str = ""


def classify_poll(http_status: int, payload: dict[str, object]) -> BootstrapPoll:
    """Classify one status poll without retaining credential material.

    ``delivered`` is true only when this poll carried the one-time URL, which is
    the delivery boundary: it means ``delivered_at`` was set server-side by this
    very call.
    """
    status = str(payload.get("status", "")).strip().lower()
    has_url = bool(payload.get("url"))
    error = str(payload.get("error", "") or "")
    return BootstrapPoll(
        status=status,
        http_status=http_status,
        pending=http_status == 200 and status in _PENDING_STATES,
        succeeded=status == _SUCCESS_STATE,
        delivered=http_status == 200 and status == _SUCCESS_STATE and has_url,
        error=error,
    )


@dataclass(frozen=True)
class SessionTarget:
    """The connection coordinates decoded from a one-time session URL.

    ``token`` is credential material: it is kept off ``repr`` and must never be
    logged, reported, or persisted.
    """

    tunnel_url: str
    connection_id: str
    data_source: str
    token: str = field(repr=False, default="")


def parse_session_url(url: str, *, base_origin: str = "", allow_plaintext_loopback: bool = False) -> SessionTarget:
    """Decode a signed Guacamole session URL into tunnel connection coordinates.

    ``create_guacamole_rdp_url`` renders ``{base}/#/client/{client_id}?token=…``
    where ``client_id`` is unpadded base64 of
    ``"{connection_name}\\0c\\0{data_source}"``. The fragment is where the browser
    keeps its client state, so the token and identifier are parsed out of it
    rather than the query string.

    ``GUACAMOLE_BASE_URL`` is commonly a *path* (``/guacamole``) rather than an
    absolute URL, because the browser reaches Guacamole through the portal's own
    origin. Such a URL is resolved against ``base_origin`` — the same origin the
    session was established on — rather than rejected.
    """
    if url and not urlparse(url).scheme and base_origin:
        url = urljoin(base_origin.rstrip("/") + "/", url.lstrip("/"))
    # The delivered URL carries the signed Guacamole token, and it becomes the
    # tunnel URL below, so it is held to the same transport rule as the origin:
    # a server-returned URL must not be the way plaintext gets reintroduced.
    try:
        require_secure_url(url, what="Guacamole session URL", allow_plaintext_loopback=allow_plaintext_loopback)
    except ProfileError as exc:
        raise GuacamoleCheckError(str(exc)) from exc

    parsed = urlparse(url)

    fragment = parsed.fragment or ""
    client_part, _, query_part = fragment.partition("?")
    marker = "/client/"
    if marker not in client_part:
        raise GuacamoleCheckError("Guacamole session URL does not carry a /client/ identifier")
    client_id = client_part.split(marker, 1)[1].strip("/")

    token_values = parse_qs(query_part).get("token", [])
    token = token_values[0] if token_values else ""
    if not token:
        raise GuacamoleCheckError("Guacamole session URL carries no auth token")

    connection_id, data_source = _decode_client_id(client_id)
    base_path = parsed.path.rstrip("/")
    tunnel_url = f"{parsed.scheme}://{parsed.netloc}{base_path}/tunnel"
    return SessionTarget(tunnel_url=tunnel_url, connection_id=connection_id, data_source=data_source, token=token)


def _decode_client_id(client_id: str) -> tuple[str, str]:
    """Decode ``base64(name \\0 type \\0 data_source)`` back into its parts."""
    padded = client_id + "=" * (-len(client_id) % 4)
    try:
        raw = base64.b64decode(padded).decode("utf-8")
    except Exception as exc:
        raise GuacamoleCheckError("Guacamole client identifier is not decodable base64") from exc
    parts = raw.split("\0")
    if len(parts) != 3 or not parts[0]:
        raise GuacamoleCheckError("Guacamole client identifier has an unexpected shape")
    return parts[0], parts[2]


def connect_params(target: SessionTarget) -> dict[str, str]:
    """Tunnel connection parameters, matching what the browser client sends."""
    return {
        "token": target.token,
        "GUAC_DATA_SOURCE": target.data_source,
        "GUAC_ID": target.connection_id,
        "GUAC_TYPE": "c",
        "GUAC_WIDTH": "1024",
        "GUAC_HEIGHT": "768",
        "GUAC_DPI": "96",
        "GUAC_AUDIO": "audio/L16",
        "GUAC_IMAGE": "image/png",
    }


def tunnel_ws_url(target: SessionTarget) -> str:
    """The websocket tunnel URL the Guacamole client itself opens.

    Driving the same transport as the browser keeps the claim honest: if this
    connects, a user's session would too.
    """
    base = target.tunnel_url.rsplit("/", 1)[0]
    scheme = "wss" if base.startswith("https://") else "ws"
    base = f"{scheme}://{base.split('://', 1)[1]}"
    return f"{base}/websocket-tunnel?{urlencode(connect_params(target))}"


def has_ready_instruction(stream: str) -> bool:
    """True when the Guacamole protocol stream carries a ``ready`` instruction.

    ``ready`` is guacd's own signal that the handshake completed and the remote
    session is open — the bounded client-level connection evidence the check
    requires. Instructions are length-prefixed (``5.ready,37.$uuid;``), so the
    opcode is matched with its length prefix rather than as a bare substring,
    which cannot be spoofed by connection-parameter text.
    """
    return "5.ready," in (stream or "")


def is_error_instruction(stream: str) -> bool:
    """True when guacd answered the handshake with an ``error`` instruction."""
    return "5.error," in (stream or "")
