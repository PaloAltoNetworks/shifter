"""Authoritative RAES range launch path (#1479 / #1311).

``create_raes_native_range`` launches a registered RAES package through the
RAES provisioning path: it reuses the range ownership / active-range /
audit helpers, persists the same CMS ``Request`` + ``RangeInstance`` bookkeeping
(so Mission Control visibility, active-range admission, and the
``range.status.updated`` -> ``apply_range_status`` flow all work uniformly, keyed
by ``request_id``), then drives the RAES backend + dispatch port instead of
legacy hydration. The ``RangeInstance`` carries ``range_spec=None`` because the
serialized RAES provisioning plan is the only authored runtime contract.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from cms.exceptions import CMSError
from cms.models import RangeInstance
from cms.services._range_backend_admission import assert_backend_admitted
from cms.services._range_launch_common import (
    LaunchOptions,
    _assert_no_active_range,
    _assert_scenario_launchable,
    _audit_log_call,
    _reserve_active_range_slot,
    _set_range_instance_status,
    _validate_create_range_scenario,
    _validate_create_range_user,
)
from cms.services._range_workspace import admit_workspace_launch, resolve_launch_workspace
from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
)
from shared.enums import ResourceStatus
from shared.range_instantiation_policy import InstantiationPurpose

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import RaesPackageSource, Request
    from shared.enums import RangeSource
    from shared.model_access import OwnedReference
    from shared.range_instantiation_policy import BackendAdmission
    from shared.schemas.range import RangeContext

logger = logging.getLogger(__name__)

_OBJECT_SOURCE_KIND = "object"
# The only range backend raes_range_ops can realize today (#1354).
_RAES_REALIZED_BACKEND = "gce"


def _load_raes_source_or_raise(scenario: str) -> RaesPackageSource:
    """Return the RaesPackageSource for ``scenario`` or raise a clear CMSError."""
    from cms.models import RaesPackageSource

    try:
        return RaesPackageSource.objects.get(scenario_id=scenario)
    except RaesPackageSource.DoesNotExist:
        raise CMSError(f"No RAES package registered for scenario '{scenario}'") from None


def _dispatch_raes_package(
    request_id: UUID,
    user: User,
    source: RaesPackageSource,
    backend_admission: BackendAdmission | None,
    workspace_id: int,
    egress_mode: str,
) -> None:
    """Resolve, verify, load, plan, and dispatch one registered RAES pack.

    Routes on ``source.source_kind``: a ``repo`` pack resolves under
    ``RAES_PACKAGE_ROOT``; an ``object`` pack resolves through the object-storage
    launch resolver (#1567). Both paths end in the same digest-verified,
    canonical-launch tail (:func:`_launch_pack`). ``backend_admission`` (the
    trusted #1348 result) is threaded to the dispatch port so the Engine binds
    the #1666 ownership fields at create; ``workspace_id`` (the trusted #1325
    tenancy scope) rides the same way so the RAES path scopes ranges exactly like
    the cyberscript path (ADR-046-R3).
    """
    from cms.services._raes_dispatch import dispatch_object_raes_package, dispatch_repo_raes_package

    if source.source_kind == _OBJECT_SOURCE_KIND:
        dispatch_object_raes_package(request_id, user, source, backend_admission, workspace_id, egress_mode)
    else:
        dispatch_repo_raes_package(request_id, user, source, backend_admission, workspace_id, egress_mode)


def _audit_raes_range_provision(request_id: UUID, scenario: str, user: User, range_source: RangeSource) -> None:
    """Write the audit-log entry for a successful RAES-native launch."""
    instance = RangeInstance.objects.filter(request__request_id=request_id).first()
    lease_state: dict[str, object] = {}
    if instance is not None and instance.lease_policy_source:
        lease_state = {
            "lease_initial_days": instance.lease_initial_days,
            "lease_maximum_days": instance.lease_maximum_days,
            "lease_extension_days": instance.extension_days,
            "lease_policy_source": instance.lease_policy_source,
            "lease_policy_tenant_revision": instance.lease_policy_tenant_revision,
            "lease_policy_group_revisions": instance.lease_policy_group_revisions,
        }
    _audit_log_call(
        entity_type=AuditEntityType.RANGE,
        entity_id=instance.pk if instance is not None else 0,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.USER,
        actor_id=user.id,
        new_state={
            "request_id": str(request_id),
            "scenario": scenario,
            "provisioning": "raes-native",
            "range_source": range_source.value,
            **lease_state,
        },
        request_id=str(request_id),
    )


def _build_raes_range_context(request_id: UUID, scenario: str, user: User) -> RangeContext:
    """Build the RangeContext projection returned by the RAES-native launch."""
    from shared.schemas import RangeContext

    return RangeContext(
        request_id=request_id,
        range_id=None,
        scenario_id=scenario,
        user_id=user.id,
        status=ResourceStatus.PROVISIONING,
        instances=[],
        agent_name="",
    )


def _assert_raes_adapter_supports(backend_admission: BackendAdmission | None) -> None:
    """Refuse an RAES launch on an admitted backend that has no RAES adapter (#1354).

    Policy admission and adapter availability are independent gates (ADR-030
    preflight). ``raes_range_ops`` realizes GCE range cells only, so a non-user
    purpose the policy permits on the retained GDC substrate must still fail
    closed here -- before reservation and dispatch -- rather than binding ``gdc``
    and then running the hard-coded GCE adapter.
    """
    if backend_admission is None or backend_admission.backend == _RAES_REALIZED_BACKEND:
        return
    raise CMSError(
        f"RAES-native provisioning has no realization adapter for range backend "
        f"'{backend_admission.backend}'; only the GCE VM range-cell backend is implemented.",
        details={"code": "unsupported-capability"},
    )


def create_raes_native_range(
    user: User,
    scenario: str,
    *,
    range_source: RangeSource | None = None,
    workspace_uuid: str | UUID | None = None,
) -> RangeContext:
    """Launch a registered RAES package through the native provisioning path.

    The generic RAES product facade, permanently live-fire and taking no
    instantiation-purpose argument (ADR-030-R6). The operator-gated non-user
    entry point is ``cms.services.create_non_user_range``.

    Enforces the user/active-range/launchability admission, persists
    the CMS Request + RangeInstance bookkeeping, then dispatches the compiled
    RAES plan. On any dispatch failure the RangeInstance is marked FAILED and the
    error propagates.
    """
    return _create_raes_native_range_impl(
        user,
        scenario,
        range_source=range_source,
        instantiation_purpose=InstantiationPurpose.LIVE_FIRE,
        workspace_uuid=workspace_uuid,
    )


def _create_raes_native_range_impl(
    user: User,
    scenario: str,
    *,
    range_source: RangeSource | None,
    instantiation_purpose: InstantiationPurpose,
    workspace_uuid: str | UUID | None = None,
    enforced_deadline: datetime | None = None,
    model_admission_subject: OwnedReference | None = None,
) -> RangeContext:
    """Shared RAES creation body, parameterized by minted launch authority.

    ``scenario`` is both the stable public id used for persistence/correlation
    and the immutable registered package-source id loaded for the launch.
    """
    from shared.enums import RangeSource

    _validate_create_range_user(user)
    _validate_create_range_scenario(user, scenario)
    if range_source is None:
        range_source = RangeSource.MISSION_CONTROL
    backend_admission = assert_backend_admitted(instantiation_purpose, range_source)
    _assert_raes_adapter_supports(backend_admission)
    _assert_no_active_range(user, range_source)
    _assert_scenario_launchable(scenario)
    source = _load_raes_source_or_raise(scenario)

    def _persist(cms_request: Request) -> RangeInstance:
        """Build the RAES RangeInstance (range_spec=None) for the reservation."""
        from cms.services._range_lease import build_range_lease, build_resolved_mission_control_range_lease

        lease = (
            build_resolved_mission_control_range_lease(user, for_update=True)
            if range_source is RangeSource.MISSION_CONTROL
            else build_range_lease(range_source, enforced_deadline=enforced_deadline)
        )
        return RangeInstance.objects.create(
            request=cms_request,
            scenario_id=scenario,
            user_id=user.id,
            # Inherit the request's authorized scope rather than re-resolving it,
            # so the two projections can never disagree (ADR-046-R3).
            workspace_id=cms_request.workspace_id,
            range_source=range_source.value,
            range_spec=None,
            expires_at=lease.expires_at,
            maximum_expires_at=lease.maximum_expires_at,
            extension_days=lease.extension_days,
            lease_initial_days=lease.initial_days,
            lease_maximum_days=lease.maximum_days,
            lease_policy_source=lease.policy_source,
            lease_policy_tenant_revision=lease.tenant_revision,
            lease_policy_group_revisions=[
                {"group_id": group_id, "revision": revision} for group_id, revision in lease.group_revisions
            ],
        )

    from uuid import uuid4

    request_id = uuid4()
    workspace_id = resolve_launch_workspace(user, workspace_uuid)
    admit_workspace_launch(
        workspace_id=workspace_id,
        user=user,
        range_source=range_source,
        instantiation_purpose=instantiation_purpose,
        correlation_key=request_id,
    )

    from cms.services._range_workspace import resolve_effective_egress_mode

    egress_mode = resolve_effective_egress_mode(workspace_id)

    # PLAT-202: required model access is a fail-closed admission decision enforced
    # here, before any dispatch (cold, warm-claim, or non-user), so every launch
    # family is gated once. Distinct from the best-effort capacity path: a required
    # denial or indeterminate outcome refuses the launch rather than proceeding. A
    # scenario with no authored model need passes through unchanged.
    from cms.services._model_admission import assert_launch_model_access

    assert_launch_model_access(
        user=user,
        scenario_id=scenario,
        egress_mode=egress_mode,
        subject=model_admission_subject,
        package_digest=source.package_digest,
    )

    # #28: attempt an atomic warm-pool claim before cold provisioning. A hit
    # transfers a ready, compatible, system-owned generation to this user (audited
    # ownership rehome) and enqueues activation, which realizes the claimant's
    # fresh, sanitized access. A miss / disabled policy / unsupported backend
    # cold-falls-back through the unchanged reservation + dispatch path below, with
    # the inputs already validated for this launch.
    from cms.services._warm_pool_claim import WarmClaimRequest, attempt_warm_claim

    claimed_request_id = attempt_warm_claim(
        WarmClaimRequest(
            user=user,
            scenario=scenario,
            package_digest=source.package_digest,
            lock_digest=source.lock_digest,
            backend=backend_admission.backend if backend_admission else "",
            instantiation_purpose=instantiation_purpose,
            range_source=range_source,
            workspace_id=workspace_id,
            egress_mode=egress_mode,
            request_id=request_id,
            enforced_deadline=enforced_deadline,
        )
    )
    if claimed_request_id is not None:
        _audit_raes_range_provision(claimed_request_id, scenario, user, range_source)
        return _build_raes_range_context(claimed_request_id, scenario, user)

    _request_id, _cms_request, range_instance, egress_mode = _reserve_active_range_slot(
        user, range_source, _persist, workspace_id, request_id
    )

    try:
        # PLAT-202/#2119: _reserve_active_range_slot resolves egress under the
        # workspace lock, and that authoritative posture — not the earlier
        # preliminary read — is what dispatch uses. Re-run the model gate against
        # it so a posture change between admission and reservation cannot dispatch
        # a required-model range with an incompatible egress. A denial here is
        # released and marked FAILED by the surrounding handler.
        assert_launch_model_access(
            user=user,
            scenario_id=scenario,
            egress_mode=egress_mode,
            subject=model_admission_subject,
            package_digest=source.package_digest,
        )
        _dispatch_raes_package(request_id, user, source, backend_admission, workspace_id, egress_mode)
    except Exception:
        # Dispatch failed before an Engine lifecycle can converge, so mark the
        # range FAILED and release the open concurrent-range reservation as one
        # atomic convergence step. No terminal status event will arrive to repair
        # a partial write, so the FAILED transition and the release must commit
        # together or not at all (ADR-046-R10).
        from workspaces.services import release_workspace_concurrent_range

        with transaction.atomic():
            _set_range_instance_status(range_instance, ResourceStatus.FAILED)
            release_workspace_concurrent_range(workspace_id, request_id)
        raise

    _audit_raes_range_provision(request_id, scenario, user, range_source)
    return _build_raes_range_context(request_id, scenario, user)


def create_range_dispatch(
    user: User,
    scenario: str,
    ngfw_enabled: bool = False,
    range_source: RangeSource | None = None,
    remote_access_teardown_at: datetime | None = None,
    workspace_uuid: str | UUID | None = None,
    model_admission_subject: OwnedReference | None = None,
) -> RangeContext:
    """Launch a registered RAES scenario through the authoritative path.

    ``ngfw_enabled`` remains accepted at the public service seam while callers
    migrate their request shape; RAES packages own topology and authored
    infrastructure intent, so it does not change the plan.

    ``workspace_uuid`` is the optional public workspace selection (ADR-046-R9),
    threaded to whichever create path runs. Server-derived callers (e.g. the CTF
    bridge) omit it, so their ranges bind to the launcher's personal workspace.
    """
    return dispatch_range_launch(
        user,
        scenario,
        range_source=range_source,
        instantiation_purpose=InstantiationPurpose.LIVE_FIRE,
        options=LaunchOptions(
            ngfw_enabled=ngfw_enabled,
            remote_access_teardown_at=remote_access_teardown_at,
            workspace_uuid=workspace_uuid,
            model_admission_subject=model_admission_subject,
        ),
    )


def dispatch_range_launch(
    user: User,
    scenario: str,
    *,
    range_source: RangeSource | None,
    instantiation_purpose: InstantiationPurpose,
    options: LaunchOptions,
) -> RangeContext:
    """Shared RAES launch body, parameterized by minted launch authority.

    Not a product facade. Internal to
    the CMS create seam -- ``cms.services`` exports the two facades that wrap it,
    never this function. ``options`` bundles the optional launch-shaping inputs
    (see :class:`cms.services._range_launch_common.LaunchOptions`).
    """
    # RAES participant access is authored in the package and persisted as the
    # compiled participant-access sidecar. The server-derived CTF cleanup time
    # bounds the range lease; it does not mint an OpenVPN capability or alter the
    # RAES plan.
    return _create_raes_native_range_impl(
        user,
        scenario,
        range_source=range_source,
        instantiation_purpose=instantiation_purpose,
        workspace_uuid=options.workspace_uuid,
        enforced_deadline=options.remote_access_teardown_at,
        model_admission_subject=options.model_admission_subject,
    )
