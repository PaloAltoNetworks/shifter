"""Tests for CMS-side source-backed content delivery preparation (#1564, S2).

Drives ``prepare_content_delivery`` end to end against a real temp pack tree, an
injected ``ObjectStorage`` fake, and injected projection / inventory loaders (so
the resolve -> inventory-verify -> materialize -> content-address -> promote ->
bind pipeline is exercised without standing up a full canonical RAES pack). The
security-critical fail-closed paths (missing projection entry, inventory
mismatch, non-inventory input, path escape, unsupported shape, oversize payload)
each go red if the enforcement is removed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shared.raes.content_delivery import (
    ContentDeliveryError,
    DeliveryProjection,
    DeliveryProjectionEntry,
    sha256_hex,
)
from shared.raes.content_delivery_prep import (
    DeliveryTarget,
    InventoryEntry,
    prepare_content_delivery,
)


class _FakeStorage:
    """In-memory ObjectStorage stand-in recording promotions."""

    def __init__(self, *, existing: set[str] | None = None):
        self.objects: dict[str, bytes] = {}
        self._existing = existing or set()
        self.uploads: list[str] = []

    def object_exists(self, bucket: str, key: str) -> bool:
        return key in self._existing or key in self.objects

    def upload_file(self, file_obj, bucket: str, key: str, content_type: str = "") -> None:
        self.uploads.append(key)
        self.objects[key] = file_obj.read()


def _content_resource(address: str, *, ctype: str, source: object, text: str | None = None) -> dict:
    spec: dict = {"type": ctype}
    if source is not None:
        spec["source"] = source
    if text is not None:
        spec["text"] = text
    if ctype == "file":
        spec["path"] = "/opt/app/" + address
    elif ctype == "directory":
        spec["destination"] = "/opt/app/" + address
    return {
        "address": address,
        "domain": "provisioning",
        "resource_type": "content-placement",
        "payload": {"content_name": address, "target_address": "node.web", "spec": spec},
    }


def _feature_resource(
    address: str,
    *,
    feature_type: str,
    source: object,
    destination: str,
) -> dict:
    return {
        "address": address,
        "domain": "provisioning",
        "resource_type": "feature-binding",
        "payload": {
            "feature_name": address,
            "node_address": "node.web",
            "spec": {
                "template": {
                    "type": feature_type,
                    "source": source,
                    "destination": destination,
                }
            },
        },
    }


def _plan(*resources: dict) -> dict:
    return {
        "kind": "raes.provisioning-plan",
        "resources": {res["address"]: res for res in resources},
    }


def _pack(tmp_path: Path) -> tuple[Path, dict, DeliveryProjection]:
    """Build a temp pack tree + matching inventory + projection."""
    pack = tmp_path / "pack"
    (pack / "assets" / "seed" / "sub").mkdir(parents=True)
    (pack / "assets" / "flag.txt").write_bytes(b"CTF{real-bytes}")
    (pack / "assets" / "seed" / "a.txt").write_bytes(b"aaa")
    (pack / "assets" / "seed" / "sub" / "b.txt").write_bytes(b"bbb")

    def _entry(rel: str) -> tuple[str, InventoryEntry]:
        data = (pack / rel).read_bytes()
        return rel, InventoryEntry(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))

    inventory = dict([_entry("assets/flag.txt"), _entry("assets/seed/a.txt"), _entry("assets/seed/sub/b.txt")])
    projection = DeliveryProjection(
        entries=(
            DeliveryProjectionEntry("flag-pkg", "1.0.0", "file", "", "assets/flag.txt"),
            DeliveryProjectionEntry("seed-tree", "1.0.0", "directory", "", "assets/seed"),
        )
    )
    return pack, inventory, projection


def _prepare(pack, inventory, projection, plan, storage, *, prefix="raes/content", max_bytes=10_000_000):
    target = DeliveryTarget(storage=storage, bucket="assets-bucket", prefix=prefix, max_payload_bytes=max_bytes)
    return prepare_content_delivery(
        pack_root=pack,
        serialized_plan=plan,
        target=target,
        projection_loader=lambda _root: projection,
        inventory_loader=lambda _root: inventory,
    )


def test_no_source_backed_content_returns_empty(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    plan = _plan(_content_resource("inline", ctype="file", source=None, text="hi"))
    storage = _FakeStorage()
    assert _prepare(pack, inventory, projection, plan, storage) == ()
    assert storage.uploads == []


def test_source_backed_file_and_directory_produce_bindings(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    plan = _plan(
        _content_resource("cf.flag", ctype="file", source={"name": "flag-pkg", "version": "1.0.0"}),
        _content_resource("cf.seed", ctype="directory", source={"name": "seed-tree", "version": "1.0.0"}),
        _content_resource("cf.inline", ctype="file", source=None, text="inline"),
    )
    storage = _FakeStorage()
    bindings = _prepare(pack, inventory, projection, plan, storage)

    assert len(bindings) == 2
    by_addr = {b.content_address: b for b in bindings}
    assert set(by_addr) == {"cf.flag", "cf.seed"}

    flag = by_addr["cf.flag"]
    assert flag.sha256 == sha256_hex(b"CTF{real-bytes}")
    assert flag.byte_count == len(b"CTF{real-bytes}")
    assert flag.storage_key == f"raes/content/{flag.sha256[:2]}/{flag.sha256}"
    assert flag.storage_key in storage.objects
    # directory payload is a nonzero deterministic tar
    assert by_addr["cf.seed"].byte_count > 0
    assert len(storage.uploads) == 2


def test_source_backed_feature_artifact_produces_discriminated_v2_binding(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    projection = DeliveryProjection(
        entries=(
            *projection.entries,
            DeliveryProjectionEntry(
                "flag-pkg",
                "1.0.0",
                "file",
                "",
                "assets/flag.txt",
                resource_type="feature-binding",
                feature_type="artifact",
                payload_kind="file",
                install_policy="executable",
            ),
        )
    )
    plan = _plan(
        _feature_resource(
            "provision.feature.agent",
            feature_type="artifact",
            source={"name": "flag-pkg", "version": "1.0.0"},
            destination="/opt/raes/agent",
        )
    )
    bindings = _prepare(pack, inventory, projection, plan, _FakeStorage())
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.binding_version == 2
    assert binding.content_address is None
    assert binding.resource_type == "feature-binding"
    assert binding.resource_address == "provision.feature.agent"
    assert binding.payload_kind == "file"
    assert binding.install_policy == "executable"


def test_promotion_is_idempotent(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    flag_digest = sha256_hex(b"CTF{real-bytes}")
    existing = {f"raes/content/{flag_digest[:2]}/{flag_digest}"}
    plan = _plan(_content_resource("cf.flag", ctype="file", source="flag-pkg"))
    storage = _FakeStorage(existing=existing)
    bindings = _prepare(pack, inventory, projection, plan, storage)
    assert len(bindings) == 1
    assert storage.uploads == []  # already present -> not re-uploaded


def test_source_shorthand_string_resolves(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    plan = _plan(_content_resource("cf.flag", ctype="file", source="flag-pkg"))
    storage = _FakeStorage()
    bindings = _prepare(pack, inventory, projection, plan, storage)
    assert len(bindings) == 1


def test_missing_projection_entry_fails_closed(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    plan = _plan(_content_resource("cf.x", ctype="file", source={"name": "unknown-pkg", "version": "1.0.0"}))
    storage = _FakeStorage()
    with pytest.raises(ContentDeliveryError):
        _prepare(pack, inventory, projection, plan, storage)


def test_input_not_in_inventory_fails_closed(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    inventory.pop("assets/flag.txt")  # projection points at it, inventory does not cover it
    plan = _plan(_content_resource("cf.flag", ctype="file", source="flag-pkg"))
    storage = _FakeStorage()
    with pytest.raises(ContentDeliveryError):
        _prepare(pack, inventory, projection, plan, storage)


def test_inventory_digest_mismatch_fails_closed(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    inventory["assets/flag.txt"] = InventoryEntry(sha256="0" * 64, size_bytes=3)  # tampered claim
    plan = _plan(_content_resource("cf.flag", ctype="file", source="flag-pkg"))
    storage = _FakeStorage()
    with pytest.raises(ContentDeliveryError):
        _prepare(pack, inventory, projection, plan, storage)


def test_directory_file_not_in_inventory_fails_closed(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    inventory.pop("assets/seed/sub/b.txt")  # a file under the delivered tree is uncovered
    plan = _plan(_content_resource("cf.seed", ctype="directory", source="seed-tree"))
    storage = _FakeStorage()
    with pytest.raises(ContentDeliveryError):
        _prepare(pack, inventory, projection, plan, storage)


def test_input_path_escaping_pack_fails_closed(tmp_path: Path):
    pack, inventory, _projection = _pack(tmp_path)
    escaping = DeliveryProjection(
        entries=(DeliveryProjectionEntry("flag-pkg", "1.0.0", "file", "", "assets/flag.txt"),)
    )
    # a projection whose resolved path leaves the pack must fail closed even if
    # the entry parsed; simulate by pointing the loader at a traversing path via
    # a hand-built entry object (bypassing parse guards).
    object.__setattr__(escaping.entries[0], "input_path", "../../etc/passwd")
    plan = _plan(_content_resource("cf.flag", ctype="file", source="flag-pkg"))
    storage = _FakeStorage()
    with pytest.raises(ContentDeliveryError):
        _prepare(pack, inventory, escaping, plan, storage)


def test_unsupported_source_backed_type_fails_closed(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    plan = _plan(_content_resource("cf.ds", ctype="dataset", source={"name": "flag-pkg", "version": "1.0.0"}))
    storage = _FakeStorage()
    with pytest.raises(ContentDeliveryError):
        _prepare(pack, inventory, projection, plan, storage)


def test_oversize_payload_fails_closed(tmp_path: Path):
    # F2: the declared inventory size (metadata) is over the cap -> rejected before
    # any bytes are read.
    pack, inventory, projection = _pack(tmp_path)
    plan = _plan(_content_resource("cf.flag", ctype="file", source="flag-pkg"))
    storage = _FakeStorage()
    with pytest.raises(ContentDeliveryError):
        _prepare(pack, inventory, projection, plan, storage, max_bytes=3)


def test_streaming_hash_caps_input_larger_than_declared(tmp_path: Path):
    # F2: a file whose ACTUAL bytes exceed the cap (even though its declared
    # inventory size is small) is rejected mid-stream, never buffered whole.
    pack, inventory, projection = _pack(tmp_path)
    (pack / "assets" / "flag.txt").write_bytes(b"x" * 500)  # actual >> declared
    inventory["assets/flag.txt"] = InventoryEntry(sha256="0" * 64, size_bytes=5)  # lies small
    plan = _plan(_content_resource("cf.flag", ctype="file", source="flag-pkg"))
    storage = _FakeStorage()
    with pytest.raises(ContentDeliveryError):
        _prepare(pack, inventory, projection, plan, storage, max_bytes=50)


def _write_projection_file(pack: Path, entries: list[dict]) -> Path:
    """Write a real ``delivery/content-projection.json`` document to ``pack``."""
    delivery_dir = pack / "delivery"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    path = delivery_dir / "content-projection.json"
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    return path


_FLAG_PROJECTION_ENTRIES = [
    {
        "source": {"name": "flag-pkg", "version": "1.0.0"},
        "content_type": "file",
        "format": "",
        "input_path": "assets/flag.txt",
    }
]


def test_default_projection_loader_requires_matching_inventory_record(tmp_path: Path):
    """The real (default) projection loader binds the document to an inventory
    record before trusting it -- unlike the tests above, which inject a
    pre-parsed ``DeliveryProjection`` and so never touch this loader."""
    pack, inventory, _projection = _pack(tmp_path)
    proj_path = _write_projection_file(pack, _FLAG_PROJECTION_ENTRIES)
    inventory["delivery/content-projection.json"] = InventoryEntry(
        sha256=hashlib.sha256(proj_path.read_bytes()).hexdigest(), size_bytes=proj_path.stat().st_size
    )
    plan = _plan(_content_resource("cf.flag", ctype="file", source={"name": "flag-pkg", "version": "1.0.0"}))
    target = DeliveryTarget(
        storage=_FakeStorage(), bucket="assets-bucket", prefix="raes/content", max_payload_bytes=10_000_000
    )
    bindings = prepare_content_delivery(
        pack_root=pack,
        serialized_plan=plan,
        target=target,
        inventory_loader=lambda _root: inventory,
    )
    assert len(bindings) == 1


def test_default_projection_loader_fails_closed_when_document_uncovered(tmp_path: Path):
    pack, inventory, _projection = _pack(tmp_path)
    _write_projection_file(pack, _FLAG_PROJECTION_ENTRIES)
    # inventory carries no record at all for delivery/content-projection.json
    plan = _plan(_content_resource("cf.flag", ctype="file", source={"name": "flag-pkg", "version": "1.0.0"}))
    target = DeliveryTarget(
        storage=_FakeStorage(), bucket="assets-bucket", prefix="raes/content", max_payload_bytes=10_000_000
    )
    with pytest.raises(ContentDeliveryError, match="associated-artifact inventory"):
        prepare_content_delivery(
            pack_root=pack,
            serialized_plan=plan,
            target=target,
            inventory_loader=lambda _root: inventory,
        )


def test_default_projection_loader_fails_closed_when_document_altered(tmp_path: Path):
    """A contributor re-pointing the mapping after registration -- the inventory
    record still names an entry, but its digest no longer matches the (edited)
    on-disk document -- must fail closed rather than silently trust the edit."""
    pack, inventory, _projection = _pack(tmp_path)
    _write_projection_file(pack, _FLAG_PROJECTION_ENTRIES)
    inventory["delivery/content-projection.json"] = InventoryEntry(sha256="0" * 64, size_bytes=1)
    plan = _plan(_content_resource("cf.flag", ctype="file", source={"name": "flag-pkg", "version": "1.0.0"}))
    target = DeliveryTarget(
        storage=_FakeStorage(), bucket="assets-bucket", prefix="raes/content", max_payload_bytes=10_000_000
    )
    with pytest.raises(ContentDeliveryError, match="does not match the pack inventory digest"):
        prepare_content_delivery(
            pack_root=pack,
            serialized_plan=plan,
            target=target,
            inventory_loader=lambda _root: inventory,
        )


def test_no_bucket_configured_fails_closed(tmp_path: Path):
    pack, inventory, projection = _pack(tmp_path)
    plan = _plan(_content_resource("cf.flag", ctype="file", source="flag-pkg"))
    target = DeliveryTarget(storage=_FakeStorage(), bucket="", prefix="raes/content", max_payload_bytes=10_000)
    with pytest.raises(ContentDeliveryError):
        prepare_content_delivery(
            pack_root=pack,
            serialized_plan=plan,
            target=target,
            projection_loader=lambda _root: projection,
            inventory_loader=lambda _root: inventory,
        )
