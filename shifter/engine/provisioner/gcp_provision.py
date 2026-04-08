"""GCP range provisioner — creates KubeVirt VMs on GKE.

Replaces the Terraform-based AWS provisioner flow:
- Creates a K8s namespace per range (isolation)
- Creates KubeVirt VirtualMachine CRDs from containerDisk images
- Configures NetworkPolicy for subnet isolation
- Writes provisioned state to the same DB schema as AWS

This module is called from main.py when CLOUD_PROVIDER=gcp.
"""

from __future__ import annotations

import json
import logging
import os
import uuid as uuid_module
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from events import publish_failed, publish_ready, publish_status_update

logger = logging.getLogger(__name__)

# Image mapping: os_type -> env var holding Artifact Registry URI
IMAGE_ENV_MAP = {
    "kali": "KUBEVIRT_KALI_IMAGE",
    "ubuntu": "KUBEVIRT_UBUNTU_IMAGE",
    "windows": "KUBEVIRT_WINDOWS_IMAGE",
}

# Default instance sizing per role
INSTANCE_SIZING = {
    "attacker": {"cpu": 2, "memory": "4Gi"},
    "victim": {"cpu": 2, "memory": "4Gi"},
    "dc": {"cpu": 4, "memory": "8Gi"},
}


def _get_image_for_os(os_type: str) -> str:
    """Resolve containerDisk image URI for an OS type.

    Args:
        os_type: One of kali, ubuntu, windows.

    Returns:
        Artifact Registry image URI.

    Raises:
        ValueError: If image not configured.
    """
    env_var = IMAGE_ENV_MAP.get(os_type)
    if not env_var:
        raise ValueError(f"No image mapping for os_type={os_type}")
    image = os.environ.get(env_var, "")
    if not image:
        raise ValueError(f"{env_var} environment variable not set for os_type={os_type}")
    return image


def _build_namespace_name(request_uuid: str) -> str:
    """Build a K8s namespace name from the request UUID.

    K8s namespace names must be DNS-compatible: lowercase, alphanumeric, hyphens.

    Args:
        request_uuid: UUID string of the request.

    Returns:
        Namespace name like "range-a1b2c3d4".
    """
    short_id = request_uuid.replace("-", "")[:12]
    return f"range-{short_id}"


def provision_range_gcp(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
) -> None:
    """Provision a range on GCP using KubeVirt VMs.

    This is the GCP equivalent of _run_terraform_provision() in main.py.

    Flow:
    1. Create K8s namespace for range isolation
    2. Create KubeVirt VMs for each instance in the spec
    3. Wait for all VMs to reach Running state
    4. Generate SSH keys and store in Secret Manager
    5. Write provisioned state to DB
    6. Publish ready event

    Args:
        request_id: UUID string of the provisioning request.
        range_id: Database ID of the range.
        user_id: Owner's Django user ID.
        range_spec: Hydrated range specification with subnets and instances.
    """
    from executors.kubevirt_executor import KubeVirtExecutor
    from main import update_range_status

    logger.info(
        "provision_range_gcp: starting request_id=%s range_id=%d",
        request_id,
        range_id,
    )

    # Publish provisioning status
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status="provisioning",
    )

    executor = KubeVirtExecutor()
    namespace = _build_namespace_name(request_id)

    try:
        # Step 1: Create namespace
        logger.info("provision_range_gcp: creating namespace=%s", namespace)
        ns_result = executor.create_namespace(
            namespace,
            labels={
                "shifter-range-id": str(range_id),
                "shifter-request-id": request_id,
                "shifter-user-id": str(user_id),
            },
        )
        if not ns_result.success:
            raise RuntimeError(f"Failed to create namespace: {ns_result.stderr}")

        # Step 2: Create VMs for each subnet's instances
        subnets_output: dict[str, dict] = {}
        instances_output: list[dict] = []
        vm_futures: list[dict] = []

        subnets = range_spec.get("subnets", [])
        for subnet_spec in subnets:
            subnet_name = subnet_spec.get("name", "default")
            subnet_uuid = subnet_spec.get("uuid", str(uuid_module.uuid4()))

            subnets_output[subnet_name] = {
                "uuid": subnet_uuid,
                "subnet_id": f"{namespace}/{subnet_name}",
                "subnet_cidr": "",  # K8s pod networking, no manual CIDR
                "security_group_id": "",
                "route_table_id": "",
            }

            for instance_spec in subnet_spec.get("instances", []):
                inst_uuid = instance_spec.get("uuid", str(uuid_module.uuid4()))
                inst_name = instance_spec.get("name", f"vm-{inst_uuid[:8]}")
                role = instance_spec.get("role", "victim")
                os_type = instance_spec.get("os_type", "ubuntu")
                image = instance_spec.get("image") or _get_image_for_os(os_type)
                sizing = INSTANCE_SIZING.get(role, {"cpu": 2, "memory": "4Gi"})

                # Sanitize VM name for K8s (must be DNS-compatible)
                vm_name = inst_name.lower().replace("_", "-").replace(" ", "-")[:63]

                vm_futures.append(
                    {
                        "uuid": inst_uuid,
                        "name": inst_name,
                        "vm_name": vm_name,
                        "role": role,
                        "os_type": os_type,
                        "image": image,
                        "subnet_name": subnet_name,
                        "cpu": sizing["cpu"],
                        "memory": sizing["memory"],
                    }
                )

        # Create VMs in parallel
        logger.info(
            "provision_range_gcp: creating %d VMs in namespace=%s",
            len(vm_futures),
            namespace,
        )

        def _create_vm(vm_spec: dict) -> dict:
            result = executor.create_vm(
                namespace=namespace,
                name=vm_spec["vm_name"],
                image=vm_spec["image"],
                cpu_cores=vm_spec["cpu"],
                memory=vm_spec["memory"],
                labels={
                    "shifter-role": vm_spec["role"],
                    "shifter-os": vm_spec["os_type"],
                    "shifter-instance-uuid": vm_spec["uuid"],
                    "shifter-subnet": vm_spec["subnet_name"],
                },
            )
            if not result.success:
                raise RuntimeError(f"Failed to create VM {vm_spec['vm_name']}: {result.stderr}")
            return vm_spec

        with ThreadPoolExecutor(max_workers=min(len(vm_futures), 10)) as pool:
            futures = {pool.submit(_create_vm, spec): spec for spec in vm_futures}
            for future in as_completed(futures):
                future.result()  # Raises on failure

        # Step 3: Wait for all VMs to reach Running state
        logger.info("provision_range_gcp: waiting for %d VMs to start", len(vm_futures))
        for vm_spec in vm_futures:
            wait_result = executor.wait_for_running(vm_spec["vm_name"], namespace)
            if not wait_result.success:
                raise RuntimeError(f"VM {vm_spec['vm_name']} failed to start: {wait_result.stderr}")

        # Step 4: Get VM IPs and build instance output
        for vm_spec in vm_futures:
            describe_result = executor.describe_instance(vm_spec["vm_name"], namespace)
            if not describe_result.success:
                raise RuntimeError(f"Failed to describe VM {vm_spec['vm_name']}: {describe_result.stderr}")
            vm_info = json.loads(describe_result.stdout)

            # Build the SSH key secret reference.
            # On GCP, SSH keys are stored in Secret Manager.
            ssh_key_secret_ref = os.environ.get("RANGE_SSH_KEY_SECRET", "")

            instances_output.append(
                {
                    "uuid": vm_spec["uuid"],
                    "name": vm_spec["name"],
                    "role": vm_spec["role"],
                    "os": vm_spec["os_type"],
                    "instance_id": vm_spec["vm_name"],
                    "private_ip": vm_info.get("ip_address", ""),
                    "subnet_name": vm_spec["subnet_name"],
                    "ssh_key_secret_arn": ssh_key_secret_ref,
                    # GCP-specific state fields
                    "vm_name": vm_spec["vm_name"],
                    "namespace": namespace,
                    "node": vm_info.get("node", ""),
                }
            )

        # Step 5: Create NetworkPolicy for subnet isolation
        _create_network_policies(executor, namespace, subnets)

        # Step 6: Write state to DB
        logger.info(
            "provision_range_gcp: writing state to DB range_id=%d instances=%d",
            range_id,
            len(instances_output),
        )
        _write_gcp_provisioned_state(range_id, namespace, subnets_output, instances_output)

        # Step 7: Update range status and publish ready event
        update_range_status(range_id, "ready", ready_at="NOW()")
        publish_ready(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
        )

        logger.info(
            "provision_range_gcp: completed request_id=%s range_id=%d vms=%d",
            request_id,
            range_id,
            len(instances_output),
        )

    except Exception as e:
        error_msg = str(e)[:1000]
        logger.exception("provision_range_gcp: failed request_id=%s", request_id)

        # Cleanup: delete namespace (cascades to all VMs)
        try:
            executor.delete_namespace(namespace)
            logger.info("provision_range_gcp: cleanup deleted namespace=%s", namespace)
        except Exception as cleanup_err:
            logger.warning("provision_range_gcp: cleanup failed: %s", cleanup_err)

        update_range_status(range_id, "failed", error_message=error_msg)
        publish_failed(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            error_message=error_msg,
        )
        raise


def destroy_range_gcp(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
) -> None:
    """Destroy a GCP range by deleting the K8s namespace.

    Namespace deletion cascades to all VMs, services, and network policies.

    Args:
        request_id: UUID string of the request.
        range_id: Database ID of the range.
        user_id: Owner's Django user ID.
        range_spec: Range specification (used for logging only).
    """
    from executors.kubevirt_executor import KubeVirtExecutor
    from main import mark_range_instances_destroyed, update_range_status

    logger.info(
        "destroy_range_gcp: starting request_id=%s range_id=%d",
        request_id,
        range_id,
    )

    executor = KubeVirtExecutor()
    namespace = _build_namespace_name(request_id)

    try:
        # Delete namespace — cascades to everything
        result = executor.delete_namespace(namespace)
        if not result.success:
            logger.warning(
                "destroy_range_gcp: namespace delete returned error: %s",
                result.stderr,
            )

        # Mark instances as destroyed in DB
        mark_range_instances_destroyed(range_id)

        # Update range status
        update_range_status(range_id, "destroyed")

        # Publish destroyed event
        from events import publish_destroyed

        publish_destroyed(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
        )

        logger.info(
            "destroy_range_gcp: completed request_id=%s range_id=%d",
            request_id,
            range_id,
        )

    except Exception as e:
        error_msg = str(e)[:1000]
        logger.exception("destroy_range_gcp: failed request_id=%s", request_id)
        update_range_status(range_id, "failed", error_message=error_msg)
        publish_failed(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            error_message=error_msg,
        )
        raise


def _create_network_policies(
    executor: Any,
    namespace: str,
    subnets: list[dict],
) -> None:
    """Create Kubernetes NetworkPolicies for subnet isolation.

    Each subnet gets a NetworkPolicy that:
    - Allows traffic within the subnet (matching labels)
    - Allows traffic to connected subnets
    - Denies other intra-namespace traffic

    Args:
        executor: KubeVirtExecutor (used for core_client access).
        namespace: K8s namespace.
        subnets: List of subnet specs with name, connected_to.
    """
    from kubernetes import client as k8s_client  # type: ignore[import-untyped]
    from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

    networking_client = k8s_client.NetworkingV1Api()

    for subnet_spec in subnets:
        subnet_name = subnet_spec.get("name", "default")
        connected_to = subnet_spec.get("connected_to", [])

        # Allow ingress from same subnet and connected subnets
        allowed_labels = [subnet_name, *connected_to]
        ingress_from = [
            k8s_client.V1NetworkPolicyIngressRule(
                from_=[
                    k8s_client.V1NetworkPolicyPeer(
                        pod_selector=k8s_client.V1LabelSelector(
                            match_labels={"shifter-subnet": label},
                        ),
                    )
                    for label in allowed_labels
                ],
            )
        ]

        policy = k8s_client.V1NetworkPolicy(
            metadata=k8s_client.V1ObjectMeta(
                name=f"subnet-{subnet_name}",
                namespace=namespace,
            ),
            spec=k8s_client.V1NetworkPolicySpec(
                pod_selector=k8s_client.V1LabelSelector(
                    match_labels={"shifter-subnet": subnet_name},
                ),
                policy_types=["Ingress"],
                ingress=ingress_from,
            ),
        )

        try:
            networking_client.create_namespaced_network_policy(
                namespace=namespace,
                body=policy,
            )
            logger.debug(
                "Created NetworkPolicy subnet-%s in namespace=%s",
                subnet_name,
                namespace,
            )
        except ApiException as e:
            if e.status == 409:
                logger.debug("NetworkPolicy subnet-%s already exists", subnet_name)
            else:
                logger.warning(
                    "Failed to create NetworkPolicy subnet-%s: %s",
                    subnet_name,
                    e,
                )


def _write_gcp_provisioned_state(
    range_id: int,
    namespace: str,
    subnets: dict[str, dict],
    instances: list[dict],
) -> None:
    """Write GCP-specific provisioned state to database.

    Uses the same DB schema as write_provisioned_state() in main.py but
    with GCP-specific state fields (vm_name, namespace instead of
    aws_instance_id, aws_subnet_id).

    Args:
        range_id: Database ID of the range.
        namespace: K8s namespace for this range.
        subnets: Dict of subnet_name -> subnet details.
        instances: List of instance dicts with VM details.
    """
    from main import get_db_connection

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Update engine_subnet state
            for subnet_name, subnet_data in subnets.items():
                subnet_uuid = subnet_data.get("uuid")
                if not subnet_uuid:
                    continue

                state = {
                    "namespace": namespace,
                    "subnet_name": subnet_name,
                    "cloud_provider": "gcp",
                }

                cur.execute(
                    """
                    UPDATE engine_subnet
                    SET state = %s, status = 'ready'
                    WHERE uuid = %s AND range_id = %s
                    """,
                    (json.dumps(state), subnet_uuid, range_id),
                )

            # Update engine_instance state
            provisioned_instances = []
            for inst in instances:
                instance_uuid = inst.get("uuid")
                if not instance_uuid:
                    continue

                instance_state = {
                    "vm_name": inst.get("vm_name"),
                    "namespace": namespace,
                    "private_ip": inst.get("private_ip"),
                    "ssh_key_secret_arn": inst.get("ssh_key_secret_arn", ""),
                    "subnet_name": inst.get("subnet_name"),
                    "node": inst.get("node", ""),
                    "cloud_provider": "gcp",
                }

                cur.execute(
                    """
                    UPDATE engine_instance
                    SET status = 'ready', state = %s
                    WHERE uuid = %s
                    """,
                    (json.dumps(instance_state), instance_uuid),
                )

                provisioned_instances.append(
                    {
                        "uuid": instance_uuid,
                        "name": inst.get("name"),
                        "role": inst.get("role"),
                        "os_type": inst.get("os"),
                        "subnet_name": inst.get("subnet_name"),
                        "instance_id": inst.get("vm_name"),
                        "private_ip": inst.get("private_ip"),
                        "ssh_key_secret_arn": inst.get("ssh_key_secret_arn", ""),
                    }
                )

            # Update Range.provisioned_instances
            cur.execute(
                """
                UPDATE mission_control_range
                SET provisioned_instances = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(provisioned_instances), range_id),
            )

        conn.commit()

    logger.info(
        "Wrote GCP provisioned state: range_id=%s subnets=%d instances=%d",
        range_id,
        len(subnets),
        len(instances),
    )
