"""The validated, non-secret run profile — the extensibility seam.

Adding another environment, example range, logical target, or Guacamole protocol
is a profile change. It must not require a second harness, a second lifecycle
implementation, or a provider-specific host schema.

Two invariants this module enforces, both deliberate:

* **No connection material.** The profile carries a *logical* selector (role and
  channel) only. A host, IP, port, username, key, or password may never be
  supplied by the runner — the portal resolves the realized binding from the
  range's authored ``participant_access``, and that resolution is part of what is
  under test. Accepting a host here would let the smoke pass while the product's
  own resolution is broken.
* **Positive environment selection.** A production-looking target is refused
  unless the operator explicitly acknowledges it, so a run can never be pointed
  at production or a live event tenant by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

#: Keys that would smuggle realized connection details past the portal's own
#: resolution. Rejected loudly rather than ignored.
FORBIDDEN_PROFILE_KEYS = frozenset(
    {
        "host",
        "hostname",
        "ip",
        "ip_address",
        "private_ip",
        "port",
        "username",
        "ssh_username",
        "password",
        "rdp_password",
        "private_key",
        "ssh_key",
        "secret",
        "token",
    }
)

_PRODUCTION_MARKERS = ("prod", "production")

#: Hosts where plaintext cannot leave the machine, so there is no observer to
#: protect against. Everything else must be encrypted.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class ProfileError(ValueError):
    """Raised for an invalid or unsafe run profile."""


def is_loopback(host: str | None) -> bool:
    """True when a host cannot be observed off-box."""
    return (host or "").strip().lower().strip("[]") in LOOPBACK_HOSTS


def require_secure_url(url: str, *, what: str, allow_plaintext_loopback: bool = False) -> str:
    """Reject a plaintext URL that would carry credentials over the network.

    This harness handles replayable secrets end to end: an Identity Platform ID
    token, a live ``sessionid`` cookie sent on both HTTP requests and the
    terminal websocket handshake, and a server-minted Guacamole token carried in
    a tunnel query string. Over ``http``/``ws`` a passive observer between the
    operator and the target can lift any of them and impersonate the participant.

    So encrypted transport is required for **every** secret-bearing URL — the
    configured origin and every server-returned URL alike — and the single
    exception is a loopback host behind an explicit opt-in, where there is no
    network path to observe. Enforced in one place so a new URL surface cannot
    quietly reintroduce plaintext.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme in ("https", "wss"):
        return url
    if scheme not in ("http", "ws"):
        raise ProfileError(f"{what} must use http(s); got {scheme or 'no'} scheme")
    if allow_plaintext_loopback and is_loopback(parsed.hostname):
        return url
    raise ProfileError(
        f"{what} uses plaintext {scheme}://, which would expose the participant session and "
        "Guacamole token to any observer on the path. Use https, or pass allow_plaintext_loopback "
        "for a loopback target."
    )


class Protocol(StrEnum):
    """Guacamole protocol profile for the session check.

    Defaults to RDP: the terminal check already proves the SSH path end to end,
    so driving Guacamole over RDP widens real coverage instead of re-proving SSH
    through a second broker.
    """

    RDP = "rdp"
    SSH = "ssh"


@dataclass(frozen=True)
class Deadlines:
    """Per-check and whole-run bounds, in seconds. Every wait is bounded."""

    session_seconds: float = 60.0
    terminal_open_seconds: float = 30.0
    terminal_exchange_seconds: float = 45.0
    guacamole_bootstrap_seconds: float = 90.0
    guacamole_connect_seconds: float = 60.0
    run_seconds: float = 600.0

    def __post_init__(self) -> None:
        for name in (
            "session_seconds",
            "terminal_open_seconds",
            "terminal_exchange_seconds",
            "guacamole_bootstrap_seconds",
            "guacamole_connect_seconds",
            "run_seconds",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value <= 0:
                raise ProfileError(f"deadline {name} must be a positive number of seconds")


@dataclass(frozen=True)
class RunProfile:
    """A validated, non-secret description of one run."""

    origin: str
    environment: str
    target_role: str = "attacker"
    protocol: Protocol = Protocol.RDP
    deadlines: Deadlines = None  # type: ignore[assignment]  # normalised below
    #: The harness never destroys an operator-supplied example range.
    destroy_range: bool = False
    allow_production: bool = False
    #: Opt-in for a loopback target only; never permits plaintext to a real host.
    allow_plaintext_loopback: bool = False
    evidence_path: str | None = None

    def __post_init__(self) -> None:
        if self.deadlines is None:
            object.__setattr__(self, "deadlines", Deadlines())
        object.__setattr__(self, "origin", _validated_origin(self.origin))
        require_secure_url(self.origin, what="portal origin", allow_plaintext_loopback=self.allow_plaintext_loopback)
        object.__setattr__(self, "environment", _validated_environment(self.environment))
        if not self.target_role or not self.target_role.strip():
            raise ProfileError("target_role is required (the authored logical target, e.g. 'attacker')")
        object.__setattr__(self, "target_role", self.target_role.strip().lower())
        object.__setattr__(self, "protocol", Protocol(self.protocol))
        if self.destroy_range:
            raise ProfileError(
                "this harness consumes an operator-supplied example range and never destroys it; "
                "range teardown belongs to whoever created the range"
            )
        _assert_not_production(self.environment, self.origin, allow_production=self.allow_production)

    @property
    def channel(self) -> str:
        """The declared participant-access channel the Guacamole check requires."""
        return self.protocol.value

    @property
    def websocket_origin(self) -> str:
        """Origin header for the websocket handshake.

        Channels' ``AllowedHostsOriginValidator`` is part of the contract under
        test, and a browser sends ``Origin``; sending the exact configured origin
        keeps a rejection meaningful instead of a wrong-reason failure.
        """
        return self.origin


def _validated_origin(origin: str) -> str:
    if not origin or not str(origin).strip():
        raise ProfileError("origin is required (the exact portal origin, e.g. https://portal.example.com)")
    origin = str(origin).strip().rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme not in ("https", "http"):
        raise ProfileError(f"origin must be http(s); got {parsed.scheme!r}")
    if not parsed.hostname:
        raise ProfileError("origin must include a host")
    if parsed.path or parsed.query or parsed.fragment:
        raise ProfileError("origin must be a bare scheme://host[:port] with no path, query, or fragment")
    return origin


def _validated_environment(environment: str) -> str:
    if not environment or not str(environment).strip():
        raise ProfileError("environment is required (the operator-facing name of the target deployment)")
    return str(environment).strip()


def _assert_not_production(environment: str, origin: str, *, allow_production: bool) -> None:
    """Refuse a production-looking target unless positively acknowledged."""
    if allow_production:
        return
    host = (urlparse(origin).hostname or "").lower()
    env = environment.lower()
    # "gcp-dev" / "dev.example.com" contain no production marker; "prod-tenant"
    # and "portal.prod.example.com" do. Matching on dot/dash-delimited labels
    # keeps substrings like "reproduction" from tripping the guard.
    labels = set(env.replace("-", ".").replace("_", ".").split(".")) | set(host.split("."))
    if labels & set(_PRODUCTION_MARKERS):
        raise ProfileError(
            f"target {environment!r} ({host}) looks like production; "
            "re-run with allow_production set only if you positively intend it"
        )


def reject_forbidden_keys(supplied: dict[str, object]) -> None:
    """Raise if the caller tried to supply realized connection material."""
    offending = sorted(FORBIDDEN_PROFILE_KEYS & {str(key).lower() for key in supplied})
    if offending:
        raise ProfileError(
            f"run profile must not carry connection material: {', '.join(offending)}. "
            "The portal resolves the realized binding from the range's authored participant_access."
        )
