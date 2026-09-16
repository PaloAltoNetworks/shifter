"""Post-boot delivery of source-backed RAES guest content (#1564, ADR-032-R3).

While the compiled RAES plan's ``content-placement`` resources are realized by
``raes_gcp_composition`` for everything the boot-time bootstrap can safely bake
in (inline ``text`` files, source-less directories), a *source-backed*
``file``/``directory`` is deliberately excluded from that bootstrap: its bytes
never touch GCE instance metadata. Instead the CMS side promotes the
materialized payload content-addressed to object storage and hands the engine
a byte-free ``DeliveryBinding`` (``content_address`` + ``sha256`` +
``storage_key`` + ``byte_count``, never a bucket, URL, or credential) that
rides beside the serialized plan. This module is the provisioner-side
counterpart: it

1. asserts every source-backed content item has exactly one matching binding
   (and rejects an over-claiming extra binding) -- :func:`assert_content_delivery_bindings_complete`,
   called by ``raes_gcp_apply`` before any cloud resource is planned/created;
2. downloads + digest-verifies the payload from the provisioner's own object
   storage config (the binding never carries the bucket) *before* touching any
   guest -- :func:`realize_raes_content_delivery`, called after instances +
   directory realization succeed;
3. delivers the verified bytes to every concrete instance of the content's
   target node over the authenticated guest transport
   (``plans.raes_content_delivery.RaesContentDeliveryPlan``), and treats a
   missing/failed in-guest verify-step readback as a hard failure -- fail
   closed before ``publish_ready`` triggers ``_cleanup_failed_apply``.

No payload bytes, storage key, sha256 source value, or content path ever
reaches a log line or exception message here: every raised error is a
bounded, value-free ``RaesContentDeliveryError``, and the one place an
underlying provider exception is logged (``_download_and_verify``) logs only
its bounded class name via ``log_redact.safe_log_value`` and a plain
(no ``exc_info``) call -- deliberately not ``logger.exception``, which would
attach the provider exception's own traceback (and therefore its message,
which AWS/GCS adapters render with the bucket/key baked in) to the log record
even though the exception raised onward uses ``from None``.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.raes.content_delivery import ContentDeliveryError

from cloud import get_object_storage
from cloud.exceptions import CloudError
from cloud.types import ObjectStorage
from config import RaesContentDeliveryConfig, load_raes_content_delivery_config
from executors.base import CommandExecutor
from executors.factory import GuestExecutionContext, build_guest_execution_context
from log_redact import safe_log_value
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.raes_content_delivery import RaesContentDeliveryPlan, RaesContentInstallOptions
from plans.raes_feature_service import RaesFeatureServicePlan
from plans.verification_only import VerificationOnlyPlan
from raes_delivery_contract import (
    SAFE_SERVICE_IDENTITY,
    SUPPORTED_DELIVERY_CONTENT_TYPES,
    FeatureDependencyCycleError,
    assert_content_delivery_bindings_complete,
    ordered_features,
    source_backed_content,
    validated_binding,
)
from raes_plan import RaesPlan, RaesPlanContent, RaesPlanFeature, RaesPlanNode

__all__ = ["assert_content_delivery_bindings_complete"]

logger = logging.getLogger(__name__)

#: Streaming/read chunk size for the downloaded-payload digest + base64 pass.
_READ_CHUNK_BYTES = 1024 * 1024

#: Guest readiness wait before attempting delivery (content delivery runs
#: after instance + directory realization, so the guest is normally already
#: reachable; this is defense against a slow-booting or just-joined guest).
_GUEST_READY_TIMEOUT_SECONDS = 600


class RaesContentDeliveryError(RuntimeError):
    """Value-free failure at the RAES content-delivery realization boundary."""


_INVALID_SERVICE_FEATURE = "RAES service feature contract is invalid"


@dataclass(frozen=True)
class RaesContentDeliveryOps:
    """Injectable object-storage, execution, and orchestration operations."""

    config_loader: Callable[[], RaesContentDeliveryConfig] = load_raes_content_delivery_config
    object_storage_factory: Callable[[], ObjectStorage] = get_object_storage
    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context
    orchestrator_factory: Callable[[CommandExecutor], SetupOrchestrator] = SetupOrchestrator
    verify_only: bool = False


def default_content_delivery_ops() -> RaesContentDeliveryOps:
    """Return the production object-storage and guest-execution bindings."""
    return RaesContentDeliveryOps()


def _binding_for(bindings: list[dict[str, Any]], resource_type: str, resource_address: str) -> dict[str, Any]:
    """Return the one binding for ``content_address``.

    The gate (``assert_content_delivery_bindings_complete``) already
    guarantees every source-backed item has exactly one binding before this
    is ever called; the raise below is unreachable in a correctly-gated apply.
    """
    for binding in bindings:
        if resource_type == "content-placement" and str(binding.get("content_address", "")) == resource_address:
            return binding
        if (
            binding.get("resource_type") == resource_type
            and str(binding.get("resource_address", "")) == resource_address
        ):
            return binding
    # Unreachable in a correctly-gated apply; excluded from coverage via
    # pyproject.toml [tool.coverage.report].exclude_lines (Sonar S139 forbids
    # a trailing "# pragma: no cover" comment on this line).
    raise RaesContentDeliveryError("RAES content delivery binding is missing")


def _target_path(item: RaesPlanContent) -> str:
    """Return the content item's guest target (``path`` for file, ``destination`` for directory)."""
    target = item.path if item.content_type == "file" else item.destination
    if not target:
        raise RaesContentDeliveryError("RAES content delivery target is missing")
    return target


def _platform_for(node: RaesPlanNode) -> str:
    """Return the guest OS dialect (``linux``/``windows``) for one node."""
    return "windows" if (node.os_family or "linux").lower() == "windows" else "linux"


def _read_downloaded_payload(path: str) -> tuple[str, bytes]:
    """Return ``(hex_sha256, raw_bytes)`` for a downloaded payload, one read pass."""
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    with open(path, "rb") as handle:
        while chunk := handle.read(_READ_CHUNK_BYTES):
            hasher.update(chunk)
            chunks.append(chunk)
    return hasher.hexdigest(), b"".join(chunks)


def _installed_tree_sha256(tar_bytes: bytes) -> str:
    """Return the deterministic installed-tree digest for a directory payload.

    Computed over every regular file member's ``(sha256, name)`` pair, sorted by
    tar member name (the same sorted, POSIX-relative names
    ``shared.raes.content_delivery._materialize_directory`` writes), from the tar
    bytes already digest-verified against the binding in this same call --
    never from an untrusted or partially-extracted source. A fresh in-guest
    readback that independently walks the *installed* destination tree and
    recomputes the identical manifest can therefore prove the extraction is
    byte-exact. Hashing the tar bytes themselves (the binding's own ``sha256``)
    only proves the *received* archive was intact before extraction -- it
    cannot detect an install that later dropped, altered, or misplaced a
    member, which is the defect this closes (ADR-034-R6).
    """
    hasher = hashlib.sha256()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        members = sorted((member for member in tar.getmembers() if member.isfile()), key=lambda member: member.name)
        for member in members:
            extracted = tar.extractfile(member)
            data = extracted.read() if extracted is not None else b""
            hasher.update(f"{hashlib.sha256(data).hexdigest()}  {member.name}\n".encode())
    return hasher.hexdigest()


@dataclass(frozen=True)
class _DownloadedPayload:
    """One binding's downloaded, fully-verified payload, ready to deliver."""

    sha256: str
    payload_b64: str
    #: Only set for ``directory`` content -- the expected installed-tree digest
    #: the guest verify_step readback must independently reproduce.
    installed_tree_sha256: str | None


@dataclass(frozen=True)
class _GuestDelivery:
    """Verified content and guest install metadata for one delivery."""

    content_type: str
    target: str
    sensitive: bool
    file_mode: str | None
    platform: str
    downloaded: _DownloadedPayload


def _download_and_verify(
    ops: RaesContentDeliveryOps,
    config: RaesContentDeliveryConfig,
    content_type: str,
    raw_binding: dict[str, Any],
) -> _DownloadedPayload:
    """Download one binding's payload, verify it, and return it ready to deliver.

    Fails closed before any guest is touched: a binding that fails the shared
    producer contract (:func:`validated_binding`), an unconfigured bucket, an
    out-of-bound ``byte_count``, a downloaded-payload digest mismatch, or a
    downloaded size that disagrees with the binding's declared ``byte_count``
    all raise here. The download itself is bound to the object's identity
    (``head_object``) so a replacement mid-flight fails closed too.
    """
    if not config.bucket:
        raise RaesContentDeliveryError("RAES content delivery bucket is not configured")
    try:
        binding = validated_binding(raw_binding)
    except ContentDeliveryError:
        raise RaesContentDeliveryError("RAES content delivery binding is invalid") from None
    if binding.byte_count > config.max_bytes:
        raise RaesContentDeliveryError("RAES content delivery payload exceeds the configured size bound")

    storage = ops.object_storage_factory()
    try:
        identity = storage.head_object(config.bucket, binding.storage_key)
        with tempfile.TemporaryDirectory(prefix="raes-content-delivery-") as staging_dir:
            tmp_path = os.path.join(staging_dir, "payload")
            storage.download_object(
                config.bucket, binding.storage_key, tmp_path, max_bytes=config.max_bytes, expected_identity=identity
            )
            actual_sha256, raw_bytes = _read_downloaded_payload(tmp_path)
    except RaesContentDeliveryError:
        raise
    except CloudError as exc:
        # logger.exception()/exc_info would attach exc's own traceback -- and
        # therefore exc's message, which provider adapters render with the
        # bucket/key baked in (see cloud/aws/storage.py, cloud/gcp/storage.py)
        # -- to the log record. Log only the bounded exception class name via
        # a plain (no exc_info) call, and raise a fresh value-free error
        # `from None` so neither the log nor the propagated exception carries
        # the storage key, bucket, or any other identity value.
        logger.error("RAES content delivery download failed: %s", safe_log_value(exc.__class__.__name__))  # NOSONAR
        raise RaesContentDeliveryError("RAES content delivery payload could not be retrieved") from None

    if actual_sha256 != binding.sha256:
        raise RaesContentDeliveryError("RAES content delivery downloaded payload digest mismatch")
    if len(raw_bytes) != binding.byte_count:
        raise RaesContentDeliveryError("RAES content delivery downloaded payload size mismatch")
    installed_tree_sha256 = _installed_tree_sha256(raw_bytes) if content_type == "directory" else None
    payload_b64 = base64.b64encode(raw_bytes).decode("ascii")
    return _DownloadedPayload(
        sha256=binding.sha256, payload_b64=payload_b64, installed_tree_sha256=installed_tree_sha256
    )


def _output(outputs: dict[str, dict[str, Any]], instance_key: str) -> dict[str, Any]:
    """Return one required instance output or raise a bounded missing-output error."""
    try:
        return outputs[instance_key]
    except KeyError:
        raise RaesContentDeliveryError("RAES content delivery instance output is missing") from None


def _deliver_to_instance(
    ops: RaesContentDeliveryOps,
    output: dict[str, Any],
    delivery: _GuestDelivery,
) -> None:
    """Deliver + in-guest-verify one content item's bytes on one concrete instance.

    ``SetupOrchestrator.orchestrate`` raises ``SetupError`` if the deliver or
    verify step fails after retries. The verify-step branch is mapped back onto
    the RAES-specific digest verification error so callers keep the stronger
    fail-before-``publish_ready`` signal instead of a generic setup failure.
    """
    execution = ops.execution_builder(output, os_type=delivery.platform, role="raes-node")
    try:
        if execution.wait_for_ready(timeout_seconds=_GUEST_READY_TIMEOUT_SECONDS) is False:
            raise RaesContentDeliveryError("RAES content delivery guest did not become ready")
        plan: RaesContentDeliveryPlan | VerificationOnlyPlan = RaesContentDeliveryPlan(
            content_type=delivery.content_type,
            platform=delivery.platform,
            target=delivery.target,
            sha256=delivery.downloaded.sha256,
            payload_b64=delivery.downloaded.payload_b64,
            installed_tree_sha256=delivery.downloaded.installed_tree_sha256,
            install_options=RaesContentInstallOptions(
                sensitive=delivery.sensitive,
                file_mode=delivery.file_mode,
            ),
        )
        if ops.verify_only:
            plan = VerificationOnlyPlan(plan)
        try:
            result = ops.orchestrator_factory(execution.executor).orchestrate(
                execution.target, plan, plan.get_context({}), execution.document_name
            )
        except SetupError as exc:
            if exc.step_name == plan.verify_step.name:
                raise RaesContentDeliveryError("RAES content delivery in-guest digest verification failed") from None
            raise RaesContentDeliveryError("RAES content delivery setup plan failed") from None
        verification = result.verification_result
        if verification is None or not verification.success:
            raise RaesContentDeliveryError("RAES content delivery in-guest digest verification failed")
    finally:
        execution.close()


def _realize_service_on_instance(
    ops: RaesContentDeliveryOps,
    output: dict[str, Any],
    feature: RaesPlanFeature,
    platform: str,
) -> None:
    """Install/locate, enable, start, and independently verify one service."""
    package, version = _validated_service_feature(feature)
    execution = ops.execution_builder(output, os_type=platform, role="raes-node")
    try:
        if execution.wait_for_ready(timeout_seconds=_GUEST_READY_TIMEOUT_SECONDS) is False:
            raise RaesContentDeliveryError("RAES feature service guest did not become ready")
        plan: RaesFeatureServicePlan | VerificationOnlyPlan = RaesFeatureServicePlan(
            platform=platform, package=package, version=version
        )
        if ops.verify_only:
            plan = VerificationOnlyPlan(plan)
        try:
            result = ops.orchestrator_factory(execution.executor).orchestrate(
                execution.target, plan, plan.get_context({}), execution.document_name
            )
        except SetupError as exc:
            if exc.step_name == plan.verify_step.name:
                raise RaesContentDeliveryError("RAES feature service verification failed") from None
            raise RaesContentDeliveryError("RAES feature service setup plan failed") from None
        verification = result.verification_result
        if verification is None or not verification.success:
            raise RaesContentDeliveryError("RAES feature service verification failed")
    finally:
        execution.close()


def _validated_service_feature(feature: RaesPlanFeature) -> tuple[str, str | None]:
    """Handle validated service feature."""
    package = feature.source_name or ""
    version = feature.source_version
    if not SAFE_SERVICE_IDENTITY.fullmatch(package):
        raise RaesContentDeliveryError(_INVALID_SERVICE_FEATURE)
    if version is not None and not SAFE_SERVICE_IDENTITY.fullmatch(version):
        raise RaesContentDeliveryError(_INVALID_SERVICE_FEATURE)
    if feature.has_environment:
        raise RaesContentDeliveryError(_INVALID_SERVICE_FEATURE)
    return package, version


def _deliver_to_node(
    ops: RaesContentDeliveryOps,
    outputs_by_key: dict[str, dict[str, Any]],
    node: RaesPlanNode,
    delivery: _GuestDelivery,
) -> None:
    """Deliver one verified payload to every concrete instance of a node."""
    for index in range(node.count):
        output = _output(outputs_by_key, f"{node.address}#{index}")
        _deliver_to_instance(ops, output, delivery)


def _realize_content_item(
    ops: RaesContentDeliveryOps,
    config: RaesContentDeliveryConfig,
    bindings: list[dict[str, Any]],
    nodes_by_address: dict[str, RaesPlanNode],
    outputs_by_key: dict[str, dict[str, Any]],
    item: RaesPlanContent,
) -> None:
    """Download, verify, and install one source-backed content item."""
    raw_binding = _binding_for(bindings, "content-placement", item.address)
    downloaded = _download_and_verify(ops, config, item.content_type, raw_binding)
    node = nodes_by_address[item.target_address]
    delivery = _GuestDelivery(
        content_type=item.content_type,
        target=_target_path(item),
        sensitive=item.sensitive,
        file_mode=None,
        platform=_platform_for(node),
        downloaded=downloaded,
    )
    _deliver_to_node(ops, outputs_by_key, node, delivery)


def _realize_feature(
    ops: RaesContentDeliveryOps,
    config: RaesContentDeliveryConfig | None,
    bindings: list[dict[str, Any]],
    nodes_by_address: dict[str, RaesPlanNode],
    outputs_by_key: dict[str, dict[str, Any]],
    feature: RaesPlanFeature,
) -> None:
    """Realize one feature after its ordering dependencies have completed."""
    node = nodes_by_address[feature.target_address]
    platform = _platform_for(node)
    if feature.feature_type == "service":
        for index in range(node.count):
            output = _output(outputs_by_key, f"{node.address}#{index}")
            _realize_service_on_instance(ops, output, feature, platform)
        return

    raw_binding = _binding_for(bindings, "feature-binding", feature.address)
    binding = validated_binding(raw_binding)
    content_type = binding.payload_kind or ""
    if content_type not in SUPPORTED_DELIVERY_CONTENT_TYPES or not feature.destination or config is None:
        raise RaesContentDeliveryError("RAES feature delivery contract is invalid")
    delivery = _GuestDelivery(
        content_type=content_type,
        target=feature.destination,
        sensitive=binding.install_policy == "configuration",
        file_mode="755" if binding.install_policy == "executable" else None,
        platform=platform,
        downloaded=_download_and_verify(ops, config, content_type, raw_binding),
    )
    _deliver_to_node(ops, outputs_by_key, node, delivery)


def _realize_source_content(
    ops: RaesContentDeliveryOps,
    config: RaesContentDeliveryConfig | None,
    bindings: list[dict[str, Any]],
    nodes_by_address: dict[str, RaesPlanNode],
    outputs_by_key: dict[str, dict[str, Any]],
    source_content: list[RaesPlanContent],
) -> None:
    """Realize all source-backed content with one required delivery config."""
    if not source_content:
        return
    if config is None:
        raise RaesContentDeliveryError("RAES content delivery config is unavailable")
    for item in source_content:
        _realize_content_item(ops, config, bindings, nodes_by_address, outputs_by_key, item)


def _realize_ordered_features(
    ops: RaesContentDeliveryOps,
    config: RaesContentDeliveryConfig | None,
    bindings: list[dict[str, Any]],
    nodes_by_address: dict[str, RaesPlanNode],
    outputs_by_key: dict[str, dict[str, Any]],
    features: list[RaesPlanFeature],
) -> None:
    """Realize features in their already-validated dependency order."""
    for feature in features:
        _realize_feature(ops, config, bindings, nodes_by_address, outputs_by_key, feature)


def _realize_delivery_plan(
    raes_plan: RaesPlan,
    instance_outputs: list[dict[str, Any]],
    delivery_bindings: list[dict[str, Any]] | None,
    ops: RaesContentDeliveryOps | None,
) -> None:
    """Resolve shared delivery state and realize every content and feature item."""
    source_content = source_backed_content(raes_plan)
    features = ordered_features(raes_plan)
    if not source_content and not features:
        return
    resolved_ops = ops or default_content_delivery_ops()
    bindings = delivery_bindings or []
    nodes_by_address = {node.address: node for node in raes_plan.nodes}
    outputs_by_key = {str(output.get("uuid", "")): output for output in instance_outputs}
    needs_payload = bool(source_content) or any(feature.feature_type != "service" for feature in features)
    config = resolved_ops.config_loader() if needs_payload else None
    _realize_source_content(resolved_ops, config, bindings, nodes_by_address, outputs_by_key, source_content)
    _realize_ordered_features(resolved_ops, config, bindings, nodes_by_address, outputs_by_key, features)


def realize_raes_content_delivery(
    *,
    raes_plan: RaesPlan,
    instance_outputs: list[dict[str, Any]],
    delivery_bindings: list[dict[str, Any]] | None = None,
    ops: RaesContentDeliveryOps | None = None,
) -> None:
    """Deliver every source-backed content item to every concrete instance of its node.

    A no-op when the plan carries no source-backed content. The delivery
    bindings are assumed already gate-validated (``assert_content_delivery_bindings_complete``
    runs before any resource is planned); a missing binding here still raises
    rather than silently skipping, since that would mean the gate was bypassed.
    """
    try:
        _realize_delivery_plan(raes_plan, instance_outputs, delivery_bindings, ops)
    except FeatureDependencyCycleError as exc:
        raise RaesContentDeliveryError(str(exc)) from None
    except RaesContentDeliveryError:
        raise
    except Exception:
        raise RaesContentDeliveryError("RAES content delivery realization failed") from None
