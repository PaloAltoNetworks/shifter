"""CMS-side preparation of source-backed RAES content delivery (#1564, S2).

While a registered pack is live (digest-verified, immutable) this module binds
each compiled source-backed content resource to its author-declared pack input,
verifies that input against the pack's associated-artifact inventory,
materializes a deterministic payload, promotes it to a content-addressed object
under the platform assets bucket, and returns the byte-free ``DeliveryBinding``
tuple that rides *beside* the serialized ProvisioningPlan (ADR-032-R3,
ADR-034-R6).

Reused, not reinvented: the pure delivery contract (:mod:`shared.raes.content_delivery`),
the upstream associated-artifact inventory (``raes_env_packs``), and the
provider-neutral object-storage boundary (injected ``ObjectStorage``). No
standalone artifact store is introduced; no payload bytes, object keys, or pack
paths are logged.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from shared.log_sanitize import safe_log_value
from shared.raes.content_delivery import (
    FEATURE_BINDING_VERSION,
    ContentDeliveryError,
    DeliveryBinding,
    DeliveryProjection,
    materialize_payload,
    normalized_storage_key,
    parse_delivery_projection,
    sha256_hex,
)

if TYPE_CHECKING:
    from shared.cloud.types import ObjectStorage

logger = logging.getLogger(__name__)

#: Pack-relative location of the author-declared delivery projection document.
PROJECTION_RELPATH = "delivery/content-projection.json"
_CONTENT_PLACEMENT_RESOURCE_TYPE = "content-placement"
_FEATURE_BINDING_RESOURCE_TYPE = "feature-binding"
_PACK_URI_SCHEME = "raes-environment-pack"
_OCTET_STREAM = "application/octet-stream"
#: Streaming read chunk for size-gated digesting (never buffers a whole file).
_READ_CHUNK_BYTES = 1024 * 1024

__all__ = [
    "PROJECTION_RELPATH",
    "DeliveryTarget",
    "InventoryEntry",
    "has_source_backed_content",
    "prepare_content_delivery",
]


def has_source_backed_content(serialized_plan: Mapping[str, object]) -> bool:
    """Return True if the plan carries any source-backed content placement.

    Cheap, side-effect-free precheck so callers can skip object-storage / pack
    resolution entirely for the common no-source-backed-content plan.
    """
    return bool(_source_backed_content_refs(serialized_plan))


@dataclass(frozen=True)
class InventoryEntry:
    """One associated-artifact inventory record: expected digest + declared size."""

    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class _ContentRef:
    """A source-backed content-placement extracted from the serialized plan."""

    address: str
    source_name: str
    source_version: str
    content_type: str
    content_format: str
    resource_type: str = _CONTENT_PLACEMENT_RESOURCE_TYPE
    feature_type: str = ""
    install_policy: str = ""


@dataclass(frozen=True)
class DeliveryTarget:
    """Where prepared content-delivery payloads are promoted to.

    Bundles the object-storage boundary, the destination bucket/prefix, and the
    materialized-payload size cap that :func:`prepare_content_delivery` needs to
    promote each source-backed content resource (ADR-032-R3, ADR-034-R6).
    """

    storage: ObjectStorage
    bucket: str
    prefix: str
    max_payload_bytes: int


def prepare_content_delivery(
    *,
    pack_root: Path | None,
    serialized_plan: Mapping[str, object],
    target: DeliveryTarget,
    projection_loader: Callable[[Path], DeliveryProjection] | None = None,
    inventory_loader: Callable[[Path], dict[str, InventoryEntry]] | None = None,
) -> tuple[DeliveryBinding, ...]:
    """Return the delivery bindings for every source-backed content in the plan.

    Returns an empty tuple when the plan has no source-backed content (the common
    case). Otherwise, for each such content resource this resolves the pack input
    through the author-declared projection, cross-checks it against the pack's
    associated-artifact inventory, materializes a deterministic payload, promotes
    it content-addressed to ``target.bucket``/``target.prefix``, and returns the
    byte-free binding. Any failure raises ``ContentDeliveryError`` (the caller
    marks the range reservation FAILED); nothing is dispatched on a partial
    preparation.
    """
    refs = _source_backed_content_refs(serialized_plan)
    if not refs:
        return ()
    if pack_root is None:
        raise ContentDeliveryError("pack root is unavailable for source-backed content delivery")
    if not isinstance(target.bucket, str) or not target.bucket.strip():
        raise ContentDeliveryError("content delivery bucket is not configured")
    inventory = (inventory_loader or build_inventory_index)(pack_root)
    if projection_loader is None:
        # Only the real, file-reading default loader needs the inventory
        # cross-check: it is the projection *document's own bytes* that must be
        # an inventory-covered artifact (ADR-034-R6), not whatever a caller's
        # injected loader hands back (e.g. tests exercising resolution/materialize
        # behavior against a canned DeliveryProjection with no on-disk document).
        _verify_projection_against_inventory(pack_root, inventory)
        projection = _load_pack_projection(pack_root)
    else:
        projection = projection_loader(pack_root)
    return tuple(_prepare_one(ref, pack_root, projection, inventory, target) for ref in refs)


def _prepare_one(
    ref: _ContentRef,
    pack_root: Path,
    projection: DeliveryProjection,
    inventory: dict[str, InventoryEntry],
    target: DeliveryTarget,
) -> DeliveryBinding:
    """Resolve, verify, materialize, promote, and bind one content resource."""
    if ref.resource_type == _FEATURE_BINDING_RESOURCE_TYPE:
        entry = projection.resolve_feature(
            source_name=ref.source_name,
            source_version=ref.source_version,
            feature_type=ref.feature_type,
        )
    else:
        entry = projection.resolve(
            source_name=ref.source_name,
            source_version=ref.source_version,
            content_type=ref.content_type,
            content_format=ref.content_format,
        )
    payload_kind = entry.payload_kind or ref.content_type
    content_format = entry.content_format
    input_abs = _resolve_pack_input(pack_root, entry.input_path)
    _verify_input_against_inventory(pack_root, input_abs, payload_kind, inventory, target.max_payload_bytes)
    payload = materialize_payload(
        content_type=payload_kind,
        content_format=content_format,
        source_path=input_abs,
        max_bytes=target.max_payload_bytes,
    )
    if len(payload) > target.max_payload_bytes:
        raise ContentDeliveryError("materialized content payload exceeds the configured size bound")
    digest = sha256_hex(payload)
    key = normalized_storage_key(target.prefix, digest)
    _promote(target.storage, target.bucket, key, payload)
    if ref.resource_type == _FEATURE_BINDING_RESOURCE_TYPE:
        return DeliveryBinding(
            content_address=None,
            sha256=digest,
            storage_key=key,
            byte_count=len(payload),
            binding_version=FEATURE_BINDING_VERSION,
            resource_type=_FEATURE_BINDING_RESOURCE_TYPE,
            resource_address=ref.address,
            payload_kind=payload_kind,
            install_policy=entry.install_policy,
        )
    return DeliveryBinding(content_address=ref.address, sha256=digest, storage_key=key, byte_count=len(payload))


def _source_backed_content_refs(serialized_plan: Mapping[str, object]) -> list[_ContentRef]:
    """Extract source-backed content-placement resources from the serialized plan.

    Inline (``text``) files and source-less directories carry no ``source`` and
    are realized by the existing guest bootstrap, not delivered, so they are
    skipped here. A malformed source (present but with no name) fails closed.
    """
    resources = serialized_plan.get("resources") if isinstance(serialized_plan, Mapping) else None
    if not isinstance(resources, Mapping):
        return []
    refs: list[_ContentRef] = []
    for address, resource in resources.items():
        ref = _content_ref_from_resource(address, resource)
        if ref is not None:
            refs.append(ref)
            continue
        ref = _feature_ref_from_resource(address, resource)
        if ref is not None:
            refs.append(ref)
    return refs


def _feature_template_from_resource(address: object, resource: object) -> tuple[Mapping[str, object], str] | None:
    """Return a feature template and canonical address for a valid resource."""
    if not isinstance(resource, Mapping) or resource.get("resource_type") != _FEATURE_BINDING_RESOURCE_TYPE:
        return None
    payload = resource.get("payload")
    spec = payload.get("spec") if isinstance(payload, Mapping) else None
    template = spec.get("template") if isinstance(spec, Mapping) else None
    if not isinstance(template, Mapping):
        return None
    return template, str(resource.get("address") or address)


def _feature_ref_from_resource(address: object, resource: object) -> _ContentRef | None:
    """Return one source-backed artifact/configuration delivery reference."""
    resolved = _feature_template_from_resource(address, resource)
    if resolved is None:
        return None
    template, resource_address = resolved
    feature_type = template.get("type")
    feature_type = feature_type.lower() if isinstance(feature_type, str) else ""
    if feature_type == "service":
        return None
    if feature_type not in {"artifact", "configuration"}:
        raise ContentDeliveryError("feature binding has no delivery realization")
    name, version = _parse_source(template.get("source"))
    if not name:
        raise ContentDeliveryError("source-backed feature has an unresolvable source name")
    return _ContentRef(
        address=resource_address,
        source_name=name,
        source_version=version,
        content_type="file",
        content_format="",
        resource_type=_FEATURE_BINDING_RESOURCE_TYPE,
        feature_type=feature_type,
        install_policy="",
    )


def _content_ref_from_resource(address: object, resource: object) -> _ContentRef | None:
    """Return the ``_ContentRef`` for one plan resource, or None if not deliverable.

    A resource is deliverable only when it is a content-placement carrying a
    ``source``; inline (``text``) files and source-less directories return None
    (realized by the existing guest bootstrap, not delivered here). A malformed
    source (present but with no name) fails closed.
    """
    if not isinstance(resource, Mapping):
        return None
    payload = resource.get("payload")
    spec = payload.get("spec") if isinstance(payload, Mapping) else None
    source = spec.get("source") if isinstance(spec, Mapping) else None
    if (
        resource.get("resource_type") != _CONTENT_PLACEMENT_RESOURCE_TYPE
        or not isinstance(spec, Mapping)
        or source is None
    ):
        return None
    name, version = _parse_source(source)
    if not name:
        raise ContentDeliveryError("source-backed content has an unresolvable source name")
    return _ContentRef(
        address=str(resource.get("address") or address),
        source_name=name,
        source_version=version,
        content_type=_spec_str(spec, "type", lower=True),
        content_format=_spec_str(spec, "format"),
    )


def _spec_str(spec: Mapping[str, object], key: str, *, lower: bool = False) -> str:
    """Return ``spec[key]`` as a string (lowercased when ``lower``), else ``""``."""
    value = spec.get(key)
    if not isinstance(value, str):
        return ""
    return value.lower() if lower else value


def _parse_source(source: object) -> tuple[str | None, str]:
    """Return ``(name, version)`` from a content ``source`` (string or mapping)."""
    if isinstance(source, str):
        stripped = source.strip()
        return (stripped or None, "*")
    if isinstance(source, Mapping):
        name = source.get("name")
        version = source.get("version")
        name = name.strip() if isinstance(name, str) and name.strip() else None
        version = version if isinstance(version, str) and version.strip() else "*"
        return name, version
    return None, "*"


def _resolve_pack_input(pack_root: Path, input_path: str) -> Path:
    """Resolve a pack-relative input path, fail-closed on escape or absence."""
    root = Path(pack_root).resolve()
    candidate = (root / input_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ContentDeliveryError("content delivery input escapes the pack root")
    if candidate.is_symlink() or not candidate.exists():
        raise ContentDeliveryError("content delivery input does not exist in the pack")
    return candidate


def _verify_input_against_inventory(
    pack_root: Path,
    input_abs: Path,
    content_type: str,
    inventory: Mapping[str, InventoryEntry],
    max_payload_bytes: int,
) -> None:
    """Fail closed unless every delivered file is an inventory-matching pack file.

    Size-gates on the trusted inventory metadata *before* reading any bytes, then
    streams each file's digest with the same cap, so an oversized (or a tampered,
    larger-than-declared) input is rejected without ever buffering it in memory
    (defense against a pack whose declared payload would exhaust the process
    before the materialized-payload cap in ``_prepare_one`` could reject it).
    """
    root = Path(pack_root).resolve()
    files = _deliverable_files(input_abs, content_type)
    records = _matched_inventory_records(files, root, inventory, max_payload_bytes)
    for path, record in records:
        if _sha256_file(path, max_payload_bytes) != record.sha256:
            raise ContentDeliveryError("content delivery input does not match the pack inventory digest")


def _deliverable_files(input_abs: Path, content_type: str) -> list[Path]:
    """Return the concrete files backing one content input, failing closed if none."""
    if content_type == "file":
        files = [input_abs]
    elif content_type == "directory":
        files = [path for path in sorted(input_abs.rglob("*")) if not path.is_dir()]
    else:
        raise ContentDeliveryError(f"content type {content_type!r} cannot be delivered")
    if not files:
        raise ContentDeliveryError("content delivery input has no deliverable files")
    return files


def _matched_inventory_records(
    files: list[Path], root: Path, inventory: Mapping[str, InventoryEntry], max_payload_bytes: int
) -> list[tuple[Path, InventoryEntry]]:
    """Return each file paired with its inventory record, size-gating as it accumulates.

    Fails closed on a non-regular file, an uninventoried file, or a declared
    total that would exceed ``max_payload_bytes`` -- all before any bytes are
    read (the digest itself is checked separately, in :func:`_sha256_file`).
    """
    records: list[tuple[Path, InventoryEntry]] = []
    declared_total = 0
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ContentDeliveryError("content delivery input contains a non-regular file")
        rel = path.relative_to(root).as_posix()
        record = inventory.get(rel)
        if record is None:
            raise ContentDeliveryError("content delivery input is not in the pack associated-artifact inventory")
        declared_total += max(record.size_bytes, 0)
        if declared_total > max_payload_bytes:
            raise ContentDeliveryError("content delivery input exceeds the configured size bound")
        records.append((path, record))
    return records


def _sha256_file(path: Path, max_bytes: int) -> str:
    """Stream a file's sha256, failing closed once its bytes exceed ``max_bytes``.

    Never holds the whole file in memory, and caps the read so a file larger than
    declared (a tamper that would otherwise be caught only after buffering) is
    rejected mid-stream rather than exhausting the process.
    """
    hasher = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK_BYTES):
            read += len(chunk)
            if read > max_bytes:
                raise ContentDeliveryError("content delivery input exceeds the configured size bound")
            hasher.update(chunk)
    return hasher.hexdigest()


def _promote(storage: ObjectStorage, bucket: str, key: str, payload: bytes) -> None:
    """Idempotently promote ``payload`` to the content-addressed ``key``."""
    if storage.object_exists(bucket, key):
        return
    storage.upload_file(io.BytesIO(payload), bucket, key, _OCTET_STREAM)


def _verify_projection_against_inventory(pack_root: Path, inventory: Mapping[str, InventoryEntry]) -> None:
    """Fail closed unless the projection document is itself an inventory artifact.

    The projection controls which pack input each source identity resolves to.
    Launch verification cross-checks the *selected* payload files against the
    pack's associated-artifact inventory (:func:`_verify_input_against_inventory`),
    but that alone does not detect a changed *mapping*: a contributor could edit
    ``delivery/content-projection.json`` after the pack was registered, re-pointing
    a source at a different (still inventory-covered) artifact, while the
    advertised package digest stays unchanged. Requiring the projection
    document's own bytes to match an inventory record makes the mapping itself
    subject to the same whole-pack digest verification every other associated
    artifact already is (ADR-034-R6).
    """
    record = inventory.get(PROJECTION_RELPATH)
    if record is None:
        raise ContentDeliveryError("delivery projection is not in the pack associated-artifact inventory")
    path = Path(pack_root) / PROJECTION_RELPATH
    if path.is_symlink() or not path.is_file():
        raise ContentDeliveryError("pack declares source-backed content but ships no delivery projection")
    if sha256_hex(path.read_bytes()) != record.sha256:
        raise ContentDeliveryError("delivery projection does not match the pack inventory digest")


def _load_pack_projection(pack_root: Path) -> DeliveryProjection:
    """Load + parse the pack's delivery-projection document, fail-closed.

    Called only after :func:`_verify_projection_against_inventory` has already
    confirmed the document's bytes match its inventory record, so the existence
    check here is defense in depth, not the primary guard.
    """
    path = Path(pack_root) / PROJECTION_RELPATH
    if path.is_symlink() or not path.is_file():
        raise ContentDeliveryError("pack declares source-backed content but ships no delivery projection")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContentDeliveryError(f"delivery projection could not be read: {safe_log_value(exc)}") from exc
    return parse_delivery_projection(raw)


def build_inventory_index(pack_root: Path) -> dict[str, InventoryEntry]:
    """Return a pack-relative-path -> ``InventoryEntry`` index from the pack manifest.

    Derived from the canonical associated-artifact manifest, so every entry is a
    real, digest-bound payload file (path + sha256 + size). Fails closed on an
    invalid manifest or an unsupported checksum algorithm.
    """
    from raes_env_packs import PackDigestError, validate_pack_content_manifest

    try:
        manifest = validate_pack_content_manifest(pack_root)
    except PackDigestError as exc:
        raise ContentDeliveryError(f"pack associated-artifact inventory is invalid: {safe_log_value(exc)}") from exc
    index: dict[str, InventoryEntry] = {}
    for artifact in manifest.artifacts.values():
        rel = _uri_to_relpath(artifact.uri)
        checksum = artifact.checksum
        if getattr(checksum, "algorithm", "").lower() != "sha256":
            raise ContentDeliveryError("pack inventory uses an unsupported checksum algorithm")
        index[rel] = InventoryEntry(sha256=checksum.value.lower(), size_bytes=int(artifact.size_bytes))
    return index


def _uri_to_relpath(uri: str) -> str:
    """Resolve a canonical ``raes-environment-pack:`` artifact URI to a pack relpath."""
    parts = urlsplit(uri)
    if parts.scheme != _PACK_URI_SCHEME:
        raise ContentDeliveryError("pack inventory artifact has an unexpected uri scheme")
    rel = unquote(f"{parts.netloc}{parts.path}").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise ContentDeliveryError("pack inventory artifact has an invalid path")
    return rel
