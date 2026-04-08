"""KubeVirt Executor for VM lifecycle operations on GKE.

KubeVirtExecutor provides a consistent interface for managing KubeVirt
VirtualMachine CRDs on a GKE cluster, analogous to AWSExecutor for EC2.

Operations:
- VM lifecycle: create_vm, delete_vm, start_instance, stop_instance
- VM status: wait_for_running, wait_for_stopped, describe_instance
- Namespace: create_namespace, delete_namespace
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from executors.base import CommandResult

logger = logging.getLogger(__name__)

# KubeVirt API group and version
KUBEVIRT_GROUP = "kubevirt.io"
KUBEVIRT_VERSION = "v1"
KUBEVIRT_VM_PLURAL = "virtualmachines"
KUBEVIRT_VMI_PLURAL = "virtualmachineinstances"

# Default timeouts
DEFAULT_WAIT_TIMEOUT = 600  # 10 minutes
POLL_INTERVAL = 10  # seconds


def _load_kube_config() -> None:
    """Load Kubernetes configuration (in-cluster or kubeconfig)."""
    from kubernetes import config as k8s_config  # type: ignore[import-untyped]

    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()


class KubeVirtExecutor:
    """Executor for KubeVirt VM operations via Kubernetes API.

    Manages VirtualMachine CRDs on GKE with KubeVirt operator installed.
    Uses the Kubernetes custom objects API since VirtualMachine is a CRD.
    """

    def __init__(self) -> None:
        _load_kube_config()
        self._custom_client: Any = None
        self._core_client: Any = None
        logger.info("KubeVirtExecutor initialized")

    @property
    def custom_client(self) -> Any:
        if self._custom_client is None:
            from kubernetes import client as k8s_client  # type: ignore[import-untyped]

            self._custom_client = k8s_client.CustomObjectsApi()
        return self._custom_client

    @property
    def core_client(self) -> Any:
        if self._core_client is None:
            from kubernetes import client as k8s_client  # type: ignore[import-untyped]

            self._core_client = k8s_client.CoreV1Api()
        return self._core_client

    # =========================================================================
    # Action Dispatcher (for OpsOrchestrator integration)
    # =========================================================================

    def execute_action(self, action: str, context: dict[str, Any]) -> CommandResult:
        """Execute a named action using context parameters.

        Matches AWSExecutor.execute_action() interface for OpsOrchestrator.

        Args:
            action: The action name (e.g., "start_instance", "stop_instance").
            context: Dict containing parameters for the action.

        Returns:
            CommandResult from the specific action method.
        """
        logger.debug("execute_action: action=%s context_keys=%s", action, list(context.keys()))

        action_map: dict[str, tuple[Callable[..., CommandResult], list[str]]] = {
            "start_instance": (self.start_instance, ["instance_id", "namespace"]),
            "stop_instance": (self.stop_instance, ["instance_id", "namespace"]),
            "wait_for_running": (self.wait_for_running, ["instance_id", "namespace"]),
            "wait_for_stopped": (self.wait_for_stopped, ["instance_id", "namespace"]),
            "describe_instance": (self.describe_instance, ["instance_id", "namespace"]),
        }

        if action not in action_map:
            logger.warning("execute_action: unknown action=%s", action)
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Unknown action: {action}",
            )

        method, param_keys = action_map[action]
        params = {}
        for key in param_keys:
            if key not in context:
                return CommandResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=f"Missing required parameter '{key}' for action '{action}'",
                )
            params[key] = context[key]

        return method(**params)

    # =========================================================================
    # Namespace Operations
    # =========================================================================

    def create_namespace(self, namespace: str, labels: dict[str, str] | None = None) -> CommandResult:
        """Create a Kubernetes namespace for range isolation.

        Args:
            namespace: Namespace name (typically range-{uuid}).
            labels: Optional labels for the namespace.

        Returns:
            CommandResult with success status.
        """
        from kubernetes import client as k8s_client  # type: ignore[import-untyped]
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        logger.debug("create_namespace: namespace=%s", namespace)
        try:
            ns_labels = {"app": "shifter", "component": "range"}
            if labels:
                ns_labels.update(labels)

            body = k8s_client.V1Namespace(
                metadata=k8s_client.V1ObjectMeta(name=namespace, labels=ns_labels),
            )
            self.core_client.create_namespace(body=body)
            logger.info("create_namespace: created namespace=%s", namespace)
            return CommandResult(success=True, exit_code=0, stdout=namespace, stderr="")
        except ApiException as e:
            if e.status == 409:
                logger.info("create_namespace: already exists namespace=%s", namespace)
                return CommandResult(success=True, exit_code=0, stdout=namespace, stderr="")
            logger.error("create_namespace: failed namespace=%s error=%s", namespace, e)
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def delete_namespace(self, namespace: str) -> CommandResult:
        """Delete a namespace and all resources within it.

        This is the primary cleanup mechanism — deleting the namespace
        cascades to all VMs, services, network policies, etc.

        Args:
            namespace: Namespace to delete.

        Returns:
            CommandResult with success status.
        """
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        logger.debug("delete_namespace: namespace=%s", namespace)
        try:
            self.core_client.delete_namespace(name=namespace)
            logger.info("delete_namespace: deleted namespace=%s", namespace)
            return CommandResult(success=True, exit_code=0, stdout="", stderr="")
        except ApiException as e:
            if e.status == 404:
                logger.info("delete_namespace: not found namespace=%s", namespace)
                return CommandResult(success=True, exit_code=0, stdout="", stderr="")
            logger.error("delete_namespace: failed namespace=%s error=%s", namespace, e)
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    # =========================================================================
    # VM Lifecycle Operations
    # =========================================================================

    def create_vm(
        self,
        namespace: str,
        name: str,
        image: str,
        cpu_cores: int = 2,
        memory: str = "4Gi",
        disk_size: str = "20Gi",
        labels: dict[str, str] | None = None,
        cloud_init: str | None = None,
    ) -> CommandResult:
        """Create a KubeVirt VirtualMachine.

        Args:
            namespace: Kubernetes namespace.
            name: VM name.
            image: containerDisk image URI from Artifact Registry.
            cpu_cores: Number of CPU cores.
            memory: Memory allocation (e.g. "4Gi").
            disk_size: Root disk size.
            labels: Additional labels for the VM.
            cloud_init: Optional cloud-init userdata script.

        Returns:
            CommandResult with VM name in stdout.
        """
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        logger.debug("create_vm: namespace=%s name=%s image=%s", namespace, name, image)

        vm_labels = {"app": "shifter", "component": "range-vm", "vm-name": name}
        if labels:
            vm_labels.update(labels)

        # Build the VirtualMachine manifest
        vm_spec: dict[str, Any] = {
            "apiVersion": f"{KUBEVIRT_GROUP}/{KUBEVIRT_VERSION}",
            "kind": "VirtualMachine",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": vm_labels,
            },
            "spec": {
                "running": True,
                "template": {
                    "metadata": {
                        "labels": vm_labels,
                    },
                    "spec": {
                        "domain": {
                            "cpu": {"cores": cpu_cores},
                            "memory": {"guest": memory},
                            "devices": {
                                "disks": [
                                    {
                                        "name": "rootdisk",
                                        "disk": {"bus": "virtio"},
                                    },
                                ],
                                "interfaces": [
                                    {
                                        "name": "default",
                                        "masquerade": {},
                                    },
                                ],
                            },
                            "machine": {"type": "q35"},
                        },
                        "networks": [
                            {
                                "name": "default",
                                "pod": {},
                            },
                        ],
                        "volumes": [
                            {
                                "name": "rootdisk",
                                "containerDisk": {"image": image},
                            },
                        ],
                        "tolerations": [
                            {
                                "key": "kubevirt.io/schedulable",
                                "operator": "Equal",
                                "value": "true",
                                "effect": "NoSchedule",
                            },
                        ],
                    },
                },
            },
        }

        # Add cloud-init volume if provided
        if cloud_init:
            vm_spec["spec"]["template"]["spec"]["volumes"].append(
                {
                    "name": "cloudinit",
                    "cloudInitNoCloud": {"userData": cloud_init},
                }
            )
            vm_spec["spec"]["template"]["spec"]["domain"]["devices"]["disks"].append(
                {
                    "name": "cloudinit",
                    "disk": {"bus": "virtio"},
                }
            )

        try:
            self.custom_client.create_namespaced_custom_object(
                group=KUBEVIRT_GROUP,
                version=KUBEVIRT_VERSION,
                namespace=namespace,
                plural=KUBEVIRT_VM_PLURAL,
                body=vm_spec,
            )
            logger.info("create_vm: created vm=%s namespace=%s", name, namespace)
            return CommandResult(success=True, exit_code=0, stdout=name, stderr="")
        except ApiException as e:
            logger.error("create_vm: failed vm=%s namespace=%s error=%s", name, namespace, e)
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def delete_vm(self, namespace: str, name: str) -> CommandResult:
        """Delete a KubeVirt VirtualMachine.

        Args:
            namespace: Kubernetes namespace.
            name: VM name.

        Returns:
            CommandResult with success status.
        """
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        logger.debug("delete_vm: namespace=%s name=%s", namespace, name)
        try:
            self.custom_client.delete_namespaced_custom_object(
                group=KUBEVIRT_GROUP,
                version=KUBEVIRT_VERSION,
                namespace=namespace,
                plural=KUBEVIRT_VM_PLURAL,
                name=name,
            )
            logger.info("delete_vm: deleted vm=%s namespace=%s", name, namespace)
            return CommandResult(success=True, exit_code=0, stdout="", stderr="")
        except ApiException as e:
            if e.status == 404:
                logger.info("delete_vm: not found vm=%s namespace=%s", name, namespace)
                return CommandResult(success=True, exit_code=0, stdout="", stderr="")
            logger.error("delete_vm: failed vm=%s namespace=%s error=%s", name, namespace, e)
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def start_instance(self, instance_id: str, namespace: str) -> CommandResult:
        """Start a stopped KubeVirt VM by setting spec.running=True.

        Args:
            instance_id: VM name (KubeVirt uses name, not opaque IDs).
            namespace: Kubernetes namespace.

        Returns:
            CommandResult with success status.
        """
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        logger.debug("start_instance: vm=%s namespace=%s", instance_id, namespace)
        try:
            patch = {"spec": {"running": True}}
            self.custom_client.patch_namespaced_custom_object(
                group=KUBEVIRT_GROUP,
                version=KUBEVIRT_VERSION,
                namespace=namespace,
                plural=KUBEVIRT_VM_PLURAL,
                name=instance_id,
                body=patch,
            )
            logger.info("start_instance: started vm=%s namespace=%s", instance_id, namespace)
            return CommandResult(success=True, exit_code=0, stdout=instance_id, stderr="")
        except ApiException as e:
            logger.error("start_instance: failed vm=%s error=%s", instance_id, e)
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def stop_instance(self, instance_id: str, namespace: str) -> CommandResult:
        """Stop a running KubeVirt VM by setting spec.running=False.

        Args:
            instance_id: VM name.
            namespace: Kubernetes namespace.

        Returns:
            CommandResult with success status.
        """
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        logger.debug("stop_instance: vm=%s namespace=%s", instance_id, namespace)
        try:
            patch = {"spec": {"running": False}}
            self.custom_client.patch_namespaced_custom_object(
                group=KUBEVIRT_GROUP,
                version=KUBEVIRT_VERSION,
                namespace=namespace,
                plural=KUBEVIRT_VM_PLURAL,
                name=instance_id,
                body=patch,
            )
            logger.info("stop_instance: stopped vm=%s namespace=%s", instance_id, namespace)
            return CommandResult(success=True, exit_code=0, stdout=instance_id, stderr="")
        except ApiException as e:
            logger.error("stop_instance: failed vm=%s error=%s", instance_id, e)
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def describe_instance(self, instance_id: str, namespace: str) -> CommandResult:
        """Get details of a KubeVirt VM and its VMI (running instance).

        Args:
            instance_id: VM name.
            namespace: Kubernetes namespace.

        Returns:
            CommandResult with JSON status in stdout containing:
            - vm_name, namespace, running (spec), phase (VMI actual status)
            - ip_address (from VMI status if running)
            - node (which GKE node the VM is scheduled on)
        """
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        logger.debug("describe_instance: vm=%s namespace=%s", instance_id, namespace)
        try:
            vm = self.custom_client.get_namespaced_custom_object(
                group=KUBEVIRT_GROUP,
                version=KUBEVIRT_VERSION,
                namespace=namespace,
                plural=KUBEVIRT_VM_PLURAL,
                name=instance_id,
            )

            result: dict[str, Any] = {
                "vm_name": instance_id,
                "namespace": namespace,
                "running": vm.get("spec", {}).get("running", False),
                "created": vm.get("metadata", {}).get("creationTimestamp"),
                "labels": vm.get("metadata", {}).get("labels", {}),
            }

            # Try to get the VMI (VirtualMachineInstance) for runtime state
            try:
                vmi = self.custom_client.get_namespaced_custom_object(
                    group=KUBEVIRT_GROUP,
                    version=KUBEVIRT_VERSION,
                    namespace=namespace,
                    plural=KUBEVIRT_VMI_PLURAL,
                    name=instance_id,
                )
                vmi_status = vmi.get("status", {})
                result["phase"] = vmi_status.get("phase", "Unknown")
                result["node"] = vmi_status.get("nodeName")

                # Extract IP address from VMI interfaces
                interfaces = vmi_status.get("interfaces", [])
                if interfaces:
                    result["ip_address"] = interfaces[0].get("ipAddress")
            except ApiException:
                # VMI doesn't exist (VM is stopped)
                result["phase"] = "Stopped"

            logger.debug("describe_instance: vm=%s result=%s", instance_id, result)
            return CommandResult(
                success=True,
                exit_code=0,
                stdout=json.dumps(result, default=str),
                stderr="",
            )
        except ApiException as e:
            if e.status == 404:
                return CommandResult(success=False, exit_code=-1, stdout="", stderr="VM not found")
            logger.error("describe_instance: failed vm=%s error=%s", instance_id, e)
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def wait_for_running(
        self,
        instance_id: str,
        namespace: str,
        timeout_seconds: int = DEFAULT_WAIT_TIMEOUT,
    ) -> CommandResult:
        """Wait for a KubeVirt VM to reach Running phase.

        Polls the VMI status until phase is "Running" or timeout.

        Args:
            instance_id: VM name.
            namespace: Kubernetes namespace.
            timeout_seconds: Maximum wait time.

        Returns:
            CommandResult with success=True if VM is running.
        """
        logger.debug(
            "wait_for_running: vm=%s namespace=%s timeout=%d",
            instance_id,
            namespace,
            timeout_seconds,
        )
        return self._wait_for_phase(instance_id, namespace, "Running", timeout_seconds)

    def wait_for_stopped(
        self,
        instance_id: str,
        namespace: str,
        timeout_seconds: int = DEFAULT_WAIT_TIMEOUT,
    ) -> CommandResult:
        """Wait for a KubeVirt VM to stop (VMI deleted).

        Args:
            instance_id: VM name.
            namespace: Kubernetes namespace.
            timeout_seconds: Maximum wait time.

        Returns:
            CommandResult with success=True if VM is stopped.
        """
        logger.debug(
            "wait_for_stopped: vm=%s namespace=%s timeout=%d",
            instance_id,
            namespace,
            timeout_seconds,
        )
        return self._wait_for_phase(instance_id, namespace, "Stopped", timeout_seconds)

    def _wait_for_phase(
        self,
        instance_id: str,
        namespace: str,
        target_phase: str,
        timeout_seconds: int,
    ) -> CommandResult:
        """Poll VMI status until target phase or timeout.

        Args:
            instance_id: VM name.
            namespace: Kubernetes namespace.
            target_phase: "Running" or "Stopped".
            timeout_seconds: Maximum wait time.

        Returns:
            CommandResult with success if phase reached.
        """
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            try:
                vmi = self.custom_client.get_namespaced_custom_object(
                    group=KUBEVIRT_GROUP,
                    version=KUBEVIRT_VERSION,
                    namespace=namespace,
                    plural=KUBEVIRT_VMI_PLURAL,
                    name=instance_id,
                )
                phase = vmi.get("status", {}).get("phase", "Unknown")

                if target_phase == "Running" and phase == "Running":
                    logger.info("wait_for_phase: vm=%s reached Running", instance_id)
                    return CommandResult(success=True, exit_code=0, stdout=phase, stderr="")

                if phase == "Failed":
                    logger.error("wait_for_phase: vm=%s entered Failed phase", instance_id)
                    return CommandResult(
                        success=False,
                        exit_code=-1,
                        stdout="",
                        stderr=f"VM {instance_id} entered Failed phase",
                    )

                logger.debug("wait_for_phase: vm=%s phase=%s waiting for %s", instance_id, phase, target_phase)

            except ApiException as e:
                if e.status == 404 and target_phase == "Stopped":
                    logger.info("wait_for_phase: vm=%s VMI gone (stopped)", instance_id)
                    return CommandResult(success=True, exit_code=0, stdout="Stopped", stderr="")
                if e.status != 404:
                    logger.error("wait_for_phase: API error vm=%s error=%s", instance_id, e)

            time.sleep(POLL_INTERVAL)

        logger.error(
            "wait_for_phase: timeout vm=%s target=%s after %ds",
            instance_id,
            target_phase,
            timeout_seconds,
        )
        return CommandResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=f"Timeout waiting for VM {instance_id} to reach {target_phase}",
        )

    # =========================================================================
    # Utility
    # =========================================================================

    def list_vms(self, namespace: str) -> CommandResult:
        """List all VirtualMachines in a namespace.

        Args:
            namespace: Kubernetes namespace.

        Returns:
            CommandResult with JSON list of VM summaries in stdout.
        """
        from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

        logger.debug("list_vms: namespace=%s", namespace)
        try:
            vms = self.custom_client.list_namespaced_custom_object(
                group=KUBEVIRT_GROUP,
                version=KUBEVIRT_VERSION,
                namespace=namespace,
                plural=KUBEVIRT_VM_PLURAL,
            )
            summaries = []
            for vm in vms.get("items", []):
                summaries.append(
                    {
                        "name": vm["metadata"]["name"],
                        "running": vm.get("spec", {}).get("running", False),
                        "created": vm["metadata"].get("creationTimestamp"),
                        "labels": vm["metadata"].get("labels", {}),
                    }
                )
            return CommandResult(
                success=True,
                exit_code=0,
                stdout=json.dumps(summaries, default=str),
                stderr="",
            )
        except ApiException as e:
            logger.error("list_vms: failed namespace=%s error=%s", namespace, e)
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))
