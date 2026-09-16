"""The canonical live-validation package must exercise composition evidence."""

from __future__ import annotations

from pathlib import Path

from raes.parser import parse_sdl
from raes_runtime.manager import RuntimeManager

from shared.raes.content_delivery_prep import DeliveryTarget, prepare_content_delivery
from shared.raes.dispatch_port import ShifterDispatchResult
from shared.raes.runtime_target import create_shifter_backend_target, serialize_provisioning_plan

_SDL_PATH = (
    Path(__file__).resolve().parents[5]
    / "scenario-dev"
    / "shifter-raes-validation"
    / "sdl"
    / "shifter-raes-validation.sdl.yaml"
)
_PACK_ROOT = _SDL_PATH.parents[1]


class _Port:
    request_id = "req-validation-package"

    def realize(self, compiled_plan: dict, participant_access=()) -> ShifterDispatchResult:
        return ShifterDispatchResult(
            request_id=self.request_id,
            accepted=True,
            status="accepted",
            range_id="r1",
        )


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def object_exists(self, bucket: str, key: str) -> bool:
        return key in self.objects

    def upload_file(self, file_obj, bucket: str, key: str, content_type: str = "") -> None:
        self.objects[key] = file_obj.read()


def test_validation_package_compiles_all_composition_resource_kinds() -> None:
    scenario = parse_sdl(_SDL_PATH.read_text(encoding="utf-8"))
    execution = RuntimeManager(create_shifter_backend_target(port=_Port())).plan(scenario)
    serialized = serialize_provisioning_plan(execution.provisioning)

    resource_types = {resource["resource_type"] for resource in serialized["resources"].values()}
    assert {
        "content-placement",
        "account-placement",
        "feature-binding",
    } <= resource_types


def test_validation_package_feature_is_digest_bound_for_guest_delivery() -> None:
    scenario = parse_sdl(_SDL_PATH.read_text(encoding="utf-8"))
    execution = RuntimeManager(create_shifter_backend_target(port=_Port())).plan(scenario)
    serialized = serialize_provisioning_plan(execution.provisioning)
    storage = _Storage()

    bindings = prepare_content_delivery(
        pack_root=_PACK_ROOT,
        serialized_plan=serialized,
        target=DeliveryTarget(
            storage=storage,
            bucket="assets",
            prefix="raes/content",
            max_payload_bytes=1024 * 1024,
        ),
    )

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.resource_type == "feature-binding"
    assert binding.payload_kind == "file"
    assert binding.install_policy == "configuration"
    assert binding.storage_key in storage.objects
