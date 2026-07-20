"""Cross-boundary evidence for source-backed content delivery (#1564, ADR-032-R6).

This is the producer-half cross-boundary proof required to re-declare the coarse
``file`` / ``directory`` capabilities: it authors a source-backed ``file`` AND a
source-backed ``directory`` in a real ACES SDL, compiles it through the upstream
compiler, asserts the Shifter backend *admits* both (the capability gate no
longer rejects them), serializes the plan exactly as the platform persists it,
and then runs the real CMS-side ``prepare_content_delivery`` against a real pack
tree -- proving the producer genuinely materializes, digests, promotes, and binds
each source-backed payload into a byte-free ``DeliveryBinding``.

The consumer half (provisioner parse -> content<->binding gate -> guest transfer
-> in-guest digest readback) is covered by the provisioner delivery tests
(``engine/provisioner/tests/test_aces_content_delivery*``), which meet this half
at the ``DeliveryBinding`` transport contract. The full live-guest proof is the
``run_aces_backend_validation`` cutover gate (docs/architecture/aces-cutover-evidence-1264.md).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from aces_runtime.manager import RuntimeManager
from aces_sdl.parser import parse_sdl

from shared.aces.content_delivery import DeliveryProjection, DeliveryProjectionEntry, sha256_hex
from shared.aces.content_delivery_prep import DeliveryTarget, InventoryEntry, prepare_content_delivery
from shared.aces.dispatch_port import ShifterDispatchResult
from shared.aces.runtime_target import (
    ShifterProvisioner,
    create_shifter_backend_target,
    serialize_provisioning_plan,
)

_SDL = """name: e2e-content-delivery
version: "1.0.0"
nodes:
  web:
    type: vm
    os: linux
    source: base-linux
content:
  flag:
    type: file
    target: web
    path: /opt/flag
    source: flag-pkg
  seed:
    type: directory
    target: web
    destination: /opt/seed
    source: seed-tree
"""


class _Port:
    """Minimal dispatch port; plan()/validate() do not dispatch."""

    request_id = "req-e2e-content"

    def realize(self, compiled_plan: dict) -> ShifterDispatchResult:
        return ShifterDispatchResult(request_id=self.request_id, accepted=True, status="accepted", range_id="r1")


class _FakeStorage:
    """In-memory ObjectStorage stand-in recording content-addressed promotions."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def object_exists(self, bucket: str, key: str) -> bool:
        return key in self.objects

    def upload_file(self, file_obj, bucket: str, key: str, content_type: str = "") -> None:
        self.objects[key] = file_obj.read()


def _real_pack(tmp_path: Path) -> tuple[Path, dict[str, InventoryEntry]]:
    pack = tmp_path / "pack"
    (pack / "assets" / "seed" / "sub").mkdir(parents=True)
    (pack / "assets" / "flag.txt").write_bytes(b"CTF{e2e}")
    (pack / "assets" / "seed" / "a.txt").write_bytes(b"aaa")
    (pack / "assets" / "seed" / "sub" / "b.txt").write_bytes(b"bbb")

    def _inv(rel: str) -> tuple[str, InventoryEntry]:
        data = (pack / rel).read_bytes()
        return rel, InventoryEntry(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))

    inventory = dict([_inv("assets/flag.txt"), _inv("assets/seed/a.txt"), _inv("assets/seed/sub/b.txt")])
    return pack, inventory


def test_source_backed_content_admitted_and_bound_end_to_end(tmp_path: Path):
    # Compile the authored source-backed content through the real ACES compiler.
    scenario = parse_sdl(_SDL)
    execution = RuntimeManager(create_shifter_backend_target(port=_Port())).plan(scenario)
    plan = execution.provisioning

    # Admission: the backend now ACCEPTS source-backed file + directory content
    # (the #1564 re-declaration) -- no unsupported-content-type diagnostic.
    diagnostics = ShifterProvisioner.validate(plan)
    assert not any(d.code == "shifter-provisioner.unsupported-content-type" for d in diagnostics)
    assert not any(d.is_error for d in diagnostics)

    serialized = serialize_provisioning_plan(plan)

    # Producer: real prepare materializes, digests, promotes, and binds both.
    pack, inventory = _real_pack(tmp_path)
    projection = DeliveryProjection(
        entries=(
            DeliveryProjectionEntry("flag-pkg", "*", "file", "", "assets/flag.txt"),
            DeliveryProjectionEntry("seed-tree", "*", "directory", "", "assets/seed"),
        )
    )
    storage = _FakeStorage()
    target = DeliveryTarget(
        storage=storage, bucket="assets-bucket", prefix="aces/content", max_payload_bytes=10_000_000
    )
    bindings = prepare_content_delivery(
        pack_root=pack,
        serialized_plan=serialized,
        target=target,
        projection_loader=lambda _root: projection,
        inventory_loader=lambda _root: inventory,
    )

    assert len(bindings) == 2
    digests = {binding.sha256 for binding in bindings}
    # The source-backed file's exact bytes were materialized + bound.
    assert sha256_hex(b"CTF{e2e}") in digests
    # Both payloads were promoted content-addressed under the configured prefix.
    assert len(storage.objects) == 2
    for binding in bindings:
        assert binding.storage_key == f"aces/content/{binding.sha256[:2]}/{binding.sha256}"
        assert binding.storage_key in storage.objects
        assert binding.byte_count > 0
