"""Request interpreter - materializes specs into models.

Takes a RequestSpec from CMS, walks the spec tree, and creates
the corresponding Engine models (Request, Instance, App, Subnet).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import transaction

if TYPE_CHECKING:
    from engine.models import App, Instance, Request, Subnet
    from shared.schemas import InstanceSpec, RangeSpec, RequestSpec, SubnetSpec

logger = logging.getLogger(__name__)


def interpret(request_spec: RequestSpec) -> Request:
    """Interpret a RequestSpec into Engine models.

    Creates Request, Instance, and App records by walking the spec tree.
    All models are created in a single transaction.

    Args:
        request_spec: Hydrated RequestSpec from CMS.

    Returns:
        The created Request model with related instantiations.

    Raises:
        TypeError: If request_spec is not a RequestSpec.
        ValueError: If request_spec fails validation.
        User.DoesNotExist: If user_id doesn't map to a Django user.
    """
    from django.contrib.auth import get_user_model

    from engine.models import Request
    from shared.schemas import InstanceSpec, RangeSpec
    from shared.schemas import RequestSpec as RequestSpecClass

    User = get_user_model()

    if not isinstance(request_spec, RequestSpecClass):
        raise TypeError(f"Expected RequestSpec, got {type(request_spec).__name__}")

    if not request_spec.items:
        raise ValueError("RequestSpec must have at least one item")

    user = User.objects.get(id=request_spec.user_id)

    # Determine request type from items
    request_type = _infer_request_type(request_spec)

    with transaction.atomic():
        # Create Request
        request = Request.objects.create(
            request_id=request_spec.request_id,
            request_type=request_type,
            user=user,
        )

        logger.info(
            "interpret: created request_id=%s type=%s",
            request_spec.request_id,
            request_type,
        )

        # Walk items and create instantiations
        for item in request_spec.items:
            if isinstance(item, InstanceSpec):
                _interpret_instance(item, request)
            elif isinstance(item, RangeSpec):
                _interpret_range(item, request)
            else:
                logger.warning("interpret: unknown item type %s", type(item).__name__)

    return request


def _infer_request_type(request_spec: RequestSpec) -> str:
    """Infer RequestType from the items in the spec."""
    from shared.enums import RequestType
    from shared.schemas import InstanceSpec, RangeSpec

    for item in request_spec.items:
        if isinstance(item, RangeSpec):
            return RequestType.RANGE.value
        if isinstance(item, InstanceSpec) and item.role == "ngfw":
            return RequestType.NGFW.value

    # Default fallback for unknown item types
    raise ValueError("RequestSpec must contain RangeSpec or NGFW InstanceSpec")


def _interpret_instance(instance_spec: InstanceSpec, request: Request, subnet: Subnet | None = None) -> Instance:
    """Create Instance and any nested Apps from an InstanceSpec.

    Args:
        instance_spec: InstanceSpec from the hydrated request.
        request: Parent Request this instance belongs to.
        subnet: Optional Subnet this instance belongs to (for Range instances).
    """
    from engine.models import Instance
    from shared.enums import ResourceStatus

    # Generate UUID if not provided
    instance_uuid = instance_spec.uuid or str(uuid4())

    instance = Instance.objects.create(
        uuid=instance_uuid,
        request=request,
        subnet=subnet,
        role=instance_spec.role,
        os_type=instance_spec.os_type,
        spec=instance_spec.model_dump(mode="json"),
        status=ResourceStatus.PENDING.value,
    )

    logger.info(
        "interpret: created instance uuid=%s role=%s",
        instance_uuid,
        instance_spec.role,
    )

    # Create nested App if present
    if instance_spec.ngfw_app:
        _interpret_ngfw_app(instance_spec.ngfw_app, instance, request)

    # TODO: Handle other app types (agent_app, os_app, other_app) when needed

    return instance


def _interpret_ngfw_app(ngfw_app_spec, instance: Instance, request: Request) -> App:
    """Create App from an NGFWAppSpec."""
    from engine.models import App
    from shared.enums import ResourceStatus

    # Use app_id from spec if provided, otherwise model generates default
    app_kwargs = {
        "request": request,
        "instance": instance,
        "app_type": App.AppType.NGFW,
        "spec": ngfw_app_spec.model_dump(mode="json"),
        "status": ResourceStatus.PENDING.value,
    }
    if ngfw_app_spec.app_id:
        app_kwargs["uuid"] = ngfw_app_spec.app_id

    app = App.objects.create(**app_kwargs)

    logger.info(
        "interpret: created app uuid=%s type=ngfw",
        app.uuid,
    )

    return app


def _interpret_range(range_spec: RangeSpec, request: Request) -> None:
    """Create Subnets and Instances from a RangeSpec.

    Iterates through all subnets in the range, creates Subnet
    records for each, and Instance records for instances within.
    """
    # Walk subnets - create Subnet record and its Instances
    for subnet_spec in range_spec.subnets:
        _interpret_subnet(subnet_spec, request)


def _interpret_subnet(subnet_spec: SubnetSpec, request: Request) -> Subnet:
    """Create Subnet and its Instances from a SubnetSpec."""
    from engine.models import Subnet
    from shared.enums import ResourceStatus

    # Use UUID from spec if provided
    subnet_uuid = subnet_spec.uuid or str(uuid4())

    subnet = Subnet.objects.create(
        uuid=subnet_uuid,
        request=request,
        name=subnet_spec.name,
        connected_to=subnet_spec.connected_to,
        spec=subnet_spec.model_dump(mode="json"),
        status=ResourceStatus.PENDING.value,
    )

    logger.info(
        "interpret: created subnet uuid=%s name=%s connected_to=%s",
        subnet_uuid,
        subnet_spec.name,
        subnet_spec.connected_to,
    )

    # Create instances within this subnet
    for instance_spec in subnet_spec.instances:
        _interpret_instance(instance_spec, request, subnet=subnet)

    return subnet
