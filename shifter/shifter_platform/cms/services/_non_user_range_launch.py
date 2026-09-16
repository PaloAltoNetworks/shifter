"""The dedicated authorized entry point for a non-user range launch (issue #1354, ADR-030).

ADR-030-R3 retains the Kubernetes/GDC substrate for explicitly declared non-user
modes -- deterministic product demo, breach-and-attack simulation, image-build
validation, operator validation -- and ADR-030-R6 requires that authority be
minted by a dedicated workflow rather than passed in by whoever happens to call
the product facade.

This module is that workflow. The generic facades (``create_range``,
``create_range_dispatch``, ``create_raes_native_range``) take no
instantiation-purpose argument at all, so they cannot escalate. Reaching a
non-user purpose means calling ``create_non_user_range``, which:

1. requires operator authority on the calling user, and
2. *derives* the closed :class:`InstantiationPurpose` from the declared
   :class:`NonUserWorkflow` rather than accepting one.

There is no HTTP surface, serializer, form, scenario field, or event that
reaches this function. It is a server-side seam for a trusted operator workflow
to consume; the closed policy in ``shared.range_instantiation_policy`` still has
the final say on whether the selected backend serves the minted purpose.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from cms.exceptions import CMSError
from cms.services._raes_range_create import dispatch_range_launch
from cms.services._range_launch_common import LaunchOptions
from shared.range_instantiation_policy import POLICY_DENIAL_CODE, InstantiationPurpose

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.schemas.range import RangeContext

logger = logging.getLogger(__name__)

_NOT_AN_OPERATOR = (
    "A non-user range launch requires operator authority. Normal product range creation is "
    "live-fire and cannot select a non-user instantiation mode. See ADR-030."
)

_UNKNOWN_WORKFLOW = "Unknown non-user launch workflow. See ADR-030."


class NonUserWorkflow(StrEnum):
    """Closed set of declared non-user launch workflows (ADR-030-R3).

    Each names a real operator-facing activity, not a containment claim. The
    workflow is what the caller declares; the instantiation purpose is derived
    from it by :data:`_WORKFLOW_PURPOSES` and is never supplied directly.
    """

    PRODUCT_DEMO = "product_demo"
    BREACH_ATTACK_SIMULATION = "breach_attack_simulation"
    OPERATOR_VALIDATION = "operator_validation"
    IMAGE_VALIDATION = "image_validation"


# Deterministic demo and BAS share the demo purpose; image-build validation and
# operator-run validation share the operator-validation purpose. Adding a
# workflow requires an explicit entry -- there is no default.
_WORKFLOW_PURPOSES: dict[NonUserWorkflow, InstantiationPurpose] = {
    NonUserWorkflow.PRODUCT_DEMO: InstantiationPurpose.NON_USER_DEMO,
    NonUserWorkflow.BREACH_ATTACK_SIMULATION: InstantiationPurpose.NON_USER_DEMO,
    NonUserWorkflow.OPERATOR_VALIDATION: InstantiationPurpose.OPERATOR_VALIDATION,
    NonUserWorkflow.IMAGE_VALIDATION: InstantiationPurpose.OPERATOR_VALIDATION,
}


def _assert_operator_authority(user: User) -> None:
    """Require an active operator account before any non-user authority is minted.

    This is the workflow's own gate, run before the purpose exists. It is the
    operator trust boundary the ADR-030 preflight names -- the same
    staff/superuser session authority the Administer surface uses -- and it is
    defense in depth on top of the fact that no request path reaches here.
    """
    if not (getattr(user, "is_active", False) and (user.is_staff or user.is_superuser)):
        logger.warning("create_non_user_range: refused for non-operator user_id=%s", getattr(user, "id", None))
        raise CMSError(_NOT_AN_OPERATOR, details={"code": POLICY_DENIAL_CODE})


def _validated_workflow(workflow: object) -> NonUserWorkflow:
    """Narrow an untrusted argument to a declared workflow, or refuse it.

    Accepting only a closed enum member keeps a raw string or arbitrary object
    from standing in as launch authority (ADR-030-R6).
    """
    if not isinstance(workflow, NonUserWorkflow):
        raise CMSError(_UNKNOWN_WORKFLOW, details={"code": POLICY_DENIAL_CODE})
    return workflow


def create_non_user_range(
    user: User,
    scenario: str,
    agents_by_os: dict[str, int] | None = None,
    *,
    workflow: object,
    ngfw_enabled: bool = False,
) -> RangeContext:
    """Launch a range under a declared non-user mode, after the operator gate.

    Routes through the same RAES dispatch, active-range admission,
    Engine persistence, and provisioner path as a normal launch -- only the
    minted instantiation purpose differs, which is what lets the retained
    GDC/Kubernetes plumbing be selected (ADR-030-R3).

    ``range_source`` is fixed to ``MISSION_CONTROL``: a CTF launch is never a
    non-user launch, and the admission gate refuses that combination anyway.

    Raises ``CMSError`` when the caller lacks operator authority, the workflow is
    not a declared one, or the closed policy denies the resulting
    (backend, purpose) pair.
    """
    from shared.enums import RangeSource

    del agents_by_os
    _assert_operator_authority(user)
    declared = _validated_workflow(workflow)
    purpose = _WORKFLOW_PURPOSES[declared]
    logger.info(
        "create_non_user_range: minted purpose=%s workflow=%s user_id=%s",
        purpose.value,
        declared.value,
        user.id,
    )
    return dispatch_range_launch(
        user,
        scenario,
        range_source=RangeSource.MISSION_CONTROL,
        instantiation_purpose=purpose,
        options=LaunchOptions(ngfw_enabled=ngfw_enabled),
    )
