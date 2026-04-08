"""GCP NGFW provisioner — VM-Series firewall as a KubeVirt VM.

On GCP, the NGFW is a Palo Alto VM-Series running as a KubeVirt VM in a
dedicated namespace. Range subnets are wired to the NGFW using Kubernetes
Services and NetworkPolicy rather than AWS ENIs and VPC route tables.

Architecture:
- NGFW runs in namespace "ngfw-{user_id}" (persists across ranges)
- Data interface exposed as a ClusterIP Service (the "NGFW gateway")
- Range VMs route egress through the NGFW Service IP
- NGFW management IP = NGFW pod IP (reachable from provisioner)
- SSH to NGFW CLI uses the same SSHExecutor as AWS

Traffic flow with NGFW:
  Range VM → NGFW Service (ClusterIP) → NGFW VM → Internet (via Cloud NAT)

Without NGFW:
  Range VM → Internet (via Cloud NAT directly)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

NGFW_IMAGE_ENV = "KUBEVIRT_NGFW_IMAGE"
NGFW_CPU_CORES = 4
NGFW_MEMORY = "8Gi"


def _get_ngfw_namespace(user_id: int) -> str:
    """Build the NGFW namespace for a user.

    Each user gets one NGFW that persists across ranges.
    """
    return f"ngfw-user-{user_id}"


def provision_ngfw_gcp(
    request_id: str,
    user_id: int,
    ngfw_instance_id: int,
) -> dict[str, Any]:
    """Provision a VM-Series NGFW as a KubeVirt VM.

    Creates:
    - Dedicated namespace for the user's NGFW
    - KubeVirt VM running VM-Series from containerDisk image
    - ClusterIP Service exposing the NGFW data interface
    - Waits for VM to boot, then runs NGFW provision plan via SSH

    Args:
        request_id: UUID of the provisioning request.
        user_id: Owner's Django user ID.
        ngfw_instance_id: DB ID of the NGFW Instance record.

    Returns:
        Dict with management_ip, service_ip, vm_name, namespace.
    """
    from executors.kubevirt_executor import KubeVirtExecutor
    from gcp_provision import _generate_ssh_keypair, _store_ssh_key_in_secret_manager

    executor = KubeVirtExecutor()
    namespace = _get_ngfw_namespace(user_id)

    ngfw_image = os.environ.get(NGFW_IMAGE_ENV, "")
    if not ngfw_image:
        raise ValueError(f"{NGFW_IMAGE_ENV} environment variable not set")

    logger.info(
        "provision_ngfw_gcp: request_id=%s user_id=%d namespace=%s",
        request_id,
        user_id,
        namespace,
    )

    # Create namespace
    ns_result = executor.create_namespace(
        namespace,
        labels={
            "shifter-component": "ngfw",
            "shifter-user-id": str(user_id),
            "shifter-request-id": request_id,
        },
    )
    if not ns_result.success:
        raise RuntimeError(f"Failed to create NGFW namespace: {ns_result.stderr}")

    # Generate SSH keypair
    ssh_private_key, ssh_public_key = _generate_ssh_keypair()
    ssh_key_secret_ref = _store_ssh_key_in_secret_manager(f"ngfw-{request_id}", ssh_private_key)

    # Create NGFW VM
    vm_name = f"ngfw-{user_id}"
    cloud_init = f"""#cloud-config
hostname: {vm_name}
ssh_authorized_keys:
  - {ssh_public_key}
"""

    create_result = executor.create_vm(
        namespace=namespace,
        name=vm_name,
        image=ngfw_image,
        cpu_cores=NGFW_CPU_CORES,
        memory=NGFW_MEMORY,
        labels={
            "shifter-component": "ngfw",
            "shifter-user-id": str(user_id),
            "app": "ngfw",
        },
        cloud_init=cloud_init,
    )
    if not create_result.success:
        raise RuntimeError(f"Failed to create NGFW VM: {create_result.stderr}")

    # Wait for NGFW to boot
    wait_result = executor.wait_for_running(vm_name, namespace, timeout_seconds=900)
    if not wait_result.success:
        raise RuntimeError(f"NGFW VM failed to start: {wait_result.stderr}")

    # Get NGFW IP
    describe_result = executor.describe_instance(vm_name, namespace)
    if not describe_result.success:
        raise RuntimeError(f"Failed to describe NGFW VM: {describe_result.stderr}")
    vm_info = json.loads(describe_result.stdout)
    management_ip = vm_info.get("ip_address", "")

    # Create ClusterIP Service for the NGFW data interface
    # Range VMs will route egress through this service IP
    service_ip = _create_ngfw_service(namespace, vm_name)

    # Run NGFW provision plan (configure interfaces, zones, policies)
    logger.info("provision_ngfw_gcp: running NGFW provision plan on %s", management_ip)
    _run_ngfw_provision_plan(management_ip, ssh_private_key)

    result = {
        "management_ip": management_ip,
        "service_ip": service_ip,
        "vm_name": vm_name,
        "namespace": namespace,
        "ssh_key_secret_ref": ssh_key_secret_ref,
    }
    logger.info("provision_ngfw_gcp: completed %s", result)
    return result


def configure_range_ngfw_routing(
    range_namespace: str,
    ngfw_namespace: str,
    ngfw_service_ip: str,
    subnets: list[dict],
    range_id: int,
    ssh_private_key: str,
    ngfw_management_ip: str,
) -> None:
    """Wire range subnets to the user's NGFW.

    On GCP, this creates:
    1. A K8s NetworkPolicy in the range namespace allowing egress to the NGFW service
    2. PAN-OS address objects and security rules for the range subnets (via SSH)

    This is the GCP equivalent of configure_ngfw_subnets() in main.py.

    Args:
        range_namespace: K8s namespace of the range.
        ngfw_namespace: K8s namespace of the NGFW.
        ngfw_service_ip: ClusterIP of the NGFW data service.
        subnets: List of subnet specs with name, cidr, connected_to.
        range_id: Range ID for naming.
        ssh_private_key: PEM private key for NGFW SSH access.
        ngfw_management_ip: NGFW pod IP for SSH.
    """
    from kubernetes import client as k8s_client  # type: ignore[import-untyped]
    from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

    from executors.kubevirt_executor import _load_kube_config

    _load_kube_config()
    networking_client = k8s_client.NetworkingV1Api()

    # Create NetworkPolicy allowing egress from range namespace to NGFW namespace
    egress_policy = k8s_client.V1NetworkPolicy(
        metadata=k8s_client.V1ObjectMeta(
            name="allow-ngfw-egress",
            namespace=range_namespace,
        ),
        spec=k8s_client.V1NetworkPolicySpec(
            pod_selector=k8s_client.V1LabelSelector(),  # All pods in range
            policy_types=["Egress"],
            egress=[
                k8s_client.V1NetworkPolicyEgressRule(
                    to=[
                        k8s_client.V1NetworkPolicyPeer(
                            namespace_selector=k8s_client.V1LabelSelector(
                                match_labels={"shifter-component": "ngfw"},
                            ),
                        )
                    ],
                )
            ],
        ),
    )

    try:
        networking_client.create_namespaced_network_policy(
            namespace=range_namespace,
            body=egress_policy,
        )
        logger.info("Created NGFW egress policy in namespace=%s", range_namespace)
    except ApiException as e:
        if e.status != 409:
            logger.warning("Failed to create NGFW egress policy: %s", e)

    # Configure NGFW with range subnet rules via PAN-OS CLI
    _configure_ngfw_subnets(
        management_ip=ngfw_management_ip,
        ssh_private_key=ssh_private_key,
        subnets=subnets,
        range_id=range_id,
    )


def remove_range_ngfw_routing(
    range_namespace: str,
    range_id: int,
    ssh_private_key: str,
    ngfw_management_ip: str,
) -> None:
    """Remove range-specific NGFW configuration.

    Called during range destruction. Removes PAN-OS address objects and
    security rules for this range.

    Args:
        range_namespace: K8s namespace of the range.
        range_id: Range ID for naming.
        ssh_private_key: PEM private key for NGFW SSH access.
        ngfw_management_ip: NGFW pod IP for SSH.
    """
    from executors.ssh_executor import SSHExecutor
    from orchestrators.setup_orchestrator import SetupOrchestrator
    from plans.ngfw_reconcile import NGFWReconcilePlan

    logger.info(
        "remove_range_ngfw_routing: range_namespace=%s range_id=%d",
        range_namespace,
        range_id,
    )

    # Remove PAN-OS rules for this range
    try:
        ssh_exec = SSHExecutor(private_key=ssh_private_key, username="admin")
        orchestrator = SetupOrchestrator(executor=ssh_exec)

        # Use reconcile plan to clean up stale range-specific routes and rules
        plan = NGFWReconcilePlan()
        context = plan.get_context({"range_id": range_id, "action": "remove"})
        result = orchestrator.orchestrate(ngfw_management_ip, plan, context)
        if not result.success:
            logger.warning("NGFW rule removal failed (non-fatal): %s", result.error)
    except Exception as e:
        logger.warning("NGFW rule removal failed (non-fatal): %s", e)


def _create_ngfw_service(namespace: str, vm_name: str) -> str:
    """Create a ClusterIP Service for the NGFW data interface.

    Returns the assigned ClusterIP address.
    """
    from kubernetes import client as k8s_client  # type: ignore[import-untyped]
    from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

    from executors.kubevirt_executor import _load_kube_config

    _load_kube_config()
    core_client = k8s_client.CoreV1Api()

    service = k8s_client.V1Service(
        metadata=k8s_client.V1ObjectMeta(
            name="ngfw-data",
            namespace=namespace,
        ),
        spec=k8s_client.V1ServiceSpec(
            type="ClusterIP",
            selector={"app": "ngfw"},
            ports=[
                k8s_client.V1ServicePort(
                    name="data",
                    port=443,
                    target_port=443,
                    protocol="TCP",
                ),
            ],
        ),
    )

    try:
        created = core_client.create_namespaced_service(namespace=namespace, body=service)
        service_ip = created.spec.cluster_ip
        logger.info("Created NGFW Service: namespace=%s ip=%s", namespace, service_ip)
        return service_ip
    except ApiException as e:
        if e.status == 409:
            existing = core_client.read_namespaced_service(name="ngfw-data", namespace=namespace)
            return existing.spec.cluster_ip
        raise RuntimeError(f"Failed to create NGFW Service: {e}") from e


def _run_ngfw_provision_plan(management_ip: str, ssh_private_key: str) -> None:
    """Run the NGFW initial provision plan via SSH.

    Same PAN-OS CLI commands as AWS — configure interfaces, zones, profiles.
    """
    from executors.ssh_executor import SSHExecutor
    from orchestrators.setup_orchestrator import SetupOrchestrator
    from plans.ngfw_provision import NGFWProvisionPlan

    ssh_exec = SSHExecutor(private_key=ssh_private_key, username="admin")
    orchestrator = SetupOrchestrator(executor=ssh_exec)

    # Wait for PAN-OS SSH to become available (can take 3-5 minutes)
    logger.info("Waiting for PAN-OS SSH on %s...", management_ip)
    ssh_exec.wait_for_ready(management_ip, timeout_seconds=600)

    plan = NGFWProvisionPlan()
    context = plan.get_context({})
    result = orchestrator.orchestrate(management_ip, plan, context)
    if not result.success:
        raise RuntimeError(f"NGFW provision plan failed: {result.error}")
    logger.info("NGFW provision plan completed on %s", management_ip)


def _configure_ngfw_subnets(
    management_ip: str,
    ssh_private_key: str,
    subnets: list[dict],
    range_id: int,
) -> None:
    """Configure NGFW with range subnet routes and security rules.

    Same PAN-OS CLI commands as AWS — address objects, security rules,
    static routes. The only difference is the next-hop: on AWS it's the
    VPC gateway IP, on GCP it's the default gateway in the pod network.
    """
    from executors.ssh_executor import SSHExecutor
    from orchestrators.setup_orchestrator import SetupOrchestrator
    from plans.ngfw_configure_subnets import NGFWConfigureSubnetsPlan

    ssh_exec = SSHExecutor(private_key=ssh_private_key, username="admin")
    orchestrator = SetupOrchestrator(executor=ssh_exec)

    plan = NGFWConfigureSubnetsPlan()
    context = plan.get_context(
        {
            "subnets": subnets,
            "range_id": range_id,
            # On GCP, the NGFW pod has a default route to the pod network gateway.
            # PAN-OS static routes use this as next-hop.
            "vpc_gateway_ip": "10.4.0.1",  # GKE pod network default gateway
        }
    )
    result = orchestrator.orchestrate(management_ip, plan, context)
    if not result.success:
        raise RuntimeError(f"NGFW subnet configuration failed: {result.error}")
    logger.info("NGFW subnet configuration completed for range_id=%d", range_id)
