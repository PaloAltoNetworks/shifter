"""Internal dispatch facade for RAES range launches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cms.services._range_launch_common import LaunchOptions
from shared.range_instantiation_policy import InstantiationPurpose

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.enums import RangeSource
    from shared.schemas.range import RangeContext


def dispatch_range_launch(
    user: User,
    scenario: str,
    *,
    range_source: RangeSource | None,
    instantiation_purpose: InstantiationPurpose,
    options: LaunchOptions,
) -> RangeContext:
    """Launch with the authority and policy prepared by the caller."""
    from cms.services._raes_range_create import _create_raes_native_range_impl

    return _create_raes_native_range_impl(
        user,
        scenario,
        range_source=range_source,
        instantiation_purpose=instantiation_purpose,
        workspace_uuid=options.workspace_uuid,
        enforced_deadline=options.remote_access_teardown_at,
        model_admission_subject=options.model_admission_subject,
        model_launch_scope=options.model_launch_scope,
        model_sources=options.model_sources,
        content_authorizer=options.content_authorizer,
        ctf_policy_workspace_id=options.ctf_policy_workspace_id,
    )
