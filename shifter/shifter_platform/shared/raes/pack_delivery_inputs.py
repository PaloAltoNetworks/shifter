"""Pack-side verification of source-backed delivery inputs (ADR-034-R6, ADR-032-R9).

Resolves a projected pack input, and proves it and the projection document are
artifacts of the pack's digest-bound associated-artifact inventory before any
bytes are delivered. Reads are streamed and bounded by each record's exact
declared size; there is no fixed payload cap.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from shared.log_sanitize import safe_log_value
from shared.raes.content_delivery import ContentDeliveryError, DeliveryProjection, parse_delivery_projection, sha256_hex

__all__ = [
    "PROJECTION_RELPATH",
    "InventoryEntry",
    "build_inventory_index",
    "load_pack_projection",
    "resolve_pack_input",
    "verify_input_against_inventory",
    "verify_projection_against_inventory",
]

#: Pack-relative location of the author-declared delivery projection document.
PROJECTION_RELPATH = "delivery/content-projection.json"
_PACK_URI_SCHEME = "raes-environment-pack"
_READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class InventoryEntry:
    """One associated-artifact inventory record: expected digest + declared size."""

    sha256: str
    size_bytes: int


def resolve_pack_input(pack_root: Path, input_path: str) -> Path:
    """Resolve a pack-relative input path, fail-closed on escape or absence."""
    root = Path(pack_root).resolve()
    candidate = (root / input_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ContentDeliveryError("content delivery input escapes the pack root")
    if candidate.is_symlink() or not candidate.exists():
        raise ContentDeliveryError("content delivery input does not exist in the pack")
    return candidate


def verify_input_against_inventory(
    pack_root: Path,
    input_abs: Path,
    content_type: str,
    inventory: Mapping[str, InventoryEntry],
) -> list[tuple[Path, InventoryEntry]]:
    """Fail closed unless every delivered file is an inventory-matching pack file.

    Each file's digest is streamed and its read is bounded by the inventory's
    exact declared size, so a tampered, larger-than-declared input is rejected
    mid-stream without buffering it (ADR-032-R9: the inventory's exact sizes are
    the bound, not a fixed cap). Returns each file paired with its record.
    """
    root = Path(pack_root).resolve()
    files = _deliverable_files(input_abs, content_type)
    records = _matched_inventory_records(files, root, inventory)
    for path, record in records:
        if _sha256_file(path, record.size_bytes) != record.sha256:
            raise ContentDeliveryError("content delivery input does not match the pack inventory digest")
    return records


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
    files: list[Path], root: Path, inventory: Mapping[str, InventoryEntry]
) -> list[tuple[Path, InventoryEntry]]:
    """Return each file paired with its inventory record.

    Fails closed on a non-regular file or an uninventoried file before any
    bytes are read (the digest itself is checked separately, in
    :func:`_sha256_file`).
    """
    records: list[tuple[Path, InventoryEntry]] = []
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ContentDeliveryError("content delivery input contains a non-regular file")
        rel = path.relative_to(root).as_posix()
        record = inventory.get(rel)
        if record is None:
            raise ContentDeliveryError("content delivery input is not in the pack associated-artifact inventory")
        records.append((path, record))
    return records


def _sha256_file(path: Path, declared_bytes: int) -> str:
    """Stream a file's sha256, failing closed once it exceeds its declared size.

    Never holds the whole file in memory, and stops reading as soon as the file
    proves larger than its inventory record (a tamper that would otherwise be
    caught only after reading it all).
    """
    hasher = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK_BYTES):
            read += len(chunk)
            if read > declared_bytes:
                raise ContentDeliveryError("content delivery input does not match the pack inventory digest")
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_projection_against_inventory(pack_root: Path, inventory: Mapping[str, InventoryEntry]) -> None:
    """Fail closed unless the projection document is itself an inventory artifact.

    The projection controls which pack input each source identity resolves to.
    Launch verification cross-checks the *selected* payload files against the
    pack's associated-artifact inventory (:func:`verify_input_against_inventory`),
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


def load_pack_projection(pack_root: Path) -> DeliveryProjection:
    """Load + parse the pack's delivery-projection document, fail-closed.

    Called only after :func:`verify_projection_against_inventory` has already
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
