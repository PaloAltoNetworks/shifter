"""Post-boot delivery of source-backed ACES guest content (#1564, ADR-032-R3).

While the compiled ACES plan's ``content-placement`` resources are realized by
``aces_gcp_composition`` for everything the boot-time bootstrap can safely bake
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
   called by ``aces_gcp_apply`` before any cloud resource is planned/created;
2. downloads + digest-verifies the payload from the provisioner's own object
   storage config (the binding never carries the bucket) *before* touching any
   guest -- :func:`realize_aces_content_delivery`, called after instances +
   directory realization succeed;
3. delivers the verified bytes to every concrete instance of the content's
   target node over the authenticated guest transport
   (``plans.aces_content_delivery.AcesContentDeliveryPlan``), and treats a
   missing/failed in-guest verify-step readback as a hard failure -- fail
   closed before ``publish_ready`` triggers ``_cleanup_failed_apply``.

No payload bytes, storage key, sha256 source value, or content path ever
reaches a log line or exception message here: every raised error is a
bounded, value-free ``AcesContentDeliveryError``, and the one place an
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

from shared.aces.content_delivery import ContentDeliveryError, DeliveryBinding

from aces_gcp_composition import AcesGceCompositionError
from aces_plan import AcesPlan, AcesPlanContent, AcesPlanNode
from cloud import get_object_storage
from cloud.exceptions import CloudError
from cloud.types import ObjectStorage
from config import AcesContentDeliveryConfig, load_aces_content_delivery_config
from executors.base import Executor
from executors.factory import GuestExecutionContext, build_guest_execution_context
from log_redact import safe_log_value
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.aces_content_delivery import AcesContentDeliveryPlan

logger = logging.getLogger(__name__)

#: Content types with a genuine delivery + digest-readback path (mirrors
#: shared.aces.content_delivery.SUPPORTED_DELIVERY_CONTENT_TYPES). Any other
#: content_type on a source-backed item cannot be realized safely.
_SUPPORTED_DELIVERY_CONTENT_TYPES = frozenset({"file", "directory"})

#: Streaming/read chunk size for the downloaded-payload digest + base64 pass.
_READ_CHUNK_BYTES = 1024 * 1024

#: Guest readiness wait before attempting delivery (content delivery runs
#: after instance + directory realization, so the guest is normally already
#: reachable; this is defense against a slow-booting or just-joined guest).
_GUEST_READY_TIMEOUT_SECONDS = 600


class AcesContentDeliveryError(RuntimeError):
    """Value-free failure at the ACES content-delivery realization boundary."""


@dataclass(frozen=True)
class AcesContentDeliveryOps:
    """Injectable object-storage, execution, and orchestration operations."""

    config_loader: Callable[[], AcesContentDeliveryConfig] = load_aces_content_delivery_config
    object_storage_factory: Callable[[], ObjectStorage] = get_object_storage
    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context
    orchestrator_factory: Callable[[Executor], SetupOrchestrator] = SetupOrchestrator


def default_content_delivery_ops() -> AcesContentDeliveryOps:
    """Return the production object-storage and guest-execution bindings."""
    return AcesContentDeliveryOps()


def _source_backed_content(aces_plan: AcesPlan) -> list[AcesPlanContent]:
    """Return every content item whose bytes are delivered, not baked in."""
    return [item for item in aces_plan.content if item.source_name]


def _validated_binding(raw: dict[str, Any]) -> DeliveryBinding:
    """Parse + fully validate one persisted binding against the producer contract.

    Reuses ``shared.aces.content_delivery.DeliveryBinding.from_transport`` --
    the exact schema/version/digest/address/key validation the CMS producer
    applies when it hands the binding to the engine (ADR-032-R3) -- so the
    provisioner never trusts a persisted binding's shape, version, or digest
    format merely because it round-tripped through the database. Additionally
    enforces that ``storage_key`` is structurally bound to ``sha256``
    (``.../<dd>/<digest>``, the suffix ``normalized_storage_key`` always
    produces): the provisioner does not know the CMS-configured key prefix,
    but the digest suffix is a server-derived invariant a tampered or
    malformed binding cannot satisfy by chance.
    """
    binding = DeliveryBinding.from_transport(raw)
    suffix = f"/{binding.sha256[:2]}/{binding.sha256}"
    if not binding.storage_key.endswith(suffix):
        raise ContentDeliveryError("delivery binding storage_key is not content-addressed")
    return binding


def assert_content_delivery_bindings_complete(
    aces_plan: AcesPlan,
    delivery_bindings: list[dict[str, Any]] | None,
) -> None:
    """Fail closed unless every source-backed content item has one valid binding.

    Rejects (all as a bounded, value-free ``AcesGceCompositionError``, mirroring
    the sibling ``_assert_composition_targets_resolve`` gate):

    - a binding that fails the shared producer contract (:func:`_validated_binding`)
      -- an unknown ``binding_version``, a malformed digest, a non-canonical
      ``storage_key``, an unknown key, or a negative ``byte_count``;
    - a source-backed content item with no matching binding;
    - a binding whose ``content_address`` matches no source-backed content item
      (an over-claim -- a stale or forged binding riding along);
    - a source-backed content item whose ``content_type`` has no delivery
      materializer (only ``file``/``directory`` do).

    Bindings are joined to content items by the compiled plan's own resource
    address (``AcesPlanContent.address``, threaded through by ``aces_plan``
    from the same serialized-plan resource key the CMS side reads) -- never by
    ``target_address``/``path``, since a node may carry more than one content
    item and paths are author-controlled. This runs before any cloud resource
    is planned/created (``aces_gcp_apply``), so a malformed binding never
    reaches storage access or guest delivery.
    """
    source_backed = _source_backed_content(aces_plan)
    for item in source_backed:
        if item.content_type not in _SUPPORTED_DELIVERY_CONTENT_TYPES:
            raise AcesGceCompositionError(f"source-backed content {item.content_type!r} has no delivery materializer")
    bindings = delivery_bindings or []
    for raw_binding in bindings:
        try:
            _validated_binding(raw_binding)
        except ContentDeliveryError:
            raise AcesGceCompositionError("a delivery binding failed contract validation") from None
    bound_addresses = {str(binding.get("content_address", "")) for binding in bindings}
    source_addresses = {item.address for item in source_backed}
    if len(bound_addresses) != len(bindings):
        raise AcesGceCompositionError("ACES content delivery bindings carry a duplicate content_address")
    missing = source_addresses - bound_addresses
    if missing:
        raise AcesGceCompositionError("a source-backed content item is missing its delivery binding")
    extra = bound_addresses - source_addresses
    if extra:
        raise AcesGceCompositionError("a delivery binding does not match any source-backed content item")


def _binding_for(bindings: list[dict[str, Any]], content_address: str) -> dict[str, Any]:
    """Return the one binding for ``content_address``.

    The gate (``assert_content_delivery_bindings_complete``) already
    guarantees every source-backed item has exactly one binding before this
    is ever called; the raise below is unreachable in a correctly-gated apply.
    """
    for binding in bindings:
        if str(binding.get("content_address", "")) == content_address:
            return binding
    # Unreachable in a correctly-gated apply; excluded from coverage via
    # pyproject.toml [tool.coverage.report].exclude_lines (Sonar S139 forbids
    # a trailing "# pragma: no cover" comment on this line).
    raise AcesContentDeliveryError("ACES content delivery binding is missing")


def _target_path(item: AcesPlanContent) -> str:
    """Return the content item's guest target (``path`` for file, ``destination`` for directory)."""
    target = item.path if item.content_type == "file" else item.destination
    if not target:
        raise AcesContentDeliveryError("ACES content delivery target is missing")
    return target


def _platform_for(node: AcesPlanNode) -> str:
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
    ``shared.aces.content_delivery._materialize_directory`` writes), from the tar
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


def _download_and_verify(
    ops: AcesContentDeliveryOps,
    config: AcesContentDeliveryConfig,
    item: AcesPlanContent,
    raw_binding: dict[str, Any],
) -> _DownloadedPayload:
    """Download one binding's payload, verify it, and return it ready to deliver.

    Fails closed before any guest is touched: a binding that fails the shared
    producer contract (:func:`_validated_binding`), an unconfigured bucket, an
    out-of-bound ``byte_count``, a downloaded-payload digest mismatch, or a
    downloaded size that disagrees with the binding's declared ``byte_count``
    all raise here. The download itself is bound to the object's identity
    (``head_object``) so a replacement mid-flight fails closed too.
    """
    if not config.bucket:
        raise AcesContentDeliveryError("ACES content delivery bucket is not configured")
    try:
        binding = _validated_binding(raw_binding)
    except ContentDeliveryError:
        raise AcesContentDeliveryError("ACES content delivery binding is invalid") from None
    if binding.byte_count > config.max_bytes:
        raise AcesContentDeliveryError("ACES content delivery payload exceeds the configured size bound")

    storage = ops.object_storage_factory()
    try:
        identity = storage.head_object(config.bucket, binding.storage_key)
        with tempfile.TemporaryDirectory(prefix="aces-content-delivery-") as staging_dir:
            tmp_path = os.path.join(staging_dir, "payload")
            storage.download_object(
                config.bucket, binding.storage_key, tmp_path, max_bytes=config.max_bytes, expected_identity=identity
            )
            actual_sha256, raw_bytes = _read_downloaded_payload(tmp_path)
    except AcesContentDeliveryError:
        raise
    except CloudError as exc:
        # logger.exception()/exc_info would attach exc's own traceback -- and
        # therefore exc's message, which provider adapters render with the
        # bucket/key baked in (see cloud/aws/storage.py, cloud/gcp/storage.py)
        # -- to the log record. Log only the bounded exception class name via
        # a plain (no exc_info) call, and raise a fresh value-free error
        # `from None` so neither the log nor the propagated exception carries
        # the storage key, bucket, or any other identity value.
        logger.error("ACES content delivery download failed: %s", safe_log_value(exc.__class__.__name__))  # NOSONAR
        raise AcesContentDeliveryError("ACES content delivery payload could not be retrieved") from None

    if actual_sha256 != binding.sha256:
        raise AcesContentDeliveryError("ACES content delivery downloaded payload digest mismatch")
    if len(raw_bytes) != binding.byte_count:
        raise AcesContentDeliveryError("ACES content delivery downloaded payload size mismatch")
    installed_tree_sha256 = _installed_tree_sha256(raw_bytes) if item.content_type == "directory" else None
    payload_b64 = base64.b64encode(raw_bytes).decode("ascii")
    return _DownloadedPayload(
        sha256=binding.sha256, payload_b64=payload_b64, installed_tree_sha256=installed_tree_sha256
    )


def _output(outputs: dict[str, dict[str, Any]], instance_key: str) -> dict[str, Any]:
    """Return one required instance output or raise a bounded missing-output error."""
    try:
        return outputs[instance_key]
    except KeyError:
        raise AcesContentDeliveryError("ACES content delivery instance output is missing") from None


def _deliver_to_instance(
    ops: AcesContentDeliveryOps,
    output: dict[str, Any],
    item: AcesPlanContent,
    platform: str,
    downloaded: _DownloadedPayload,
) -> None:
    """Deliver + in-guest-verify one content item's bytes on one concrete instance.

    ``SetupOrchestrator.orchestrate`` already raises ``SetupError`` if the
    deliver step itself fails after retries (a failing step's
    ``StepResult.success=False`` makes ``orchestrate`` raise before returning
    at all -- its ``SetupResult.success`` is unconditionally ``True`` on every
    normal return). It does **not**, however, raise when a ``verify_step`` runs
    but exits non-zero -- only a hard transport error during verification
    raises -- so the in-guest digest readback is checked explicitly here via
    ``result.verification_result``, to satisfy the fail-before-``publish_ready``
    contract.
    """
    execution = ops.execution_builder(output, os_type=platform, role="aces-node")
    try:
        if execution.wait_for_ready(timeout_seconds=_GUEST_READY_TIMEOUT_SECONDS) is False:
            raise AcesContentDeliveryError("ACES content delivery guest did not become ready")
        plan = AcesContentDeliveryPlan(
            content_type=item.content_type,
            platform=platform,
            target=_target_path(item),
            sha256=downloaded.sha256,
            payload_b64=downloaded.payload_b64,
            sensitive=item.sensitive,
            installed_tree_sha256=downloaded.installed_tree_sha256,
        )
        try:
            result = ops.orchestrator_factory(execution.executor).orchestrate(
                execution.target, plan, plan.get_context({}), execution.document_name
            )
        except SetupError:
            raise AcesContentDeliveryError("ACES content delivery setup plan failed") from None
        verification = result.verification_result
        if verification is None or not verification.success:
            raise AcesContentDeliveryError("ACES content delivery in-guest digest verification failed")
    finally:
        execution.close()


def realize_aces_content_delivery(
    *,
    aces_plan: AcesPlan,
    instance_outputs: list[dict[str, Any]],
    delivery_bindings: list[dict[str, Any]] | None = None,
    ops: AcesContentDeliveryOps | None = None,
) -> None:
    """Deliver every source-backed content item to every concrete instance of its node.

    A no-op when the plan carries no source-backed content. The delivery
    bindings are assumed already gate-validated (``assert_content_delivery_bindings_complete``
    runs before any resource is planned); a missing binding here still raises
    rather than silently skipping, since that would mean the gate was bypassed.
    """
    source_backed = _source_backed_content(aces_plan)
    if not source_backed:
        return
    resolved_ops = ops or default_content_delivery_ops()
    bindings = delivery_bindings or []
    nodes_by_address = {node.address: node for node in aces_plan.nodes}
    outputs_by_key = {str(output.get("uuid", "")): output for output in instance_outputs}
    config = resolved_ops.config_loader()

    try:
        for item in source_backed:
            raw_binding = _binding_for(bindings, item.address)
            downloaded = _download_and_verify(resolved_ops, config, item, raw_binding)
            node = nodes_by_address[item.target_address]
            platform = _platform_for(node)
            for index in range(node.count):
                output = _output(outputs_by_key, f"{item.target_address}#{index}")
                _deliver_to_instance(resolved_ops, output, item, platform, downloaded)
    except AcesContentDeliveryError:
        raise
    except Exception:
        raise AcesContentDeliveryError("ACES content delivery realization failed") from None
