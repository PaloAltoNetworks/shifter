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

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from shared.raes.content_delivery import (
    FEATURE_BINDING_VERSION,
    ContentDeliveryError,
    DeliveryBinding,
    DeliveryProjection,
    normalized_storage_key,
)
from shared.raes.content_payload import PayloadSource, measure, promote
from shared.raes.pack_delivery_inputs import (
    PROJECTION_RELPATH,
    InventoryEntry,
    build_inventory_index,
    load_pack_projection,
    resolve_pack_input,
    verify_input_against_inventory,
    verify_projection_against_inventory,
)

if TYPE_CHECKING:
    from shared.cloud.types import ObjectStorage

logger = logging.getLogger(__name__)

#: Pack-relative location of the author-declared delivery projection document.
_CONTENT_PLACEMENT_RESOURCE_TYPE = "content-placement"
_FEATURE_BINDING_RESOURCE_TYPE = "feature-binding"
#: Streaming read chunk for size-gated digesting (never buffers a whole file).

__all__ = [
    "PROJECTION_RELPATH",
    "ContentRef",
    "DeliveryTarget",
    "InventoryEntry",
    "has_source_backed_content",
    "pack_projects_feature",
    "prepare_content_delivery",
]


def has_source_backed_content(serialized_plan: Mapping[str, object]) -> bool:
    """Return True if the plan carries any source-backed content placement.

    Cheap, side-effect-free precheck so callers can skip object-storage / pack
    resolution entirely for the common no-source-backed-content plan.
    """
    return bool(_source_backed_content_refs(serialized_plan))


@dataclass(frozen=True)
class ContentRef:
    """A source-backed content-placement extracted from the serialized plan."""

    address: str
    source_name: str
    source_version: str
    content_type: str
    content_format: str
    resource_type: str = _CONTENT_PLACEMENT_RESOURCE_TYPE
    feature_type: str = ""
    install_policy: str = ""
    # Compiled node address a feature binds to (feature-binding refs only).
    target_address: str = ""


@dataclass(frozen=True)
class DeliveryTarget:
    """Where prepared content-delivery payloads are promoted to.

    Bundles the object-storage boundary and the destination bucket/prefix that
    :func:`prepare_content_delivery` needs to promote each source-backed content
    resource (ADR-032-R3, ADR-034-R6). There is no payload-size setting: payloads
    stream with constant memory and are bounded by the pack inventory's exact
    sizes (ADR-032-R9).
    """

    storage: ObjectStorage
    bucket: str
    prefix: str


def prepare_content_delivery(
    *,
    pack_root: Path | None,
    serialized_plan: Mapping[str, object],
    target: DeliveryTarget,
    projection_loader: Callable[[Path], DeliveryProjection] | None = None,
    inventory_loader: Callable[[Path], dict[str, InventoryEntry]] | None = None,
    acquire_feature: Callable[[ContentRef], DeliveryBinding] | None = None,
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

    A feature source the pack does not project is never carried by the pack: it
    resolves through ``acquire_feature`` to a backend-owned artifact acquired by a
    platform recipe (ADR-034-R11). Without a resolver such a source fails closed.
    """
    refs = _source_backed_content_refs(serialized_plan)
    if not refs:
        return ()
    _require_bucket(target)
    if not _uses_pack_projection(refs, pack_root, projection_loader) or pack_root is None:
        return tuple(_acquired(ref, acquire_feature) for ref in refs)
    inventory = (inventory_loader or build_inventory_index)(pack_root)
    projection = _projection_for(pack_root, inventory, projection_loader)
    return tuple(
        _prepare_one(ref, pack_root, projection, inventory, target)
        if _pack_carries(ref, projection)
        else _acquired(ref, acquire_feature)
        for ref in refs
    )


def _require_bucket(target: DeliveryTarget) -> None:
    """Fail closed when no delivery bucket is configured."""
    if not isinstance(target.bucket, str) or not target.bucket.strip():
        raise ContentDeliveryError("content delivery bucket is not configured")


def _uses_pack_projection(
    refs: list[ContentRef], pack_root: Path | None, projection_loader: Callable[[Path], DeliveryProjection] | None
) -> bool:
    """Whether the pack projects content; content placements require that it does."""
    pack_projects = _pack_projection_present(pack_root) or projection_loader is not None
    if not pack_projects and any(ref.resource_type != _FEATURE_BINDING_RESOURCE_TYPE for ref in refs):
        raise ContentDeliveryError("pack root is unavailable for source-backed content delivery")
    return pack_projects


def _projection_for(
    pack_root: Path,
    inventory: Mapping[str, InventoryEntry],
    projection_loader: Callable[[Path], DeliveryProjection] | None,
) -> DeliveryProjection:
    """The pack's delivery projection, inventory-verified when read from the pack.

    Only the real, file-reading default loader needs the inventory cross-check:
    it is the projection *document's own bytes* that must be an
    inventory-covered artifact (ADR-034-R6), not whatever a caller's injected
    loader hands back (e.g. tests exercising resolution/materialize behavior
    against a canned DeliveryProjection with no on-disk document).
    """
    if projection_loader is not None:
        return projection_loader(pack_root)
    verify_projection_against_inventory(pack_root, inventory)
    return load_pack_projection(pack_root)


def _pack_carries(ref: ContentRef, projection: DeliveryProjection) -> bool:
    """Content placements always come from the pack; a feature only when projected."""
    return ref.resource_type != _FEATURE_BINDING_RESOURCE_TYPE or projection.has_feature(
        source_name=ref.source_name, source_version=ref.source_version, feature_type=ref.feature_type
    )


def pack_projects_feature(pack_root: Path, *, source_name: str, source_version: str, feature_type: str) -> bool:
    """Whether the pack's verified projection carries this exact feature source.

    The projection document is checked against the pack's associated-artifact
    inventory first, exactly as launch does (ADR-034-R6).
    """
    if not _pack_projection_present(pack_root):
        return False
    verify_projection_against_inventory(pack_root, build_inventory_index(pack_root))
    return load_pack_projection(pack_root).has_feature(
        source_name=source_name, source_version=source_version, feature_type=feature_type
    )


def _pack_projection_present(pack_root: Path | None) -> bool:
    """Whether the pack ships a delivery projection document."""
    return pack_root is not None and (Path(pack_root) / PROJECTION_RELPATH).is_file()


def _acquired(ref: ContentRef, acquire_feature: Callable[[ContentRef], DeliveryBinding] | None) -> DeliveryBinding:
    """Resolve a feature the pack does not carry to a recipe-acquired artifact."""
    if acquire_feature is None:
        raise ContentDeliveryError(f"no delivery source for feature '{ref.source_name}' ({ref.feature_type})")
    binding = acquire_feature(ref)
    if binding.resource_type != _FEATURE_BINDING_RESOURCE_TYPE or binding.resource_address != ref.address:
        raise ContentDeliveryError("acquired feature binding does not match its plan resource")
    return binding


def _prepare_one(
    ref: ContentRef,
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
    input_abs = resolve_pack_input(pack_root, entry.input_path)
    records = verify_input_against_inventory(pack_root, input_abs, payload_kind, inventory)
    source = PayloadSource(payload_kind, content_format, input_abs)
    # A file payload is the verified pack file verbatim, so its inventory digest
    # names it; a directory's tar is measured by streaming it once.
    digest, byte_count = (records[0][1].sha256, input_abs.stat().st_size) if payload_kind == "file" else measure(source)
    key = normalized_storage_key(target.prefix, digest)
    promote(target.storage, target.bucket, key, source, digest, byte_count)
    if ref.resource_type == _FEATURE_BINDING_RESOURCE_TYPE:
        return DeliveryBinding(
            content_address=None,
            sha256=digest,
            storage_key=key,
            byte_count=byte_count,
            binding_version=FEATURE_BINDING_VERSION,
            resource_type=_FEATURE_BINDING_RESOURCE_TYPE,
            resource_address=ref.address,
            payload_kind=payload_kind,
            install_policy=entry.install_policy,
        )
    return DeliveryBinding(content_address=ref.address, sha256=digest, storage_key=key, byte_count=byte_count)


def _source_backed_content_refs(serialized_plan: Mapping[str, object]) -> list[ContentRef]:
    """Extract source-backed content-placement resources from the serialized plan.

    Inline (``text``) files and source-less directories carry no ``source`` and
    are realized by the existing guest bootstrap, not delivered, so they are
    skipped here. A malformed source (present but with no name) fails closed.
    """
    resources = serialized_plan.get("resources") if isinstance(serialized_plan, Mapping) else None
    if not isinstance(resources, Mapping):
        return []
    refs: list[ContentRef] = []
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


def _feature_ref_from_resource(address: object, resource: object) -> ContentRef | None:
    """Return one source-backed artifact/configuration delivery reference."""
    resolved = _feature_template_from_resource(address, resource)
    if resolved is None:
        return None
    template, resource_address = resolved
    payload = resource.get("payload") if isinstance(resource, Mapping) else None
    target = ""
    if isinstance(payload, Mapping):
        target = str(payload.get("node_address") or payload.get("node_name") or "")
    feature_type = template.get("type")
    feature_type = feature_type.lower() if isinstance(feature_type, str) else ""
    if feature_type == "service":
        return None
    if feature_type not in {"artifact", "configuration"}:
        raise ContentDeliveryError("feature binding has no delivery realization")
    name, version = _parse_source(template.get("source"))
    if not name:
        raise ContentDeliveryError("source-backed feature has an unresolvable source name")
    return ContentRef(
        address=resource_address,
        source_name=name,
        source_version=version,
        content_type="file",
        content_format="",
        resource_type=_FEATURE_BINDING_RESOURCE_TYPE,
        feature_type=feature_type,
        install_policy="",
        target_address=target,
    )


def _content_ref_from_resource(address: object, resource: object) -> ContentRef | None:
    """Return the ``ContentRef`` for one plan resource, or None if not deliverable.

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
    return ContentRef(
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
