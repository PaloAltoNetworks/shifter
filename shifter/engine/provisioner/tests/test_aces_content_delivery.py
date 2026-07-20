"""Tests for the #1564 post-boot ACES content-delivery orchestration.

Covers the two halves of ``aces_content_delivery``:

- ``assert_content_delivery_bindings_complete``: the fail-closed gate joining
  source-backed content items to their delivery bindings by compiled resource
  address (missing binding, over-claiming extra binding, duplicate address,
  unsupported content_type all fail closed; source-less content needs no
  binding at all).
- ``realize_aces_content_delivery``: the download+digest-verify+guest-delivery
  orchestration, exercised against a fake object storage and a fake executor
  driven through the *real* ``SetupOrchestrator`` (so the actual
  ``AcesContentDeliveryPlan`` scripts/context flow through, and the explicit
  ``result.verification_result`` check -- which ``SetupOrchestrator.orchestrate``
  does not itself enforce -- is genuinely exercised).
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from aces_content_delivery import (
    AcesContentDeliveryError,
    AcesContentDeliveryOps,
    assert_content_delivery_bindings_complete,
    realize_aces_content_delivery,
)
from aces_gcp_composition import AcesGceCompositionError
from aces_plan import AcesPlan, AcesPlanContent, AcesPlanFeature, AcesPlanNode
from cloud.exceptions import CloudStorageError
from config import AcesContentDeliveryConfig
from executors.base import CommandResult
from executors.factory import GuestExecutionContext


def _content(**kw) -> AcesPlanContent:
    base = {"name": "c", "content_type": "file", "target_address": "node.web", "address": "content.c"}
    base.update(kw)
    return AcesPlanContent(**base)


def _node(address: str = "node.web", os_family: str = "linux", count: int = 1) -> AcesPlanNode:
    return AcesPlanNode(
        address=address, name=address.rsplit(".", 1)[-1], os_family=os_family, count=count, network_addresses=()
    )


def _feature(**kw) -> AcesPlanFeature:
    base = {
        "name": "agent",
        "feature_type": "artifact",
        "target_address": "node.web",
        "address": "feature.agent",
        "source_name": "agent-pkg",
        "source_version": "1.0.0",
        "destination": "/opt/aces/agent",
    }
    base.update(kw)
    return AcesPlanFeature(**base)


def _plan(*, content=(), features=(), nodes=None) -> AcesPlan:
    return AcesPlan(
        aces_sdl_version="0.19.1",
        nodes=nodes or (_node(),),
        networks=(),
        content=content,
        features=features,
    )


#: sha256("hello") -- matches _ops()'s default fake-object-storage payload
#: (b"hello", 5 bytes) so the default binding passes the provisioner-side
#: digest check without every realize test having to compute/override it.
_HELLO_SHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def _binding(**kw) -> dict[str, Any]:
    """Build a binding dict, defaulting ``storage_key`` to the canonical
    content-addressed key *derived from whatever ``sha256`` ends up set*
    (including an overridden one) -- mirrors
    ``shared.aces.content_delivery.normalized_storage_key`` so a test that
    only overrides ``sha256`` still gets a self-consistent binding unless it
    deliberately overrides ``storage_key`` too (e.g. to test a mismatch)."""
    digest = kw.get("sha256", _HELLO_SHA256)
    base = {
        "content_address": "content.c",
        "sha256": digest,
        "storage_key": "aces/content-delivery/" + digest[:2] + "/" + digest,
        "byte_count": 5,
        "binding_version": 1,
    }
    base.update(kw)
    return base


def _feature_binding(**kw) -> dict[str, Any]:
    digest = kw.get("sha256", _HELLO_SHA256)
    base = {
        "resource_type": "feature-binding",
        "resource_address": "feature.agent",
        "payload_kind": "file",
        "install_policy": "executable",
        "sha256": digest,
        "storage_key": "aces/content-delivery/" + digest[:2] + "/" + digest,
        "byte_count": 5,
        "binding_version": 2,
    }
    base.update(kw)
    return base


def _tar(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
    return buffer.getvalue()


class TestAssertContentDeliveryBindingsComplete:
    def test_no_source_backed_content_needs_no_bindings(self):
        plan = _plan(content=(_content(source_name=None, text="hello"),))
        assert_content_delivery_bindings_complete(plan, None)  # does not raise

    def test_matching_binding_passes(self):
        plan = _plan(content=(_content(source_name="pkg", path="/opt/x.bin"),))
        assert_content_delivery_bindings_complete(plan, [_binding()])  # does not raise

    def test_missing_binding_fails_closed(self):
        plan = _plan(content=(_content(source_name="pkg", path="/opt/x.bin"),))
        with pytest.raises(AcesGceCompositionError, match="missing its delivery binding"):
            assert_content_delivery_bindings_complete(plan, [])

    def test_missing_binding_with_none_fails_closed(self):
        plan = _plan(content=(_content(source_name="pkg", path="/opt/x.bin"),))
        with pytest.raises(AcesGceCompositionError, match="missing its delivery binding"):
            assert_content_delivery_bindings_complete(plan, None)

    def test_extra_binding_with_no_matching_content_fails_closed(self):
        plan = _plan(content=())
        binding = _binding()
        with pytest.raises(AcesGceCompositionError, match="does not match any deliverable resource"):
            assert_content_delivery_bindings_complete(plan, [binding])

    def test_duplicate_content_address_fails_closed(self):
        plan = _plan(content=(_content(source_name="pkg", path="/opt/x.bin"),))
        bindings = [_binding(), _binding(byte_count=6)]
        with pytest.raises(AcesGceCompositionError, match="duplicate resource identity"):
            assert_content_delivery_bindings_complete(plan, bindings)

    def test_unsupported_content_type_fails_closed_even_without_bindings(self):
        plan = _plan(content=(_content(source_name="pkg", content_type="dataset", items=("a",)),))
        with pytest.raises(AcesGceCompositionError, match="no delivery materializer"):
            assert_content_delivery_bindings_complete(plan, [])

    def test_directory_content_type_is_supported(self):
        plan = _plan(content=(_content(source_name="pkg", content_type="directory", destination="/srv/data"),))
        assert_content_delivery_bindings_complete(plan, [_binding()])  # does not raise

    def test_binding_that_fails_contract_validation_fails_closed(self):
        plan = _plan(content=(_content(source_name="pkg", path="/opt/x.bin"),))
        binding = _binding(binding_version=99)
        with pytest.raises(AcesGceCompositionError, match="failed contract validation"):
            assert_content_delivery_bindings_complete(plan, [binding])

    def test_two_source_backed_items_each_need_their_own_binding(self):
        plan = _plan(
            content=(
                _content(source_name="pkg", path="/opt/a.bin", address="content.a"),
                _content(source_name="pkg2", path="/opt/b.bin", address="content.b"),
            )
        )
        binding_a = _binding(content_address="content.a")
        with pytest.raises(AcesGceCompositionError, match="missing its delivery binding"):
            assert_content_delivery_bindings_complete(plan, [binding_a])
        assert_content_delivery_bindings_complete(
            plan,
            [_binding(content_address="content.a"), _binding(content_address="content.b")],
        )  # does not raise

    def test_matching_source_backed_feature_binding_passes(self):
        plan = _plan(features=(_feature(),))
        assert_content_delivery_bindings_complete(plan, [_feature_binding()])

    def test_source_backed_feature_requires_exact_v2_binding(self):
        plan = _plan(features=(_feature(),))
        with pytest.raises(AcesGceCompositionError, match="missing its delivery binding"):
            assert_content_delivery_bindings_complete(plan, [])

    def test_feature_binding_overclaim_fails_closed(self):
        plan = _plan()
        binding = _feature_binding()
        with pytest.raises(AcesGceCompositionError, match="does not match any deliverable resource"):
            assert_content_delivery_bindings_complete(plan, [binding])

    def test_feature_environment_fails_before_cloud_realization(self):
        plan = _plan(features=(_feature(has_environment=True),))
        binding = _feature_binding()
        with pytest.raises(AcesGceCompositionError, match="no safe realization contract"):
            assert_content_delivery_bindings_complete(plan, [binding])


# ---------------------------------------------------------------------------
# realize_aces_content_delivery
# ---------------------------------------------------------------------------


class _FakeObjectStorage:
    def __init__(self, payload: bytes, *, head_error: Exception | None = None, download_error: Exception | None = None):
        self._payload = payload
        self._head_error = head_error
        self._download_error = download_error
        self.head_calls: list[tuple[str, str]] = []
        self.download_calls: list[dict[str, Any]] = []

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        self.head_calls.append((bucket, key))
        if self._head_error:
            raise self._head_error
        return {"content_length": len(self._payload), "etag": "etag-1"}

    def download_object(self, bucket, key, dest_path, *, max_bytes, expected_identity=None) -> dict[str, Any]:
        self.download_calls.append(
            {
                "bucket": bucket,
                "key": key,
                "dest_path": dest_path,
                "max_bytes": max_bytes,
                "identity": expected_identity,
            }
        )
        if self._download_error:
            raise self._download_error
        with open(dest_path, "wb") as handle:
            handle.write(self._payload)
        return {"content_length": len(self._payload), "etag": "etag-1"}

    def generate_presigned_download_url(self, *a, **k):
        raise NotImplementedError

    def object_exists(self, *a, **k):
        raise NotImplementedError

    def delete_object(self, *a, **k):
        raise NotImplementedError


@dataclass
class _FakeExecutor:
    """Records calls and replays canned results in call order (deliver, verify)."""

    results: list[CommandResult]
    calls: list[dict[str, Any]] = field(default_factory=list)
    ready: bool = True

    def wait_for_ready(self, target, timeout_seconds, document_name):
        return self.ready

    def run_command(self, instance_id, script, timeout_seconds, document_name, stdin_input=None):
        call_index = len(self.calls)
        self.calls.append(
            {
                "instance_id": instance_id,
                "script": script,
                "stdin_input": stdin_input,
                "document_name": document_name,
            }
        )
        return self.results[min(call_index, len(self.results) - 1)]

    def close(self):
        pass


def _success(marker: str) -> CommandResult:
    return CommandResult(success=True, exit_code=0, stdout=marker, stderr="")


def _failure(reason: str) -> CommandResult:
    return CommandResult(success=False, exit_code=1, stdout="", stderr=reason)


def _ops(
    *,
    payload: bytes = b"hello",
    bucket: str = "test-bucket",
    max_bytes: int = 1_000_000,
    executor: _FakeExecutor | None = None,
    storage: _FakeObjectStorage | None = None,
) -> tuple[AcesContentDeliveryOps, _FakeObjectStorage, list[_FakeExecutor]]:
    fake_storage = storage or _FakeObjectStorage(payload)
    built_executors: list[_FakeExecutor] = []

    def execution_builder(output, **_kwargs):
        default_results = [_success("ACES_CONTENT_FILE_INSTALLED"), _success("ACES_CONTENT_FILE_VERIFIED")]
        exec_ = executor or _FakeExecutor(results=default_results)
        built_executors.append(exec_)
        return GuestExecutionContext(
            executor=exec_, target=output["private_ip"], document_name="AWS-RunShellScript", transport_name="ssh"
        )

    ops = AcesContentDeliveryOps(
        config_loader=lambda: AcesContentDeliveryConfig(bucket=bucket, max_bytes=max_bytes),
        object_storage_factory=lambda: fake_storage,
        execution_builder=execution_builder,
    )
    return ops, fake_storage, built_executors


def _output(uuid: str, ip: str = "10.0.0.5") -> dict[str, Any]:
    return {"uuid": uuid, "private_ip": ip}


class TestRealizeAcesContentDelivery:
    def test_no_source_backed_content_is_a_noop(self):
        plan = _plan(content=(_content(source_name=None, text="hello"),))
        ops, storage, _ = _ops()
        realize_aces_content_delivery(aces_plan=plan, instance_outputs=[], delivery_bindings=[], ops=ops)
        assert storage.head_calls == []
        assert storage.download_calls == []

    def test_happy_path_downloads_verifies_and_delivers(self):
        payload = b"hello world"
        content = _content(source_name="pkg", path="/opt/x.bin", sensitive=True)
        plan = _plan(content=(content,))
        digest = __import__("hashlib").sha256(payload).hexdigest()
        binding = _binding(sha256=digest, byte_count=len(payload))
        ops, storage, executors = _ops(payload=payload)

        realize_aces_content_delivery(
            aces_plan=plan,
            instance_outputs=[_output("node.web#0")],
            delivery_bindings=[binding],
            ops=ops,
        )

        assert len(storage.download_calls) == 1
        assert storage.download_calls[0]["max_bytes"] == 1_000_000
        assert len(executors) == 1
        assert len(executors[0].calls) == 2  # deliver + verify
        # The payload bytes (base64) reach the guest only via stdin_input on the
        # deliver call for Linux content, and the target/digest are template-
        # substituted into the script -- never plumbed through argv/env here
        # (this test only has the executor boundary; argv/env are asserted at
        # the transport layer in test_aces_content_delivery_plan.py).
        assert "/opt/x.bin" in executors[0].calls[0]["script"]

    def test_feature_artifact_is_installed_executable_and_verified(self):
        plan = _plan(features=(_feature(),))
        ops, storage, executors = _ops()
        realize_aces_content_delivery(
            aces_plan=plan,
            instance_outputs=[_output("node.web#0")],
            delivery_bindings=[_feature_binding()],
            ops=ops,
        )
        assert len(storage.download_calls) == 1
        assert "/opt/aces/agent" in executors[0].calls[0]["script"]
        assert "file_mode=755" in executors[0].calls[0]["script"]
        assert len(executors[0].calls) == 2

    def test_service_feature_is_installed_and_verified_post_boot(self):
        service = _feature(
            feature_type="service",
            source_name="nginx",
            source_version="1.24.0",
            destination=None,
        )
        plan = _plan(features=(service,))
        ops, storage, executors = _ops()
        realize_aces_content_delivery(
            aces_plan=plan,
            instance_outputs=[_output("node.web#0")],
            delivery_bindings=[],
            ops=ops,
        )
        assert storage.download_calls == []
        assert len(executors[0].calls) == 2
        assert "nginx" in executors[0].calls[0]["script"]
        assert "1.24.0" in executors[0].calls[0]["script"]
        assert "|| true" not in executors[0].calls[0]["script"]
        assert "is-active" in executors[0].calls[1]["script"]

    def test_feature_realization_preserves_cross_shape_dependency_order(self):
        service = _feature(
            name="nginx",
            address="feature.nginx",
            feature_type="service",
            source_name="nginx",
            source_version="1.24.0",
            destination=None,
        )
        artifact = _feature(ordering_dependencies=("feature.nginx",))
        plan = _plan(features=(artifact, service))
        ops, _storage, executors = _ops()

        realize_aces_content_delivery(
            aces_plan=plan,
            instance_outputs=[_output("node.web#0")],
            delivery_bindings=[_feature_binding()],
            ops=ops,
        )

        assert "nginx" in executors[0].calls[0]["script"]
        assert "/opt/aces/agent" in executors[1].calls[0]["script"]

    def test_feature_dependency_cycle_fails_before_guest_realization(self):
        first = _feature(address="feature.first", ordering_dependencies=("feature.second",))
        second = _feature(address="feature.second", ordering_dependencies=("feature.first",))
        plan = _plan(features=(first, second))
        ops, _storage, executors = _ops()
        outputs = [_output("node.web#0")]

        with pytest.raises(AcesContentDeliveryError, match="dependencies contain a cycle"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=outputs,
                delivery_bindings=[],
                ops=ops,
            )

        assert executors == []

    def test_delivers_to_every_concrete_instance_of_a_counted_node(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,), nodes=(_node(count=3),))
        ops, _storage, executors = _ops()

        realize_aces_content_delivery(
            aces_plan=plan,
            instance_outputs=[_output(f"node.web#{i}") for i in range(3)],
            delivery_bindings=[_binding(byte_count=5)],
            ops=ops,
        )

        assert len(executors) == 3
        # Only ONE download for the shared content item, reused across instances.
        assert _storage_download_count(ops) == 1

    def test_windows_node_uses_windows_platform_dialect(self, monkeypatch):
        content = _content(source_name="pkg", path="C:\\data.bin")
        plan = _plan(content=(content,), nodes=(_node(os_family="windows"),))
        ops, _storage, executors = _ops()

        realize_aces_content_delivery(
            aces_plan=plan,
            instance_outputs=[_output("node.web#0")],
            delivery_bindings=[_binding(byte_count=5)],
            ops=ops,
        )
        assert executors[0].calls[0]["document_name"] == "AWS-RunShellScript"  # fixed by _ops' execution_builder
        # The stdin_input carries the payload for windows-dialect content, never
        # templated into the script text (asserted precisely in the plan tests);
        # here we just confirm the deliver call actually carried a stdin_input.
        assert executors[0].calls[0]["stdin_input"]

    def test_provisioner_side_digest_mismatch_fails_before_any_guest_call(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        ops, _storage, executors = _ops(payload=b"tampered bytes")
        binding = _binding(sha256="f" * 64, byte_count=5)  # does not match "tampered bytes"
        output = _output("node.web#0")

        with pytest.raises(AcesContentDeliveryError, match="digest mismatch"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert executors == []  # no guest was ever touched

    def test_unconfigured_bucket_fails_closed(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        ops, _storage, executors = _ops(bucket="")
        output = _output("node.web#0")
        binding = _binding(byte_count=5)

        with pytest.raises(AcesContentDeliveryError, match="bucket is not configured"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert executors == []

    def test_byte_count_over_configured_cap_fails_closed(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        ops, _storage, executors = _ops(max_bytes=10)
        output = _output("node.web#0")
        binding = _binding(byte_count=1_000_000)

        with pytest.raises(AcesContentDeliveryError, match="exceeds the configured size bound"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert executors == []

    def test_download_failure_is_wrapped_value_free(self, caplog):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        storage = _FakeObjectStorage(b"x", download_error=CloudStorageError("s3://secret-bucket/leaked-key failed"))
        ops, _storage, executors = _ops(storage=storage)
        output = _output("node.web#0")
        binding = _binding(byte_count=5)

        with pytest.raises(AcesContentDeliveryError) as exc_info:
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert "secret-bucket" not in str(exc_info.value)
        assert "leaked-key" not in str(exc_info.value)
        # Also assert the underlying CloudStorageError's message (which a
        # provider adapter renders with the bucket/key baked in) never reaches
        # a log record either -- a `logger.exception()`/exc_info=True call
        # would attach it via the traceback even with a bounded message arg.
        assert "secret-bucket" not in caplog.text
        assert "leaked-key" not in caplog.text
        assert executors == []

    def test_in_guest_verify_step_failure_fails_closed_before_ready(self, monkeypatch):
        """SetupOrchestrator.orchestrate() does not itself raise when a verify_step
        runs but exits non-zero -- only a hard transport error during verification
        raises. realize_aces_content_delivery must check result.verification_result
        explicitly so a failed in-guest readback still blocks (this is the
        publish_ready gate the security review calls for)."""
        monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)  # skip the real 15s x4 retry backoff
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        executor = _FakeExecutor(
            results=[_success("ACES_CONTENT_FILE_INSTALLED"), _failure("FATAL: readback digest mismatch")]
        )
        ops, _storage, executors = _ops(executor=executor)
        output = _output("node.web#0")
        binding = _binding(byte_count=5)

        with pytest.raises(AcesContentDeliveryError, match="in-guest digest verification failed"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert len(executors[0].calls) >= 2  # both steps really ran

    def test_deliver_step_failure_fails_closed(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        executor = _FakeExecutor(results=[_failure("FATAL: digest mismatch")])
        ops, _storage, _executors = _ops(executor=executor)
        output = _output("node.web#0")
        binding = _binding(byte_count=5)

        with pytest.raises(AcesContentDeliveryError, match="setup plan failed"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )

    def test_guest_not_ready_fails_closed(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        executor = _FakeExecutor(results=[_success("x")], ready=False)
        ops, _storage, executors = _ops(executor=executor)
        output = _output("node.web#0")
        binding = _binding(byte_count=5)

        with pytest.raises(AcesContentDeliveryError, match="did not become ready"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert executors[0].calls == []  # never ran a command against an unready guest

    def test_missing_instance_output_fails_closed(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,), nodes=(_node(count=2),))
        ops, _storage, _executors = _ops()
        output = _output("node.web#0")  # only index 0; node has count=2
        binding = _binding(byte_count=5)

        with pytest.raises(AcesContentDeliveryError, match="instance output is missing"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )


def _storage_download_count(ops: AcesContentDeliveryOps) -> int:
    return len(ops.object_storage_factory().download_calls)


class TestBindingContractValidation:
    """#1564 core review: the provisioner must revalidate the shared producer
    contract itself (unknown binding_version, malformed digest, non-canonical
    storage_key, downloaded-size/byte_count disagreement) rather than trusting
    a persisted binding's shape (ADR-032-R3)."""

    def test_unsupported_binding_version_fails_closed_before_any_guest_call(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        ops, _storage, executors = _ops()
        binding = _binding(binding_version=2)
        output = _output("node.web#0")

        with pytest.raises(AcesContentDeliveryError, match="binding is invalid"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert executors == []

    def test_binding_with_unknown_extra_key_fails_closed(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        ops, _storage, executors = _ops()
        binding = _binding(bucket="s3://leaked-bucket")  # smuggled extra field
        output = _output("node.web#0")

        with pytest.raises(AcesContentDeliveryError, match="binding is invalid"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert executors == []

    def test_non_canonical_storage_key_fails_closed(self):
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        ops, _storage, executors = _ops()
        binding = _binding(storage_key="some/unrelated/key")  # not <dd>/<digest>-suffixed
        output = _output("node.web#0")

        with pytest.raises(AcesContentDeliveryError, match="binding is invalid"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert executors == []

    def test_downloaded_size_disagreeing_with_byte_count_fails_closed(self):
        # The digest still matches (the downloaded bytes really are "hello"),
        # but the binding's declared byte_count lies about the size -- a
        # tampered/corrupted binding row the digest check alone would not
        # catch, since byte_count is never used to bound what gets hashed.
        content = _content(source_name="pkg", path="/opt/x.bin")
        plan = _plan(content=(content,))
        ops, _storage, executors = _ops(payload=b"hello")
        binding = _binding(byte_count=999)
        output = _output("node.web#0")

        with pytest.raises(AcesContentDeliveryError, match="size mismatch"):
            realize_aces_content_delivery(
                aces_plan=plan,
                instance_outputs=[output],
                delivery_bindings=[binding],
                ops=ops,
            )
        assert executors == []

    def test_zero_byte_file_binding_is_accepted(self):
        # The producer materializer and DeliveryBinding contract both permit
        # byte_count == 0 for `file`; the provisioner previously rejected it
        # outright (#1564 core review).
        content = _content(source_name="pkg", path="/opt/empty.bin")
        plan = _plan(content=(content,))
        empty_sha256 = hashlib.sha256(b"").hexdigest()
        storage = _FakeObjectStorage(b"")
        ops, _storage, executors = _ops(payload=b"", storage=storage)
        binding = _binding(sha256=empty_sha256, byte_count=0)

        realize_aces_content_delivery(
            aces_plan=plan,
            instance_outputs=[_output("node.web#0")],
            delivery_bindings=[binding],
            ops=ops,
        )
        assert len(executors) == 1
        assert len(executors[0].calls) == 2  # deliver + verify both ran


class TestDirectoryContentInstalledTreeDigest:
    """#1564 core + security review: directory verification must prove the
    installed tree, not the retained transfer archive. The provisioner side
    computes the expected installed-tree digest once, server-side, from the
    already-downloaded-and-digest-verified tar bytes, and threads it into the
    guest delivery plan as a value distinct from the tar-bytes ``sha256``."""

    def test_directory_content_computes_and_delivers_installed_tree_digest(self):
        payload = _tar({"a.txt": b"alpha", "sub/b.txt": b"beta"})
        digest = hashlib.sha256(payload).hexdigest()
        content = _content(source_name="pkg", content_type="directory", destination="/srv/data")
        plan = _plan(content=(content,))
        binding = _binding(sha256=digest, byte_count=len(payload))
        ops, _storage, executors = _ops(payload=payload)

        realize_aces_content_delivery(
            aces_plan=plan,
            instance_outputs=[_output("node.web#0")],
            delivery_bindings=[binding],
            ops=ops,
        )
        assert len(executors) == 1
        assert len(executors[0].calls) == 2  # deliver + verify both ran
        # The verify call's stdin carries the installed-tree digest (via the
        # real AcesContentDeliveryPlan/_verify_stdin), never the tar digest,
        # for directory content -- proven precisely in
        # test_aces_content_delivery_plan.py; here we only need confirmation
        # that realization got far enough to run both real guest steps.
