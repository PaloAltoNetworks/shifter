"""Closed range pause/resume lifecycle-capability policy (ADR-039, issue #614).

Decides whether a range's realized asset mix can be *losslessly* paused and
resumed on its persisted substrate adapter. Pause/resume is honest only when
every participating asset preserves its runtime state and identity across the
cycle; an ephemeral or unknown asset kind must make the whole range unsupported
rather than be silently skipped or faked (ADR-039 lossless pause/resume).

This is one Django-free, dependency-light seam shared by:

* the CMS lifecycle service gate -- primary pre-dispatch admission, so an
  unsupported range stays ``READY`` instead of dispatching a doomed pause;
* the Mission Control range projection -- server-computed ``pause_supported`` /
  ``resume_supported`` booleans so the SPA never infers capability from provider
  names, asset types, or status; and
* the provisioner -- defense-in-depth, failing before any mutation.

Capability is keyed by ``(cloud_provider, asset_type)`` and is default-deny: an
unknown combination is unsupported, never assumed pausable. It is intentionally
free of Django and provider SDKs so the standalone provisioner image and the
platform both import it, exactly as they both import
``shared.range_instantiation_policy``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from shared.range_instantiation_policy import UNSUPPORTED_CAPABILITY_CODE

# Canonical asset-type identifiers persisted in ``engine_instance.state`` and
# emitted by the provisioner output builders. Defined once here so callers stop
# reproducing the bare string literals.
ASSET_TYPE_VM_RUNTIME_VM = "vm_runtime_vm"
ASSET_TYPE_SCENARIO_POD = "scenario_pod"
ASSET_TYPE_GCE_VM = "gce_vm"

# Default provider/asset for a row whose state omits them, mirroring
# ``range_ops._pause_resume._build_range_lifecycle_entry``.
_DEFAULT_CLOUD_PROVIDER = "aws"
_DEFAULT_ASSET_TYPE = ASSET_TYPE_VM_RUNTIME_VM

# The classified ADR-039 failure code for a pre-dispatch or defense-in-depth
# denial (hyphenated), reused from the range-instantiation policy so CMS, the
# serializer, and the provisioner share one vocabulary.
LIFECYCLE_UNSUPPORTED_CODE = UNSUPPORTED_CAPABILITY_CODE

# The append-only result-inbox reason code (underscored) the provisioner records
# on a terminal capability failure. Kept in step with
# ``shared.operation_result_payloads.REASON_CODES``.
LIFECYCLE_UNSUPPORTED_REASON_CODE = "unsupported_capability"

# The ``(cloud_provider, asset_type)`` pairs whose pause/resume preserves runtime
# state and identity:
#
# * AWS EC2 stop/start keeps the EBS root volume.
# * GDC VM Runtime ``kubectl virt`` stop/start keeps the PVC-backed
#   VirtualMachineDisk.
# * GCE stop/start keeps the persistent boot disk.
#
# ``(gcp, scenario_pod)`` is deliberately absent: a scenario Pod has no
# persistent volume, so its power operation deletes and recreates the Pod and
# cannot preserve state -- the range must be unsupported instead.
_LOSSLESS_PAUSABLE: frozenset[tuple[str, str]] = frozenset(
    {
        (_DEFAULT_CLOUD_PROVIDER, ASSET_TYPE_VM_RUNTIME_VM),
        ("gcp", ASSET_TYPE_VM_RUNTIME_VM),
        ("gcp", ASSET_TYPE_GCE_VM),
    }
)

# The persisted ``Range.range_backend`` binding is the sole adapter-selection
# authority (ADR-039). Each backend may realize only its own asset kinds; a
# realized asset outside its backend's admitted set means the realized metadata
# disagrees with the canonical binding -- a cross-adapter mix (e.g. a GCE VM and
# a GDC VM Runtime guest in one range) or stale/spoofed state -- and fails closed
# before dispatch even when the asset kind would otherwise be pausable. AWS ranges
# carry no GCP backend, so ``None``/``""``/``"aws"`` all map to the AWS binding.
_BACKEND_ADMITTED_ASSETS: dict[str, frozenset[tuple[str, str]]] = {
    "aws": frozenset({("aws", ASSET_TYPE_VM_RUNTIME_VM)}),
    "gce": frozenset({("gcp", ASSET_TYPE_GCE_VM)}),
    "gdc": frozenset({("gcp", ASSET_TYPE_VM_RUNTIME_VM), ("gcp", ASSET_TYPE_SCENARIO_POD)}),
}


def normalize_backend(backend: object) -> str:
    """Return the canonical range-backend slug; AWS ranges carry no GCP backend."""
    slug = str(backend).strip().lower() if backend is not None else ""
    return "aws" if slug in {"", "aws"} else slug


def _admitted_assets_for(backend: object) -> frozenset[tuple[str, str]]:
    """Return the ``(provider, asset_type)`` set the binding admits (empty = unknown)."""
    return _BACKEND_ADMITTED_ASSETS.get(normalize_backend(backend), frozenset())


@dataclass(frozen=True)
class LifecycleCapability:
    """Whether a range's realized asset mix is losslessly pause/resume-safe.

    ``reason`` is an authored, stable message safe to surface (no secrets, no raw
    exception text); it is empty when ``supported`` is True. ``unsupported_assets``
    lists the distinct ``(cloud_provider, asset_type)`` pairs that failed, in a
    stable order, for diagnostics.
    """

    supported: bool
    reason: str
    unsupported_assets: tuple[tuple[str, str], ...]


def normalize_asset_key(cloud_provider: object, asset_type: object) -> tuple[str, str]:
    """Return the normalized ``(cloud_provider, asset_type)`` capability key.

    Mirrors the provisioner's lifecycle-entry defaulting so a state row missing
    either field is classified exactly as the dispatcher would treat it.
    """
    provider = str(cloud_provider).strip().lower() if cloud_provider is not None else ""
    provider = provider or _DEFAULT_CLOUD_PROVIDER
    asset = str(asset_type).strip() if asset_type is not None else ""
    asset = asset or _DEFAULT_ASSET_TYPE
    return provider, asset


def is_lossless_pausable(cloud_provider: object, asset_type: object) -> bool:
    """Return True when one asset preserves state across pause/resume."""
    return normalize_asset_key(cloud_provider, asset_type) in _LOSSLESS_PAUSABLE


def range_pause_resume_capability(
    backend: object,
    assets: Iterable[tuple[object, object]],
) -> LifecycleCapability:
    """Classify a range as losslessly pause/resume-safe against its persisted binding.

    ``backend`` is the persisted ``Range.range_backend`` (``None``/``"aws"`` for
    AWS, ``"gce"`` or ``"gdc"`` for GCP) -- the sole adapter-selection authority.
    ``assets`` is an iterable of ``(cloud_provider, asset_type)`` pairs, one per
    lifecycle-managed range instance.

    The range is supported only when *every* asset is (a) admitted by the backend
    binding -- so a cross-adapter mix or stale/spoofed realized metadata fails
    closed -- and (b) losslessly pausable -- so an ephemeral scenario Pod makes the
    whole range unsupported. Either failure mode fails closed before mutation
    (ADR-039). A range with no lifecycle-managed assets is vacuously supported;
    callers that require at least one instance enforce that separately.
    """
    admitted = _admitted_assets_for(backend)
    binding_violations: dict[tuple[str, str], None] = {}
    lossy: dict[tuple[str, str], None] = {}
    for cloud_provider, asset_type in assets:
        key = normalize_asset_key(cloud_provider, asset_type)
        if key not in admitted:
            binding_violations[key] = None
        elif key not in _LOSSLESS_PAUSABLE:
            lossy[key] = None

    unsupported = tuple(sorted({**binding_violations, **lossy}))
    if not unsupported:
        return LifecycleCapability(supported=True, reason="", unsupported_assets=())

    rendered = ", ".join(f"{provider}/{asset}" for provider, asset in unsupported)
    if binding_violations:
        reason = (
            "Range pause/resume is unavailable: it contains assets not admitted by its "
            f"'{normalize_backend(backend)}' range backend binding ({rendered}). A range's "
            "assets must all belong to its single persisted substrate adapter."
        )
    else:
        reason = (
            "Range pause/resume is unavailable: it contains assets that cannot be paused "
            f"without losing state ({rendered}). Pause/resume is enabled only when every "
            "asset preserves its runtime state across the cycle."
        )
    return LifecycleCapability(supported=False, reason=reason, unsupported_assets=unsupported)
