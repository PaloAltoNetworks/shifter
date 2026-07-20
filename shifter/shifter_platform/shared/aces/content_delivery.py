"""Source-backed ACES content delivery contract (#1564, ADR-032-R3, ADR-034-R6).

Pure delivery primitives shared across the launch (materialize + promote),
transport, and provisioner (join + verify + realize) boundaries:

- ``DeliveryBinding``: the versioned, server-owned, byte-free identity that rides
  *beside* the serialized ProvisioningPlan, never inside it. It carries only a
  compiled content resource address, the sha256 of the delivered payload, the
  normalized content-addressed object key, and the byte count -- no payload
  bytes, URL, bucket, credential, or guest path (ADR-032-R3).
- ``DeliveryProjection`` / ``DeliveryProjectionEntry``: the author-declared,
  associated-artifact-inventory-validated mapping from a content ``source``
  identity ``(name, version, content_type, format)`` to one pack-relative input
  path + its expected digest (ADR-034-R6). Resolution is exact and fail-closed;
  a source is never inferred from a filename, extension, directory order, or
  scenario identity.
- The deterministic materializer seam: source-backed ``file`` and ``directory``
  produce reproducible payload bytes; every other shape (``dataset``, generator
  formats) is non-realizable and fails closed until a materializer + probe lands.

This module imports no ``cms`` / ``engine`` and touches no cloud SDK; it operates
on plain values and a local materialization source path handed in by the caller.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TypeGuard

#: Rolling-deploy seam: persisted / transported bindings carry this version, and
#: readers reject any version they do not explicitly support (ADR-032-R3).
BINDING_VERSION = 1
FEATURE_BINDING_VERSION = 2
_SUPPORTED_PROJECTION_VERSIONS = frozenset({1, 2})
_HEX_SHA256_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")

#: Content types that have a deterministic materializer + digest-readback probe,
#: i.e. every plan shape admitted by the type has a genuine, verifiable guest
#: effect. This is the delivery-materialization support set; the manifest
#: capability declaration and the provisioner realized-content policy are
#: independent envelopes that must agree with it in production (ADR-032-R6).
SUPPORTED_DELIVERY_CONTENT_TYPES = frozenset({"file", "directory"})
_FILE_FORMATS = frozenset({"", "raw", "file"})
_DIRECTORY_FORMATS = frozenset({"", "tree", "directory"})
_FILE_MODE = 0o644

_BINDING_V1_KEYS = frozenset({"content_address", "sha256", "storage_key", "byte_count", "binding_version"})
_BINDING_V2_KEYS = frozenset(
    {
        "resource_type",
        "resource_address",
        "payload_kind",
        "install_policy",
        "sha256",
        "storage_key",
        "byte_count",
        "binding_version",
    }
)

__all__ = [
    "BINDING_VERSION",
    "FEATURE_BINDING_VERSION",
    "SUPPORTED_DELIVERY_CONTENT_TYPES",
    "ContentDeliveryError",
    "DeliveryBinding",
    "DeliveryProjection",
    "DeliveryProjectionEntry",
    "materialize_payload",
    "normalized_storage_key",
    "parse_delivery_projection",
    "sha256_hex",
]


class ContentDeliveryError(Exception):
    """A source-backed content item could not be projected, materialized, or bound."""


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _is_hex_sha256(value: object) -> TypeGuard[str]:
    """True when ``value`` is a lowercase 64-char hex sha256 string."""
    return isinstance(value, str) and len(value) == _HEX_SHA256_LEN and _HEX_DIGITS.issuperset(value)


def _require(condition: bool, message: str) -> None:
    """Raise ``ContentDeliveryError(message)`` unless ``condition`` is true."""
    if not condition:
        raise ContentDeliveryError(message)


def _validated_str(value: object, message: str) -> str:
    """Return ``value`` as a non-empty str, or fail closed with ``message``."""
    if not isinstance(value, str) or not value:
        raise ContentDeliveryError(message)
    return value


def _validated_sha256(value: object, message: str) -> str:
    """Return ``value`` as a lowercase hex sha256 str, or fail closed with ``message``."""
    if not _is_hex_sha256(value):
        raise ContentDeliveryError(message)
    return value


def _validated_byte_count(value: object, message: str) -> int:
    """Return ``value`` as a non-negative, non-bool int, or fail closed with ``message``."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContentDeliveryError(message)
    return value


def normalized_storage_key(prefix: str, digest: str) -> str:
    """Return a content-addressed object key ``<prefix>/<dd>/<digest>``.

    The key is derived solely from the server-owned prefix and the payload
    digest, so writes are idempotent and no authored value influences the
    location. Fails closed on a missing prefix or a non-sha256 digest.
    """
    if not isinstance(prefix, str) or not prefix.strip():
        raise ContentDeliveryError("delivery storage prefix is not configured")
    if not _is_hex_sha256(digest):
        raise ContentDeliveryError("content digest is not a lowercase hex sha256")
    return f"{prefix.strip().strip('/')}/{digest[:2]}/{digest}"


@dataclass(frozen=True)
class DeliveryBinding:
    """Server-owned, byte-free delivery identity that rides beside the plan."""

    content_address: str | None
    sha256: str
    storage_key: str
    byte_count: int
    binding_version: int = BINDING_VERSION
    resource_type: str | None = None
    resource_address: str | None = None
    payload_kind: str | None = None
    install_policy: str | None = None

    def to_transport(self) -> dict[str, object]:
        """Return the JSON-serialisable transport shape (identity only)."""
        if self.binding_version == BINDING_VERSION:
            return {
                "content_address": self.content_address,
                "sha256": self.sha256,
                "storage_key": self.storage_key,
                "byte_count": self.byte_count,
                "binding_version": self.binding_version,
            }
        if self.binding_version == FEATURE_BINDING_VERSION:
            return {
                "resource_type": self.resource_type,
                "resource_address": self.resource_address,
                "payload_kind": self.payload_kind,
                "install_policy": self.install_policy,
                "sha256": self.sha256,
                "storage_key": self.storage_key,
                "byte_count": self.byte_count,
                "binding_version": self.binding_version,
            }
        raise ContentDeliveryError(f"unsupported delivery binding version {self.binding_version!r}")

    @classmethod
    def from_transport(cls, raw: Mapping[str, object]) -> DeliveryBinding:
        """Rebuild a binding from transport, failing closed on any tamper.

        Rejects unknown keys (so a smuggled URL / bucket / bytes field cannot
        ride along), an unsupported version, a non-sha256 digest, an empty
        address / key, or a negative byte count.
        """
        invalid_shape = "delivery binding transport shape is invalid"
        _require(isinstance(raw, Mapping), invalid_shape)
        version = raw.get("binding_version")
        storage_key = _validated_str(raw.get("storage_key"), "delivery binding storage_key is invalid")
        sha256 = _validated_sha256(raw.get("sha256"), "delivery binding sha256 is invalid")
        byte_count = _validated_byte_count(raw.get("byte_count"), "delivery binding byte_count is invalid")
        if version == BINDING_VERSION:
            _require(set(raw) == _BINDING_V1_KEYS, invalid_shape)
            return cls(
                content_address=_validated_str(
                    raw.get("content_address"), "delivery binding content_address is invalid"
                ),
                sha256=sha256,
                storage_key=storage_key,
                byte_count=byte_count,
                binding_version=BINDING_VERSION,
            )
        if version == FEATURE_BINDING_VERSION:
            _require(set(raw) == _BINDING_V2_KEYS, invalid_shape)
            resource_type = _validated_str(raw.get("resource_type"), "delivery binding resource_type is invalid")
            _require(resource_type == "feature-binding", "delivery binding resource_type is unsupported")
            payload_kind = _validated_str(raw.get("payload_kind"), "delivery binding payload_kind is invalid")
            install_policy = _validated_str(raw.get("install_policy"), "delivery binding install_policy is invalid")
            _require(payload_kind in {"file", "directory"}, "delivery binding payload_kind is unsupported")
            _require(
                (payload_kind, install_policy)
                in {("file", "executable"), ("file", "configuration"), ("directory", "configuration")},
                "delivery binding install policy is unsupported",
            )
            return cls(
                content_address=None,
                binding_version=FEATURE_BINDING_VERSION,
                resource_type=resource_type,
                resource_address=_validated_str(
                    raw.get("resource_address"), "delivery binding resource_address is invalid"
                ),
                payload_kind=payload_kind,
                install_policy=install_policy,
                sha256=sha256,
                storage_key=storage_key,
                byte_count=byte_count,
            )
        raise ContentDeliveryError(f"unsupported delivery binding version {version!r}")


@dataclass(frozen=True)
class DeliveryProjectionEntry:
    """One author-declared source-identity -> pack-input binding.

    The entry maps a content ``source`` to a pack-relative input path only.
    Source-byte integrity is not duplicated here: the caller cross-checks the
    referenced path (and every file under it, for a directory) against the pack's
    associated-artifact inventory, which is itself whole-pack digest-bound.
    """

    source_name: str
    source_version: str
    content_type: str
    content_format: str
    input_path: str
    resource_type: str = "content-placement"
    feature_type: str = ""
    payload_kind: str = ""
    install_policy: str = ""


@dataclass(frozen=True)
class DeliveryProjection:
    """The parsed, validated set of delivery-projection entries for one pack."""

    entries: tuple[DeliveryProjectionEntry, ...]

    def resolve(
        self,
        *,
        source_name: str,
        source_version: str,
        content_type: str,
        content_format: str,
    ) -> DeliveryProjectionEntry:
        """Return the single entry matching the content source, or fail closed.

        Match is exact on ``(name, content_type, format)``; version matches when
        either side is the ``"*"`` wildcard or the versions are equal. A missing
        match or more than one candidate (an ambiguous wildcard) fails closed --
        no filename / extension / directory-order fallback.
        """
        matches = [
            entry
            for entry in self.entries
            if entry.resource_type == "content-placement"
            and entry.source_name == source_name
            and entry.content_type == content_type
            and entry.content_format == content_format
            and (source_version == "*" or entry.source_version == "*" or entry.source_version == source_version)
        ]
        if not matches:
            raise ContentDeliveryError(f"no delivery projection entry for source '{source_name}' ({content_type})")
        if len(matches) > 1:
            raise ContentDeliveryError(f"ambiguous delivery projection for source '{source_name}' ({content_type})")
        return matches[0]

    def resolve_feature(
        self,
        *,
        source_name: str,
        source_version: str,
        feature_type: str,
    ) -> DeliveryProjectionEntry:
        """Return the single feature projection matching an exact source shape."""
        matches = [
            entry
            for entry in self.entries
            if entry.resource_type == "feature-binding"
            and entry.source_name == source_name
            and entry.feature_type == feature_type
            and entry.source_version == source_version
        ]
        if not matches:
            raise ContentDeliveryError(f"no delivery projection entry for source '{source_name}' ({feature_type})")
        if len(matches) > 1:
            raise ContentDeliveryError(f"ambiguous delivery projection for source '{source_name}' ({feature_type})")
        return matches[0]


def parse_delivery_projection(raw: Mapping[str, object]) -> DeliveryProjection:
    """Parse + validate a pack's delivery-projection document, failing closed.

    The document is versioned and lists explicit entries; the caller
    additionally cross-checks each ``sha256`` / ``input_path`` against the pack's
    associated-artifact inventory before trusting an entry (ADR-034-R6).
    """
    if not isinstance(raw, Mapping):
        raise ContentDeliveryError("delivery projection must be a mapping")
    version = raw.get("version")
    if version not in _SUPPORTED_PROJECTION_VERSIONS:
        raise ContentDeliveryError("unsupported delivery projection version")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list):
        raise ContentDeliveryError("delivery projection 'entries' must be a list")
    entries: list[DeliveryProjectionEntry] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for item in entries_raw:
        entry = _parse_entry(item, version=int(version))
        key = (
            entry.resource_type,
            entry.source_name,
            entry.source_version,
            entry.content_type,
            entry.content_format,
            entry.feature_type,
        )
        if key in seen:
            raise ContentDeliveryError("duplicate delivery projection entry")
        seen.add(key)
        entries.append(entry)
    return DeliveryProjection(entries=tuple(entries))


def _parse_entry(item: object, *, version: int) -> DeliveryProjectionEntry:
    """Validate one raw projection entry mapping into a typed entry."""
    if not isinstance(item, Mapping):
        raise ContentDeliveryError("delivery projection entry must be a mapping")
    source = item.get("source")
    if not isinstance(source, Mapping):
        raise ContentDeliveryError("delivery projection entry requires 'source'")
    name = _validated_str(source.get("name"), "delivery projection entry 'source.name' is invalid")
    source_version = _validated_str(source.get("version", "*"), "delivery projection entry 'source.version' is invalid")
    input_path = _validated_str(item.get("input_path"), "delivery projection entry requires 'input_path'")
    _reject_unsafe_input_path(input_path)
    resource_type = (
        _validated_str(item.get("resource_type", "content-placement"), "invalid projection resource_type")
        if version == 2
        else "content-placement"
    )
    if resource_type == "content-placement":
        content_type = _validated_str(item.get("content_type"), "delivery projection entry content_type is invalid")
        if content_type not in SUPPORTED_DELIVERY_CONTENT_TYPES:
            raise ContentDeliveryError(f"delivery projection entry has unsupported content_type {content_type!r}")
        content_format = item.get("format", "")
        _require(isinstance(content_format, str), "delivery projection entry 'format' must be a string")
        feature_type = payload_kind = install_policy = ""
    elif resource_type == "feature-binding" and version == 2:
        feature_type = _validated_str(item.get("feature_type"), "feature projection type is invalid")
        payload_kind = _validated_str(item.get("payload_kind"), "feature projection payload kind is invalid")
        install_policy = _validated_str(item.get("install_policy"), "feature projection install policy is invalid")
        _require(feature_type in {"artifact", "configuration"}, "unsupported feature projection type")
        _require(payload_kind in SUPPORTED_DELIVERY_CONTENT_TYPES, "unsupported feature projection payload kind")
        _require(
            (payload_kind, install_policy)
            in {("file", "executable"), ("file", "configuration"), ("directory", "configuration")},
            "unsupported feature projection install policy",
        )
        content_type = payload_kind
        content_format = ""
    else:
        raise ContentDeliveryError("delivery projection entry has unsupported resource_type")
    return DeliveryProjectionEntry(
        source_name=name,
        source_version=source_version,
        content_type=content_type,
        content_format=content_format,
        input_path=input_path,
        resource_type=resource_type,
        feature_type=feature_type,
        payload_kind=payload_kind,
        install_policy=install_policy,
    )


def _reject_unsafe_input_path(path: str) -> None:
    """Reject absolute or parent-traversing pack-relative input paths."""
    pure = PurePosixPath(path)
    if path.startswith("/") or pure.is_absolute():
        raise ContentDeliveryError("delivery projection input_path must be pack-relative")
    if ".." in pure.parts:
        raise ContentDeliveryError("delivery projection input_path must not traverse")


def materialize_payload(
    *, content_type: str, content_format: str, source_path: Path, max_bytes: int | None = None
) -> bytes:
    """Return the deterministic delivery payload bytes for one content item.

    ``file`` yields the file bytes verbatim; ``directory`` yields a reproducible
    (sorted, identity-normalized, uncompressed) tar of the subtree. Any other
    content type or format is non-realizable and fails closed.

    When ``max_bytes`` is provided it caps the materialized payload, failing
    closed *before* buffering an oversized input (a file whose size, or a
    directory whose cumulative member bytes, exceed the bound) so a large pack
    input cannot exhaust the process. Callers on the production path
    (``content_delivery_prep``) always pass it; unit callers may omit it.
    """
    if content_type == "file":
        return _materialize_file(content_format, source_path, max_bytes)
    if content_type == "directory":
        return _materialize_directory(content_format, source_path, max_bytes)
    raise ContentDeliveryError(f"content type {content_type!r} has no deterministic materializer")


def _check_max_bytes(size: int, max_bytes: int | None) -> None:
    """Fail closed when ``size`` exceeds a configured ``max_bytes`` cap."""
    if max_bytes is not None and size > max_bytes:
        raise ContentDeliveryError("content delivery payload exceeds the configured size bound")


def _materialize_file(content_format: str, source_path: Path, max_bytes: int | None) -> bytes:
    """Return the raw bytes of a source-backed file (size-gated before reading)."""
    if content_format not in _FILE_FORMATS:
        raise ContentDeliveryError(f"file format {content_format!r} has no deterministic materializer")
    if source_path.is_symlink() or not source_path.is_file():
        raise ContentDeliveryError("file delivery source is missing or not a regular file")
    _check_max_bytes(source_path.stat().st_size, max_bytes)
    return source_path.read_bytes()


def _materialize_directory(content_format: str, source_path: Path, max_bytes: int | None) -> bytes:
    """Return a deterministic tar of a source-backed directory subtree (size-gated)."""
    if content_format not in _DIRECTORY_FORMATS:
        raise ContentDeliveryError(f"directory format {content_format!r} has no deterministic materializer")
    if source_path.is_symlink() or not source_path.is_dir():
        raise ContentDeliveryError("directory delivery source is missing or not a directory")
    buffer = io.BytesIO()
    written = 0
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for rel, abspath in _collect_regular_files(source_path):
            written += abspath.stat().st_size
            _check_max_bytes(written, max_bytes)
            data = abspath.read_bytes()
            info = tarfile.TarInfo(name=rel)
            info.size = len(data)
            info.mtime = 0
            info.mode = _FILE_MODE
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _collect_regular_files(root: Path) -> list[tuple[str, Path]]:
    """Return sorted (relative-posix, absolute) regular files under ``root``.

    Fails closed on any symlink or special file so a source tree cannot smuggle
    a link or device into the delivered payload.
    """
    resolved = root.resolve()
    collected: list[tuple[str, Path]] = []
    for path in sorted(resolved.rglob("*"), key=lambda entry: entry.relative_to(resolved).as_posix()):
        if path.is_symlink():
            raise ContentDeliveryError("directory delivery source contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ContentDeliveryError("directory delivery source contains a non-regular file")
        collected.append((path.relative_to(resolved).as_posix(), path))
    return collected
