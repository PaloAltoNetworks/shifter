"""Closed contracts for participant-held remote-access credentials.

Only non-secret binding metadata crosses the range-substrate boundary. Profile
content is resolved from the provider secret store and validated in memory at
the Engine access boundary before delivery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

OPENVPN_CAPABILITY_VERSION = "openvpn-capability-v1"
OPENVPN_BINDING_VERSION = "openvpn-binding-v1"
OPENVPN_PROFILE_VERSION = "openvpn-profile-v1"
OPENVPN_PROFILE_MEDIA_TYPE = "application/x-openvpn-profile"
OPENVPN_PROFILE_MAX_BYTES = 64 * 1024

_BINDING_KEYS = {
    "version",
    "channel",
    "generation",
    "owner_user_id",
    "target_ref",
    "endpoint",
    "port",
    "profile_version",
    "secret_ref",
    "ready",
}
_CAPABILITY_KEYS = {"version", "channel", "target_ref", "teardown_at"}
OPENVPN_CAPABILITY_MAX_WINDOW = timedelta(days=397)
_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
    r"(?:\.(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))*\Z"
)
_INLINE_BLOCKS = frozenset({"ca", "cert", "key", "tls-crypt"})
_NO_ARGUMENT_DIRECTIVES = frozenset({"client", "nobind", "persist-key", "persist-tun", "auth-nocache"})
_ONE_ARGUMENT_DIRECTIVES = {
    "dev": frozenset({"tun"}),
    "proto": frozenset({"udp", "udp4"}),
    "resolv-retry": frozenset({"infinite"}),
    "remote-cert-tls": frozenset({"server"}),
    "verb": frozenset({"3"}),
    "auth": frozenset({"SHA256"}),
    "cipher": frozenset({"AES-256-GCM"}),
    "tls-version-min": frozenset({"1.2"}),
}


class TerminalConnection(Protocol):
    """Behavioral contract for an interactive terminal connection."""

    @property
    def is_connected(self) -> bool:
        """Return whether the terminal transport remains connected."""
        ...

    async def connect(self) -> None:
        """Establish the terminal connection."""
        ...

    async def disconnect(self) -> None:
        """Close the terminal connection."""
        ...

    async def send(self, data: bytes) -> None:
        """Send terminal input bytes."""
        ...

    async def receive(self, timeout: float = 0.1) -> bytes:
        """Receive terminal output bytes."""
        ...

    def at_eof(self) -> bool:
        """Return whether the remote terminal output stream reached EOF."""
        ...

    async def resize(self, cols: int, rows: int) -> None:
        """Resize the remote pseudo-terminal."""
        ...


class TerminalConnectionFactory(Protocol):
    """Constructs a fresh :class:`TerminalConnection` from authorized facts.

    The injection seam for interactive terminal access (issue #993). It is
    handed the already-authorized, already-resolved connection facts and returns
    a not-yet-connected :class:`TerminalConnection`. Production supplies a real
    SSH transport; a consumer test supplies a fake without patching the SSH
    library or bypassing the workspace/runtime authorization that runs before
    the factory is invoked. This types the constructor callable beside the one
    behavioral protocol; it does not duplicate that contract.
    """

    def __call__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        private_key: str,
        host_public_key: str,
        session_id: str | None,
    ) -> TerminalConnection:
        """Return a fresh terminal connection for the authorized target."""
        ...


class OpenVpnBindingError(ValueError):
    """A remote-access binding or resolved profile violated its closed shape."""


@dataclass(frozen=True)
class OpenVpnBinding:
    """Validated non-secret OpenVPN access metadata for one range generation."""

    generation: UUID
    owner_user_id: int
    target_ref: UUID
    endpoint: str
    port: int
    secret_ref: str
    ready: bool
    channel: str = "openvpn"
    version: str = OPENVPN_BINDING_VERSION
    profile_version: str = OPENVPN_PROFILE_VERSION


@dataclass(frozen=True)
class OpenVpnCapability:
    """Server-issued authorization to provision one generation-bound VPN edge."""

    target_ref: UUID
    teardown_at: datetime
    channel: str = "openvpn"
    version: str = OPENVPN_CAPABILITY_VERSION

    def as_dict(self) -> dict[str, object]:
        """Return the canonical JSON representation persisted by Engine."""
        return {
            "version": self.version,
            "channel": self.channel,
            "target_ref": str(self.target_ref),
            "teardown_at": self.teardown_at.isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True)
class OpenVpnProfile:
    """In-memory profile returned only after current access checks pass."""

    content: bytes
    generation: UUID
    profile_version: str


def _require_uuid(value: object, field: str) -> UUID:
    """Parse a UUID field or reject the payload."""
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise OpenVpnBindingError(f"{field} must be a UUID") from exc


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict[str, object]:
    """Require a dict with exactly the expected keys; reject extensions."""
    if not isinstance(value, dict):
        raise OpenVpnBindingError(f"{label} must be an object")
    keys = set(value)
    if keys != expected:
        unknown = sorted(keys - expected)
        missing = sorted(expected - keys)
        detail = f"unknown fields {unknown}" if unknown else f"missing fields {missing}"
        raise OpenVpnBindingError(f"{label} has {detail}")
    return value


def _require_utc_datetime(value: object, field: str) -> datetime:
    """Parse one canonical timezone-aware RFC 3339 timestamp."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise OpenVpnBindingError(f"{field} must be a UTC RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OpenVpnBindingError(f"{field} must be a UTC RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise OpenVpnBindingError(f"{field} must be a UTC RFC 3339 timestamp")
    return parsed.astimezone(UTC)


def parse_openvpn_capability(value: object) -> OpenVpnCapability:
    """Parse the exact server-issued provisioning authorization shape."""
    value = _require_exact_keys(value, _CAPABILITY_KEYS, "capability")
    if value["version"] != OPENVPN_CAPABILITY_VERSION:
        raise OpenVpnBindingError("unsupported capability version")
    if value["channel"] != "openvpn":
        raise OpenVpnBindingError("capability channel must be openvpn")
    return OpenVpnCapability(
        target_ref=_require_uuid(value["target_ref"], "target_ref"),
        teardown_at=_require_utc_datetime(value["teardown_at"], "teardown_at"),
    )


def build_openvpn_capability(target_ref: object, teardown_at: datetime) -> dict[str, object]:
    """Build a canonical capability from trusted server-owned lifecycle facts."""
    if not isinstance(teardown_at, datetime):
        raise OpenVpnBindingError("teardown_at must be a timezone-aware datetime")
    normalized_teardown = _require_utc_datetime(teardown_at.isoformat(), "teardown_at")
    if normalized_teardown.microsecond:
        normalized_teardown = normalized_teardown.replace(microsecond=0) + timedelta(seconds=1)
    capability = OpenVpnCapability(
        target_ref=_require_uuid(target_ref, "target_ref"),
        teardown_at=normalized_teardown,
    )
    validate_openvpn_capability_window(capability)
    return capability.as_dict()


def validate_openvpn_capability_window(
    capability: OpenVpnCapability,
    *,
    now: datetime | None = None,
) -> None:
    """Reject stale or unbounded credential windows before provider mutation."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if capability.teardown_at <= current:
        raise OpenVpnBindingError("OpenVPN teardown deadline must be in the future")
    if capability.teardown_at - current > OPENVPN_CAPABILITY_MAX_WINDOW:
        raise OpenVpnBindingError(
            f"OpenVPN teardown deadline exceeds the {OPENVPN_CAPABILITY_MAX_WINDOW.days}-day maximum"
        )


def _require_owner_user_id(value: object) -> int:
    """Require a positive integer owner id."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OpenVpnBindingError("owner_user_id must be a positive integer")
    return value


def _require_port(value: object) -> int:
    """Require a valid TCP/UDP port number."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise OpenVpnBindingError("port must be between 1 and 65535")
    return value


def _require_ready(value: object) -> bool:
    """Require a boolean readiness flag."""
    if not isinstance(value, bool):
        raise OpenVpnBindingError("ready must be a boolean")
    return value


def _require_endpoint(value: object) -> str:
    """Require a bounded hostname or address endpoint."""
    if not isinstance(value, str) or not _HOST_RE.fullmatch(value):
        raise OpenVpnBindingError("endpoint must be a bounded hostname or address")
    return value


def _require_secret_ref(value: object) -> str:
    """Require a bounded single-line provider secret reference."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 500
        or value != value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise OpenVpnBindingError("secret_ref must be a bounded single-line provider reference")
    return value


def _require_binding_versions(value: dict[str, object]) -> None:
    """Reject bindings whose version, channel, or profile version differ."""
    if value["version"] != OPENVPN_BINDING_VERSION:
        raise OpenVpnBindingError("unsupported binding version")
    if value["channel"] != "openvpn":
        raise OpenVpnBindingError("channel must be openvpn")
    if value["profile_version"] != OPENVPN_PROFILE_VERSION:
        raise OpenVpnBindingError("unsupported profile_version")


def parse_openvpn_binding(value: object) -> OpenVpnBinding:
    """Parse the exact non-secret OpenVPN binding shape; reject extensions."""
    value = _require_exact_keys(value, _BINDING_KEYS, "binding")
    _require_binding_versions(value)
    return OpenVpnBinding(
        generation=_require_uuid(value["generation"], "generation"),
        owner_user_id=_require_owner_user_id(value["owner_user_id"]),
        target_ref=_require_uuid(value["target_ref"], "target_ref"),
        endpoint=_require_endpoint(value["endpoint"]),
        port=_require_port(value["port"]),
        secret_ref=_require_secret_ref(value["secret_ref"]),
        ready=_require_ready(value["ready"]),
    )


def _allowed_directive_forms(binding: OpenVpnBinding) -> dict[str, set[tuple[str, ...]]]:
    """Closed map of directive name to the argument tuples allowed for it."""
    forms: dict[str, set[tuple[str, ...]]] = {name: {()} for name in _NO_ARGUMENT_DIRECTIVES}
    forms.update(
        {name: {(argument,) for argument in arguments} for name, arguments in _ONE_ARGUMENT_DIRECTIVES.items()}
    )
    forms["remote"] = {(binding.endpoint, str(binding.port))}
    forms["data-ciphers"] = {("AES-256-GCM:AES-128-GCM",)}
    return forms


def _validate_directive(parts: list[str], allowed_forms: dict[str, set[tuple[str, ...]]]) -> None:
    """Reject any directive outside the closed allow-list for this binding."""
    allowed = allowed_forms.get(parts[0])
    if allowed is None or tuple(parts[1:]) not in allowed:
        raise OpenVpnBindingError(f"profile contains forbidden or malformed directive {parts[0]!r}")


def _consume_block_line(line: str, open_block: str, seen_blocks: set[str]) -> str | None:
    """Advance the inline-block state machine while inside an open block."""
    if line == f"</{open_block}>":
        seen_blocks.add(open_block)
        return None
    if line.startswith("<"):
        raise OpenVpnBindingError("profile contains a malformed inline credential block")
    return open_block


def _opened_block(line: str, seen_blocks: set[str]) -> str | None:
    """Return the block name when the line opens a new inline credential block."""
    if not (line.startswith("<") and line.endswith(">") and not line.startswith("</")):
        return None
    block = line[1:-1]
    if block not in _INLINE_BLOCKS or block in seen_blocks:
        raise OpenVpnBindingError("profile contains an unsupported inline credential block")
    return block


def _scan_profile(profile: str, binding: OpenVpnBinding) -> tuple[set[str], set[str]]:
    """Walk profile lines; return the inline blocks and directive names seen."""
    allowed_forms = _allowed_directive_forms(binding)
    open_block: str | None = None
    seen_blocks: set[str] = set()
    seen_directives: set[str] = set()
    for raw_line in profile.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if open_block is not None:
            open_block = _consume_block_line(line, open_block, seen_blocks)
            continue
        opened = _opened_block(line, seen_blocks)
        if opened is not None:
            open_block = opened
            continue
        parts = line.split()
        _validate_directive(parts, allowed_forms)
        seen_directives.add(parts[0])
    if open_block is not None:
        raise OpenVpnBindingError("profile has an unterminated inline credential block")
    return seen_blocks, seen_directives


def validate_openvpn_profile(profile: str, binding: OpenVpnBinding) -> bytes:
    """Return validated UTF-8 profile bytes for the exact current binding."""
    if not isinstance(profile, str) or not profile or "\x00" in profile or "\r" in profile:
        raise OpenVpnBindingError("profile must be non-empty normalized UTF-8 text")
    encoded = profile.encode("utf-8")
    if len(encoded) > OPENVPN_PROFILE_MAX_BYTES:
        raise OpenVpnBindingError("profile exceeds the maximum size")
    seen_blocks, seen_directives = _scan_profile(profile, binding)
    required_directives = {"client", "dev", "proto", "remote", "nobind", "remote-cert-tls", "auth-nocache"}
    if not required_directives.issubset(seen_directives) or seen_blocks != _INLINE_BLOCKS:
        raise OpenVpnBindingError("profile is missing required directives or inline credentials")
    return encoded


def openvpn_binding_available(value: object, owner_user_id: int) -> bool:
    """Return whether a binding is ready and belongs to the current range owner."""
    try:
        binding = parse_openvpn_binding(value)
    except OpenVpnBindingError:
        return False
    return binding.ready and binding.owner_user_id == owner_user_id
