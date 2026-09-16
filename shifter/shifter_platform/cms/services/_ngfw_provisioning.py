"""NGFW provisioning record creation (#1325 split out of ``_ngfws``).

The Request / Instance / App rows that own an NGFW provisioning. Kept in its own
module so ``cms.services._ngfws`` stays within its size budget, mirroring the
the existing ``_range_backend_admission`` split.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from cms.services._range_workspace import resolve_launch_workspace
from shared.enums import ResourceStatus

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import App, Instance, Request

logger = logging.getLogger(__name__)


def _provision_ngfw_request_records(user: User, name: str) -> tuple[UUID, Request, Instance, App]:
    """Create the Request / Instance / App rows that own an NGFW provisioning."""
    from uuid import uuid4

    from cms.models import App, AppType, Instance, InstanceType, Request
    from shared.enums import RequestType

    request_id = uuid4()
    # The request records who asked, so it carries the requester's scope; the NGFW
    # itself stays deployment-global (ADR-046-R3 / R7).
    request = Request.objects.create(
        request_id=request_id,
        request_type=RequestType.NGFW.value,
        user=user,
        workspace_id=resolve_launch_workspace(user),
    )
    logger.info("create_ngfw: created Request id=%s for user_id=%s", request_id, user.id)

    instance_type = InstanceType.objects.get(slug="panw-ngfw")
    app_type = AppType.objects.get(slug="panw-ngfw")

    instance = Instance.objects.create(
        request=request,
        name=name,
        instance_type=instance_type,
        status=ResourceStatus.PENDING.value,
    )
    logger.info("create_ngfw: created Instance id=%s for user_id=%s", instance.id, user.id)

    app = App.objects.create(
        name=name,
        app_type=app_type,
        instance=instance,
        status=ResourceStatus.PENDING.value,
    )
    logger.info("create_ngfw: created App id=%s for instance_id=%s", app.id, instance.id)

    return request_id, request, instance, app
