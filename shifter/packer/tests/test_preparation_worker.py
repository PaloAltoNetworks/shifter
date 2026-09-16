"""Standalone phase execution validates private immutable inputs before cloud work."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from shared.operation_envelope import canonical_payload_digest
from shared.preparation_grant import PreparationGrantConfiguration
from tests.shared.raes.test_preparation_contract import manifest_payload, requirement_payload
from tests.shared.raes.test_preparation_inputs import bound_input_fixture
from tests.shared.test_preparation_grant import grant_configuration

from preparation import worker
from preparation.context import context_digest

ROOT = Path(__file__).parents[1] / "preparation"


def envelope(phase="verify-inputs", evidence=None):
    adapter = manifest_payload()
    profile = adapter["specifications"][0]["reference"]["profile"]
    profile["digest"] = "sha256:" + hashlib.sha256((ROOT / "PROFILE.md").read_bytes()).hexdigest()
    spec = adapter["specifications"][0]["reference"]
    spec["specification_id"] = "http-smoke"
    spec["digest"] = context_digest({path.name: path.read_bytes() for path in (ROOT / "contexts/http-smoke").iterdir()})
    requirement = requirement_payload()
    requirement["materialization_specifications"] = [spec]
    requirement["permitted_routes"][0]["mechanism"] = profile
    grant = grant_configuration()
    payload = {
        "protocol": adapter["protocol"],
        "scope_digest": PreparationGrantConfiguration.model_validate(grant).scope_digest,
        "adapter": adapter,
        "manifest_digest": canonical_payload_digest(adapter),
        "grant": grant,
        "grant_digest": canonical_payload_digest(grant),
        "package": {
            "scenario_id": "private-example",
            "package_digest": "sha256:" + "3" * 64,
            "requirement_address": "plan/private-example/web",
            "requirement": requirement,
            "specification_id": "http-smoke",
            "input_bindings": [bound_input_fixture().model_dump(mode="json")],
        },
    }
    payload.update(
        operation_input_digest=canonical_payload_digest(payload),
        operation_id=str(uuid4()),
        phase=phase,
        evidence=evidence or {},
    )
    return {"attempt_id": str(uuid4()), "input_digest": canonical_payload_digest(payload), "input": payload}


def reseal(raw):
    payload = raw["input"]
    base = {
        key: value
        for key, value in payload.items()
        if key not in {"operation_id", "operation_input_digest", "phase", "evidence"}
    }
    payload["operation_input_digest"] = canonical_payload_digest(base)
    raw["input_digest"] = canonical_payload_digest(payload)


@pytest.mark.parametrize("failure", ["digest", "context", "trust"])
def test_invalid_input_never_gets_cloud_credentials(failure):
    raw = envelope()
    if failure == "digest":
        raw["input"]["grant"]["project_id"] = "foreign-project"
    elif failure == "context":
        raw["input"]["package"]["specification_id"] = "missing"
        reseal(raw)
    else:
        raw["input"]["grant"]["trusted_input_bindings"] = {}
        raw["input"]["grant_digest"] = canonical_payload_digest(raw["input"]["grant"])
        reseal(raw)

    def cloud(*args):
        pytest.fail("invalid input received cloud authority")

    result = worker.execute_attempt(raw, ROOT, cloud)
    assert result["status"] == "failed"
    assert result["evidence"] == {}


def test_builder_cannot_run_from_a_declared_input_without_independent_receipt():
    result = worker.execute_attempt(
        envelope("build"), ROOT, lambda *args: pytest.fail("builder ran without measurement")
    )
    assert result["status"] == "failed"
    assert result["failure_code"] == "execution-failed"


def test_digest_valid_context_without_boot_probe_never_gets_cloud_authority(tmp_path):
    raw = envelope()
    root = tmp_path / "preparation"
    context = root / "contexts/http-smoke"
    context.mkdir(parents=True)
    (root / "PROFILE.md").write_bytes((ROOT / "PROFILE.md").read_bytes())
    files = {
        path.name: path.read_bytes()
        for path in (ROOT / "contexts/http-smoke").iterdir()
        if path.name != "verify_boot.py"
    }
    for name, data in files.items():
        (context / name).write_bytes(data)
    # Seal the incomplete context as an otherwise valid installed specification.
    # Digest integrity alone must never make missing execution material usable.
    payload = raw["input"]
    payload["adapter"]["specifications"][0]["reference"]["digest"] = context_digest(files)
    payload["package"]["requirement"]["materialization_specifications"][0]["digest"] = context_digest(files)
    payload["manifest_digest"] = canonical_payload_digest(payload["adapter"])
    reseal(raw)
    result = worker.execute_attempt(raw, root, lambda *args: pytest.fail("incomplete context got cloud authority"))
    assert result["status"] == "failed"
    assert result["evidence"] == {}


def test_profile_oversized_context_is_rejected_before_cloud_authority(tmp_path):
    raw = envelope()
    root = tmp_path / "preparation"
    context = root / "contexts/http-smoke"
    context.mkdir(parents=True)
    (root / "PROFILE.md").write_bytes((ROOT / "PROFILE.md").read_bytes())
    files = {path.name: path.read_bytes() for path in (ROOT / "contexts/http-smoke").iterdir()}
    files["profile-padding.bin"] = b"x" * (96 * 1024)
    for name, data in files.items():
        (context / name).write_bytes(data)
    digest = context_digest(files)
    payload = raw["input"]
    payload["adapter"]["specifications"][0]["reference"]["digest"] = digest
    payload["package"]["requirement"]["materialization_specifications"][0]["digest"] = digest
    payload["manifest_digest"] = canonical_payload_digest(payload["adapter"])
    reseal(raw)

    result = worker.execute_attempt(raw, root, lambda *args: pytest.fail("oversized context got cloud authority"))

    assert result["status"] == "failed"
    assert result["evidence"] == {}


def test_independent_input_scan_returns_only_measured_and_matched_evidence(monkeypatch):
    binding = bound_input_fixture()
    measured = {
        "image_ref": binding.image_ref,
        "image_id": binding.image_id,
        "disk_id": "54321",
        "raw_disk_digest": binding.artifact.digest,
        "size_bytes": binding.size_bytes,
    }
    calls = []

    def scan(api, request, context, *, verify_output):
        calls.append(request)
        assert verify_output is False
        assert context["build.sh"]
        return measured

    monkeypatch.setattr(worker, "scan_image", scan)
    result = worker.execute_attempt(envelope(), ROOT, lambda grant: object())
    assert result["status"] == "succeeded", result
    assert result["evidence"]["observations"] == [{**measured, "input_id": binding.lock.input_id}]
    assert calls[0]["image_id"] == binding.image_id
    measured["raw_disk_digest"] = "sha256:" + "0" * 64
    rejected = worker.execute_attempt(envelope(), ROOT, lambda grant: object())
    assert rejected["status"] == "failed"
    assert rejected["evidence"] == {}
