"""GCP range provisioner — creates KubeVirt VMs on GKE.

Replaces the Terraform-based AWS provisioner flow:
- Creates a K8s namespace per range (isolation)
- Creates KubeVirt VirtualMachine CRDs from containerDisk images
- Generates SSH keypair, injects public key via cloud-init
- Runs setup plans (bootstrap, XDR agent, domain join) via SSH
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


def _generate_ssh_keypair() -> tuple[str, str]:
    """Generate an Ed25519 SSH keypair for range VM access.

    Returns:
        Tuple of (private_key_pem, public_key_openssh).
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_key = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode("utf-8")
    )
    return private_pem, public_key


def _store_ssh_key_in_secret_manager(
    request_id: str,
    private_key: str,
) -> str:
    """Store the range SSH private key in GCP Secret Manager.

    Args:
        request_id: Request UUID (used in secret name).
        private_key: PEM-encoded private key.

    Returns:
        Secret resource name (projects/PROJECT/secrets/NAME).
    """
    # Use the google-cloud-secret-manager SDK directly for creation
    # (the SecretsStore protocol only defines get_secret, not create).
    from google.cloud import secretmanager  # type: ignore[attr-defined]

    project = os.environ.get("GCP_PROJECT_ID", "")
    client = secretmanager.SecretManagerServiceClient()
    secret_id = f"range-ssh-{request_id[:12]}"
    parent = f"projects/{project}"

    try:
        secret = client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}},
            }
        )
    except Exception as e:
        if "ALREADY_EXISTS" in str(e):
            secret_name = f"{parent}/secrets/{secret_id}"
        else:
            raise
    else:
        secret_name = secret.name

    client.add_secret_version(
        request={
            "parent": secret_name,
            "payload": {"data": private_key.encode("utf-8")},
        }
    )
    logger.info("Stored SSH key in Secret Manager: %s", secret_name)
    return secret_name


def _build_cloud_init_userdata(
    public_key: str,
    hostname: str,
    ssh_user: str = "ubuntu",
) -> str:
    """Build minimal cloud-init userdata for SSH key injection.

    Only handles SSH key setup so the provisioner can connect.
    All other configuration (XDR agent, domain join, etc.) runs via SSH
    after boot to support CyberScript-driven dynamic composition.

    Args:
        public_key: SSH public key (OpenSSH format).
        hostname: VM hostname.
        ssh_user: SSH user to configure (ubuntu, kali, etc.).

    Returns:
        cloud-init userdata string.
    """
    return f"""#cloud-config
hostname: {hostname}
manage_etc_hosts: true
ssh_authorized_keys:
  - {public_key}
users:
  - default
  - name: {ssh_user}
    ssh_authorized_keys:
      - {public_key}
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
"""


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
        # Step 0: Generate SSH keypair for this range
        logger.info("provision_range_gcp: generating SSH keypair")
        ssh_private_key, ssh_public_key = _generate_ssh_keypair()

        # Store private key in Secret Manager
        ssh_key_secret_ref = _store_ssh_key_in_secret_manager(request_id, ssh_private_key)

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

                # Determine SSH user for this OS
                ssh_user = "kali" if os_type == "kali" else "ubuntu"
                cloud_init = _build_cloud_init_userdata(
                    public_key=ssh_public_key,
                    hostname=vm_name,
                    ssh_user=ssh_user,
                )

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
                        "cloud_init": cloud_init,
                        "ssh_user": ssh_user,
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
                cloud_init=vm_spec.get("cloud_init"),
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

            instances_output.append(
                {
                    "uuid": vm_spec["uuid"],
                    "name": vm_spec["name"],
                    "role": vm_spec["role"],
                    "os": vm_spec["os_type"],
                    "instance_id": vm_spec["vm_name"],
                    "private_ip": vm_info.get("ip_address", ""),
                    "public_key": ssh_public_key,
                    "hostname": vm_spec["vm_name"],
                    "subnet_name": vm_spec["subnet_name"],
                    "ssh_key_secret_arn": ssh_key_secret_ref,
                    "ssh_user": vm_spec.get("ssh_user", "ubuntu"),
                    # GCP-specific state fields
                    "vm_name": vm_spec["vm_name"],
                    "namespace": namespace,
                    "node": vm_info.get("node", ""),
                }
            )

        # Step 5: Create NetworkPolicy for subnet isolation
        _create_network_policies(executor, namespace, subnets)

        # Step 6: Run instance setup plans via SSH
        logger.info(
            "provision_range_gcp: running setup plans for %d instances",
            len(instances_output),
        )
        _run_gcp_instance_setup(
            instances_output=instances_output,
            range_spec=range_spec,
            ssh_private_key=ssh_private_key,
            range_id=range_id,
        )

        # Step 8: Write state to DB
        logger.info(
            "provision_range_gcp: writing state to DB range_id=%d instances=%d",
            range_id,
            len(instances_output),
        )
        _write_gcp_provisioned_state(range_id, namespace, subnets_output, instances_output)

        # Step 9: Update range status and publish ready event
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


def _run_gcp_instance_setup(
    instances_output: list[dict],
    range_spec: dict[str, Any],
    ssh_private_key: str,
    range_id: int = 0,
) -> None:
    """Run setup plans on provisioned VMs via SSH.

    Same logic as run_instance_setup() in main.py but uses GenericSSHExecutor
    instead of SSMExecutor. DC setup runs first (blocking), then other
    instances in parallel.

    Args:
        instances_output: List of instance dicts with private_ip, role, os, etc.
        range_spec: Range spec with subnet/instance configs.
        ssh_private_key: PEM private key for SSH access.
        range_id: Range ID for hostname generation.
    """
    from executors.generic_ssh_executor import GenericSSHExecutor
    from main import SetupError, get_agent_presigned_url
    from orchestrators.setup_orchestrator import SetupOrchestrator
    from plans.bootstrap import BootstrapPlan
    from plans.domain_join import DomainJoinPlan
    from plans.linux_bootstrap import LinuxBootstrapPlan
    from plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan
    from plans.xdr_agent_install import XDRAgentInstallPlan

    # Build UUID -> config lookup from spec
    uuid_to_config: dict[str, dict] = {}
    for subnet in range_spec.get("subnets", []):
        for inst in subnet.get("instances", []):
            uuid_to_config[inst.get("uuid", "")] = inst

    # Separate DCs from other instances
    dc_instances = [i for i in instances_output if i.get("role") == "dc"]
    other_instances = [i for i in instances_output if i.get("role") != "dc"]

    def _setup_single(inst: dict, dc_ip: str | None = None, domain_name: str | None = None) -> None:
        """Run setup plans for a single instance via SSH."""
        ip = inst["private_ip"]
        role = inst.get("role", "victim")
        os_type = inst.get("os", "ubuntu")
        ssh_user = inst.get("ssh_user", "kali" if os_type == "kali" else "ubuntu")
        inst_uuid = inst.get("uuid", "")
        inst_config = uuid_to_config.get(inst_uuid, {})
        hostname = inst.get("hostname", inst.get("vm_name", ""))
        public_key = inst.get("public_key", "")
        agent_url = get_agent_presigned_url(inst_config) or ""
        xdr_required = bool(inst_config.get("agent"))

        ssh_exec = GenericSSHExecutor(
            private_key=ssh_private_key,
            username=ssh_user,
        )

        # Wait for SSH to become available
        logger.info("Waiting for SSH on %s (%s)...", inst.get("vm_name"), ip)
        ssh_exec.wait_for_ready(ip, timeout_seconds=300)

        orchestrator = SetupOrchestrator(executor=ssh_exec)

        # Context object for plan.get_context()
        class InstanceCtx:
            pass

        ctx = InstanceCtx()
        ctx.hostname = hostname  # type: ignore[attr-defined]
        ctx.public_key = public_key  # type: ignore[attr-defined]
        ctx.ssh_user = ssh_user  # type: ignore[attr-defined]
        ctx.agent_presigned_url = agent_url  # type: ignore[attr-defined]

        if role == "attacker":
            plan = LinuxBootstrapPlan()
            context = plan.get_context(ctx)
            result = orchestrator.orchestrate(ip, plan, context)
            if not result.success:
                raise SetupError(f"Attacker setup failed on {ip}: {result.error}")

        elif role == "victim":
            if os_type in ("kali", "ubuntu"):
                # Linux bootstrap
                plan = LinuxBootstrapPlan()
                context = plan.get_context(ctx)
                result = orchestrator.orchestrate(ip, plan, context)
                if not result.success:
                    raise SetupError(f"Linux bootstrap failed on {ip}: {result.error}")

                # XDR agent install
                if agent_url:
                    xdr_plan = LinuxXDRAgentInstallPlan()
                    xdr_ctx = xdr_plan.get_context({"agent_presigned_url": agent_url})
                    result = orchestrator.orchestrate(ip, xdr_plan, xdr_ctx)
                    if not result.success:
                        raise SetupError(f"XDR install failed on {ip}: {result.error}")
                elif xdr_required:
                    raise SetupError(f"XDR required but no URL for {ip}")

            else:
                # Windows bootstrap (connect as Administrator)
                win_exec = GenericSSHExecutor(
                    private_key=ssh_private_key,
                    username="Administrator",
                )
                win_orchestrator = SetupOrchestrator(executor=win_exec)

                win_plan = BootstrapPlan()
                win_ctx = win_plan.get_context(ctx)
                result = win_orchestrator.orchestrate(ip, win_plan, win_ctx)
                if not result.success:
                    raise SetupError(f"Windows bootstrap failed on {ip}: {result.error}")

                # XDR agent
                if agent_url:
                    xdr_plan = XDRAgentInstallPlan()
                    xdr_ctx = xdr_plan.get_context({"agent_presigned_url": agent_url})
                    result = win_orchestrator.orchestrate(ip, xdr_plan, xdr_ctx)
                    if not result.success:
                        raise SetupError(f"Windows XDR install failed on {ip}: {result.error}")
                elif xdr_required:
                    raise SetupError(f"XDR required but no URL for {ip}")

                # Domain join
                if inst_config.get("join_domain") and dc_ip and domain_name:
                    join_plan = DomainJoinPlan()
                    join_ctx = join_plan.get_context({"dc_ip": dc_ip, "domain_name": domain_name})
                    result = win_orchestrator.orchestrate(ip, join_plan, join_ctx)
                    if not result.success:
                        raise SetupError(f"Domain join failed on {ip}: {result.error}")

        elif role == "dc":
            # DC verification only — AD is pre-promoted in the image
            from plans.dc_setup import DCSetupPlan

            win_exec = GenericSSHExecutor(
                private_key=ssh_private_key,
                username="Administrator",
            )
            win_orchestrator = SetupOrchestrator(executor=win_exec)
            dc_plan = DCSetupPlan()
            dc_config = inst_config.get("dc_config", {})
            dc_ctx = dc_plan.get_context(dc_config)
            result = win_orchestrator.orchestrate(ip, dc_plan, dc_ctx)
            if not result.success:
                raise SetupError(f"DC setup failed on {ip}: {result.error}")

        logger.info("Setup complete for %s (%s, role=%s)", inst.get("vm_name"), ip, role)

    # Run DC setup first (blocking) — must complete before domain joins
    actual_dc_ip = None
    actual_domain = None
    for dc_inst in dc_instances:
        _setup_single(dc_inst)
        actual_dc_ip = dc_inst.get("private_ip")
        dc_uuid = dc_inst.get("uuid", "")
        dc_config = uuid_to_config.get(dc_uuid, {}).get("dc_config", {})
        actual_domain = dc_config.get("domain_name")

    # Run other instances in parallel
    if other_instances:
        logger.info("Running setup for %d non-DC instances in parallel", len(other_instances))

        def _setup_worker(inst: dict) -> tuple[str, bool, str]:
            try:
                _setup_single(inst, dc_ip=actual_dc_ip, domain_name=actual_domain)
                return (inst.get("vm_name", ""), True, "")
            except Exception as e:
                return (inst.get("vm_name", ""), False, str(e))

        with ThreadPoolExecutor(max_workers=min(len(other_instances), 10)) as pool:
            futures = {pool.submit(_setup_worker, inst): inst for inst in other_instances}
            for future in as_completed(futures):
                vm_name, success, error = future.result()
                if not success:
                    raise SetupError(f"Instance {vm_name} setup failed: {error}")

    logger.info("All GCP instance setup complete")


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
