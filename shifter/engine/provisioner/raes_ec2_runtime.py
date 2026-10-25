"""Route immutable native AWS operations to bounded provider and guest clients."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from uuid import UUID

from botocore.client import BaseClient
from botocore.config import Config
from shared.model_access.aws_session import bounded_aws_session
from shared.raes.operation_input import image_lookup_key
from shared.range_instantiation_policy import (
    InstantiationPurpose,
    assert_range_backend_egress_supported,
    evaluate_range_backend_admission,
)

from ec2_guest_secrets import Ec2GuestSecrets
from ec2_range_cleanup import Ec2CleanupScope, destroy_ec2_resources, inventory_ec2_resources
from ec2_range_network import Ec2NetworkConfig, allocation_networks
from model_enrollment import EnrollmentDelivery
from provisioner_db_operation_input import RaesOperationRun
from raes_ec2_apply import RaesEc2ApplyOptions, apply_raes_ec2_range, delete_ec2_guest_credentials
from raes_ec2_image import Ec2ImageProfile, resolve_ec2_image
from raes_plan import RaesPlan, RaesPlanNode, parse_plan
from range_subnet_allocation import _release_subnet_allocations_best_effort, _reserve_range_subnet_cidrs
from runtime_plugin_execution import GuestPluginPlans

logger = logging.getLogger(__name__)


def _scope(run: RaesOperationRun) -> Ec2CleanupScope:
    """Require a deployment-bound native EC2 live-fire operation."""
    if os.environ.get("CLOUD_PROVIDER") != "aws" or run.input.range_backend != "ec2":
        raise ValueError("Native EC2 lifecycle requires the bound AWS provider")
    purpose = InstantiationPurpose(run.input.instantiation_purpose)
    if purpose is not InstantiationPurpose.LIVE_FIRE or not evaluate_range_backend_admission("ec2", purpose).admitted:
        raise ValueError("Native EC2 lifecycle requires live-fire admission")
    return Ec2CleanupScope(
        # Scope AWS range resources (tags, secret ARNs, cleanup inventory) by the
        # infrastructure environment name (dev/proof/prod), which the provisioner-iam
        # tag conditions and resource/secret ARNs are keyed on -- NOT the Django
        # ENVIRONMENT (development/production), which would be IAM-denied (#1826).
        os.environ["DEPLOYMENT_ENVIRONMENT"],
        os.environ["AWS_REGION"],
        os.environ["RANGE_VPC_ID"],
        UUID(run.request_id),
        UUID(run.input.resource_generation),
        run.input.legacy_range_id,
    )


@contextmanager
def _clients(scope: Ec2CleanupScope) -> Iterator[tuple[BaseClient, Ec2GuestSecrets]]:
    """Open bounded cloud clients and close both after the operation."""
    session = bounded_aws_session(scope.region)
    config = Config(connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 3}, proxies={})
    with ExitStack() as stack:
        ec2 = session.client("ec2", region_name=scope.region, config=config)
        stack.callback(ec2.close)
        store = session.client("secretsmanager", region_name=scope.region, config=config)
        stack.callback(store.close)
        yield ec2, Ec2GuestSecrets(store, environment=scope.environment, kms_key=os.environ["SECRETS_KMS_KEY_ARN"])


def _cidrs(name: str) -> tuple[str, ...]:
    """Read deployment-owned endpoint CIDRs without inventing default routes."""
    value = os.environ.get(name, "")
    return tuple(item.strip() for item in value.split(",")) if value else ()


def _network(scope: Ec2CleanupScope, enrollment: EnrollmentDelivery | None) -> Ec2NetworkConfig:
    """Project deployment coordinates and admitted broker reachability."""
    return Ec2NetworkConfig(
        environment=scope.environment,
        region=scope.region,
        zone=os.environ["RANGE_AVAILABILITY_ZONE"],
        vpc_id=scope.vpc_id,
        vpc_cidr=os.environ["RANGE_VPC_CIDR"],
        base_route_table_id=os.environ["RANGE_ROUTE_TABLE_ID"],
        management_cidrs=_cidrs("PORTAL_NETWORK_CIDRS"),
        access_cidrs=_cidrs("ACCESS_NETWORK_CIDRS"),
        broker_cidrs=_cidrs("MODEL_BROKER_GUEST_CIDRS") if enrollment is not None else (),
    )


def _resolve_image(node: RaesPlanNode, run: RaesOperationRun) -> Ec2ImageProfile:
    """Resolve a node image solely from the generation's immutable bindings."""
    name = image_lookup_key(source_name=node.image.name if node.image else None, os_family=node.os_family)
    return resolve_ec2_image(
        node,
        run.input.image_candidates_for("aws", name) if name else [],
        binding=run.input.artifact_binding_for(node.address),
        runtime_profile=(
            run.input.runtime_plugin.bindings.image_profile_for(node.address)
            if run.input.runtime_plugin is not None
            else None
        ),
    )


def _release_failed_reservation(
    scope: Ec2CleanupScope, run: RaesOperationRun, plan: RaesPlan, ec2: BaseClient, secrets: Ec2GuestSecrets
) -> None:
    """Release a failed launch reservation only after verified cloud absence."""
    try:
        if inventory_ec2_resources(scope, ec2)["outcome"] == "VERIFIED_ABSENT":
            delete_ec2_guest_credentials(scope.range_id, plan, secrets)
            _release_subnet_allocations_best_effort(run.request_id, operation_id=run.operation_id)
    except Exception:
        logger.warning("EC2 failed-launch reservation retained after incomplete cleanup")


def provision_ec2_run(
    run: RaesOperationRun,
    plugin_plans: GuestPluginPlans | None = None,
    enrollment: EnrollmentDelivery | None = None,
) -> dict[str, Any]:
    """Reserve portable addressing and execute the immutable native EC2 realization."""
    scope = _scope(run)
    assert_range_backend_egress_supported("ec2", run.input.egress_mode)
    config = _network(scope, enrollment)
    if enrollment is not None and not config.broker_cidrs:
        raise ValueError("EC2 enrollment requires exact applied broker addresses")
    plan = parse_plan(run.input.plan)
    networks = allocation_networks(plan)
    # The existing tenant allocator reserves portable /28 intent. Never replace
    # authored addressing with a conveniently available subnet.
    if any(network.cidr or network.gateway for network in networks):
        raise ValueError("EC2 authored addressing requires an exact subnet reservation capability")
    spec = {"subnets": [{"uuid": network.address, "name": network.name} for network in networks]}

    with _clients(scope) as (ec2, secrets):
        realized = _reserve_range_subnet_cidrs(run.request_id, spec, operation_id=run.operation_id)
        try:
            allocated = {row["uuid"]: row["cidr"] for row in realized["subnets"]}
            return apply_raes_ec2_range(
                run.request_id,
                scope.range_id,
                plan,
                lambda node: _resolve_image(node, run),
                RaesEc2ApplyOptions(
                    config=config,
                    generation=scope.generation,
                    ec2=ec2,
                    secrets=secrets,
                    allocated_cidrs=allocated,
                    egress_mode=run.input.egress_mode,
                    runtime_plugin=plugin_plans.execute if plugin_plans else None,
                    model_enrollment=enrollment.execute if enrollment else None,
                ),
                delivery_bindings=run.input.binding_transport(),
                access_bindings=run.input.access_binding_transport(),
            )
        except Exception:
            # Apply compensation is not absence evidence. A failed retry may
            # still have live guests, so keep its reservation until readback.
            _release_failed_reservation(scope, run, plan, ec2, secrets)
            raise


def destroy_ec2_run(run: RaesOperationRun) -> dict[str, Any]:
    """Cleanup does not load enabled plugins, current images, or broker settings."""
    scope = _scope(run)
    plan = parse_plan(run.input.plan, cleanup_only=True)
    with _clients(scope) as (ec2, secrets):
        result = destroy_ec2_resources(scope, ec2)
        if result["outcome"] == "VERIFIED_ABSENT":
            delete_ec2_guest_credentials(scope.range_id, plan, secrets)
            _release_subnet_allocations_best_effort(run.request_id, operation_id=run.operation_id)
        return result
