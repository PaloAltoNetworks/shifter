"""Guest SSH transport that runs from inside the GDC range cluster.

GDC VM Runtime range VMs live on an isolated L2 (macvlan) segment on the
bare-metal range cluster; the platform-plane provisioner (a separate GKE
cluster) has no L3 route to those VM IPs, so direct SSH from the provisioner
process times out. This executor preserves range isolation by running the
exact same ssh invocation from a small "setup-runner" pod created inside the
range namespace and attached to the range NAD (whereabouts auto-assigns it a
non-reserved IP on the segment, giving it L2 reachability to the guests). The
provisioner drives ssh via ``kubectl exec`` (the Kubernetes pod-exec stream).

The per-instance private key and each command's script are delivered to the
runner base64-encoded and decoded to runner-local files; ssh reads the script
from a runner-local file (``ssh ... < file``) so the *guest* never sees script
contents (which may carry secrets) on its argv. The runner is an ephemeral,
single-tenant helper in the isolated range namespace, reclaimed with the range
namespace on teardown.
"""

from __future__ import annotations

import base64
import json
import logging
import shlex
import time
import uuid
from types import ModuleType
from typing import TYPE_CHECKING, Any

from executors.guest_ssh_executor import GuestSSHConnectionError, GuestSSHExecutor, TimeoutError

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api
    from kubernetes.client.exceptions import ApiException
    from kubernetes.stream.ws_client import WSClient

logger = logging.getLogger(__name__)

_SHELL = "/bin/sh"
_NETWORKS_ANNOTATION = "k8s.v1.cni.cncf.io/networks"
_NETWORK_STATUS_ANNOTATION = "k8s.v1.cni.cncf.io/network-status"
_RUNNER_CONTAINER = "runner"
_RUNNER_POD_NAME = "shifter-setup-runner"
_RUNNER_READY_TIMEOUT_SECONDS = 180
_RUNNER_POLL_INTERVAL_SECONDS = 5
_MANAGED_BY_LABEL = "shifter-provisioner"
_PULL_SECRET_NAME = "shifter-runner-pull"  # noqa: S105  # nosec B105 - k8s Secret object name, not a credential
# Registry hosts that need GCP credentials to pull. The isolated range cluster
# can pull public registries (e.g. docker.io) anonymously but has no native
# identity for Artifact Registry / GCR, so those get a minted-token pull secret.
_GCP_REGISTRY_SUFFIXES = ("docker.pkg.dev", "gcr.io")


class RangePodSSHExecutor(GuestSSHExecutor):
    """Run guest setup ssh from a pod inside the range cluster (L2-adjacent)."""

    def __init__(
        self,
        *,
        core_api: CoreV1Api,
        client_module: ModuleType,
        api_exception: type[ApiException],
        namespace: str,
        network_name: str,
        runner_image: str,
        private_key: str,
        username: str,
        port: int = GuestSSHExecutor.DEFAULT_SSH_PORT,
        poll_interval_seconds: int = 10,
        connect_timeout_seconds: int = 10,
        runner_pod_name: str = _RUNNER_POD_NAME,
        host_public_key: str | None = None,
        known_hosts_host: str | None = None,
    ) -> None:
        if not namespace or not network_name:
            raise ValueError("RangePodSSHExecutor requires range namespace and network_name")
        if not runner_image:
            raise ValueError("RangePodSSHExecutor requires a runner image (GDC_SETUP_RUNNER_IMAGE)")
        self._core_api = core_api
        self._client_module = client_module
        self._api_exception = api_exception
        self._namespace = namespace
        self._network_name = network_name
        self._runner_image = runner_image
        self._runner_pod_name = runner_pod_name
        self._private_key_material = private_key
        self._runner_ready = False
        self._key_planted = False
        self._pull_secret_name: str | None = None
        # Set by _provision_known_hosts (called from super().__init__) when a
        # host key is supplied; the content is planted on the runner lazily.
        self._known_hosts_content = ""
        self._known_hosts_planted = False
        super().__init__(
            private_key=private_key,
            username=username,
            port=port,
            poll_interval_seconds=poll_interval_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            host_public_key=host_public_key,
            known_hosts_host=known_hosts_host,
        )

    def _provision_key(self, private_key: str) -> str:
        """The key lives on the runner pod; return a unique in-pod path.

        Planting is deferred to first use (the runner pod may not exist yet).
        A per-executor unique path keeps concurrent per-instance setups from
        clobbering one another on the shared runner.
        """
        # Path is inside the range runner pod's ephemeral filesystem, not the local host.
        return f"/tmp/shifter-guest-key-{uuid.uuid4().hex}.pem"  # noqa: S108  # nosec  # NOSONAR

    def _provision_known_hosts(self, host: str, host_public_key: str) -> str:
        """The known_hosts lives on the runner pod; return a unique in-pod path.

        The content is captured here and planted on first use (the runner pod
        may not exist yet), mirroring the deferred key-planting flow.
        """
        self._known_hosts_content = self._known_hosts_line(host, host_public_key)
        # Path is inside the range runner pod's ephemeral filesystem, not the local host.
        return f"/tmp/shifter-known-hosts-{uuid.uuid4().hex}"  # noqa: S108  # nosec  # NOSONAR

    # -- runner pod lifecycle -------------------------------------------------

    def _runner_networks_annotation(self) -> str:
        # No explicit ip -> whereabouts auto-assigns a non-reserved address on
        # the range segment (VM IPs and gateway are in the NAD exclude list).
        return json.dumps([{"name": self._network_name, "interface": "net1"}])

    def _build_runner_manifest(self) -> dict[str, Any]:
        spec = {
            "enableServiceLinks": False,
            "restartPolicy": "Always",
            "containers": [
                {
                    "name": _RUNNER_CONTAINER,
                    "image": self._runner_image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": [_SHELL, "-c"],
                    "args": ["trap : TERM INT; while true; do sleep 3600; done"],
                }
            ],
        }
        if self._pull_secret_name:
            spec["imagePullSecrets"] = [{"name": self._pull_secret_name}]
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": self._runner_pod_name,
                "namespace": self._namespace,
                "labels": {
                    "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
                    "shifter.dev/role": "setup-runner",
                },
                "annotations": {_NETWORKS_ANNOTATION: self._runner_networks_annotation()},
            },
            "spec": spec,
        }

    # -- image pull credentials ----------------------------------------------

    def _registry_host(self) -> str:
        return self._runner_image.split("/", 1)[0]

    def _registry_needs_credentials(self) -> bool:
        # AR hosts are "<region>-docker.pkg.dev" (hyphen before the suffix);
        # GCR hosts are "gcr.io" / "<region>.gcr.io" (dot or exact).
        host = self._registry_host()
        return any(
            host == suffix or host.endswith("." + suffix) or host.endswith("-" + suffix)
            for suffix in _GCP_REGISTRY_SUFFIXES
        )

    def _mint_registry_token(self) -> str:
        """Mint a short-lived OAuth2 access token from the provisioner's ADC.

        The provision Job runs under the ``provisioner`` Workload Identity,
        which holds ``roles/artifactregistry.reader``; the kubelet presents this
        token to Artifact Registry as the ``oauth2accesstoken`` user. Isolated as
        a seam so tests need not touch real Google credentials.
        """
        import google.auth
        from google.auth.transport.requests import Request as GoogleAuthRequest

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(GoogleAuthRequest())
        if not creds.token:
            raise GuestSSHConnectionError("Failed to mint Artifact Registry access token for setup-runner pull")
        return creds.token

    def _ensure_pull_secret(self) -> None:
        """Plant a dockerconfigjson pull secret in the range namespace if needed."""
        if self._pull_secret_name is not None or not self._registry_needs_credentials():
            return
        token = self._mint_registry_token()
        auth = base64.b64encode(f"oauth2accesstoken:{token}".encode()).decode("ascii")
        dockercfg = {
            "auths": {
                self._registry_host(): {
                    "username": "oauth2accesstoken",
                    "password": token,
                    "auth": auth,
                }
            }
        }
        data = base64.b64encode(json.dumps(dockercfg).encode()).decode("ascii")
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "kubernetes.io/dockerconfigjson",
            "metadata": {
                "name": _PULL_SECRET_NAME,
                "namespace": self._namespace,
                "labels": {"app.kubernetes.io/managed-by": _MANAGED_BY_LABEL},
            },
            "data": {".dockerconfigjson": data},
        }
        try:
            self._core_api.create_namespaced_secret(namespace=self._namespace, body=body)
        except self._api_exception as exc:
            if exc.status != 409:
                raise
            # Refresh the token on an existing secret (a prior range run may have
            # planted a now-expired token).
            self._core_api.patch_namespaced_secret(name=_PULL_SECRET_NAME, namespace=self._namespace, body=body)
        self._pull_secret_name = _PULL_SECRET_NAME

    def _runner_has_segment_ip(self, pod: dict[str, Any]) -> bool:
        annotations = (pod.get("metadata") or {}).get("annotations") or {}
        raw_status = annotations.get(_NETWORK_STATUS_ANNOTATION)
        if not raw_status:
            return False
        try:
            statuses = json.loads(raw_status)
        except json.JSONDecodeError:
            return False
        return any(isinstance(s, dict) and s.get("interface") == "net1" and (s.get("ips") or []) for s in statuses)

    def _ensure_runner(self) -> None:
        if self._runner_ready:
            return
        self._ensure_pull_secret()
        body = self._build_runner_manifest()
        try:
            self._core_api.create_namespaced_pod(namespace=self._namespace, body=body)
            logger.info(
                "Created GDC setup-runner pod %s/%s (image=%s)",
                self._namespace,
                self._runner_pod_name,
                self._runner_image,
            )
        except self._api_exception as exc:
            if exc.status != 409:
                raise
        self._wait_for_runner_ready()
        self._runner_ready = True

    def _wait_for_runner_ready(self) -> None:
        deadline = time.monotonic() + _RUNNER_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                pod = self._core_api.read_namespaced_pod(
                    name=self._runner_pod_name, namespace=self._namespace
                ).to_dict()
            except self._api_exception as exc:
                if exc.status == 404:
                    time.sleep(_RUNNER_POLL_INTERVAL_SECONDS)
                    continue
                raise
            phase = str(((pod.get("status") or {}).get("phase")) or "").lower()
            if phase == "running" and self._runner_has_segment_ip(pod):
                return
            if phase == "failed":
                raise GuestSSHConnectionError(
                    f"GDC setup-runner pod {self._namespace}/{self._runner_pod_name} entered phase=Failed"
                )
            time.sleep(_RUNNER_POLL_INTERVAL_SECONDS)
        raise GuestSSHConnectionError(
            f"GDC setup-runner pod {self._namespace}/{self._runner_pod_name} did not become ready"
        )

    def _ensure_key_planted(self) -> None:
        if self._key_planted:
            return
        key_b64 = base64.b64encode(self._private_key_material.encode()).decode("ascii")
        # umask 077 so the decoded key is private; written via base64 so the key
        # never appears verbatim in the pod filesystem write path.
        script = f"umask 077; printf %s {shlex.quote(key_b64)} | base64 -d > {shlex.quote(self._key_path)}"
        rc, _out, err = self._exec([_SHELL, "-c", script], timeout_seconds=30)
        if rc != 0:
            raise GuestSSHConnectionError(
                f"Failed to plant guest SSH key on runner pod (rc={rc}): {err.decode('utf-8', 'replace')}"
            )
        self._key_planted = True

    def _ensure_known_hosts_planted(self) -> None:
        if self._known_hosts_planted or not self._known_hosts_path:
            return
        kh_b64 = base64.b64encode(self._known_hosts_content.encode()).decode("ascii")
        script = f"printf %s {shlex.quote(kh_b64)} | base64 -d > {shlex.quote(self._known_hosts_path)}"
        rc, _out, err = self._exec([_SHELL, "-c", script], timeout_seconds=30)
        if rc != 0:
            raise GuestSSHConnectionError(
                f"Failed to plant known_hosts on runner pod (rc={rc}): {err.decode('utf-8', 'replace')}"
            )
        self._known_hosts_planted = True

    # -- transport seam -------------------------------------------------------

    def _invoke_ssh(self, ssh_args: list[str], command_input: bytes, timeout_seconds: int) -> tuple[int, bytes, bytes]:
        self._ensure_runner()
        self._ensure_key_planted()
        self._ensure_known_hosts_planted()
        script_b64 = base64.b64encode(command_input).decode("ascii")
        # Path is inside the range runner pod's ephemeral filesystem, not the local host.
        script_path = f"/tmp/shifter-cmd-{uuid.uuid4().hex}"  # noqa: S108  # nosec  # NOSONAR
        ssh_cmd = " ".join(shlex.quote(arg) for arg in ssh_args)
        # Deliver the command script to the guest via a runner-local file
        # (ssh ... < file) so the guest never sees script contents on its argv.
        wrapper = (
            f"printf %s {shlex.quote(script_b64)} | base64 -d > {shlex.quote(script_path)} || exit 250; "
            f"{ssh_cmd} < {shlex.quote(script_path)}; rc=$?; "
            f"rm -f {shlex.quote(script_path)}; exit $rc"
        )
        return self._exec([_SHELL, "-c", wrapper], timeout_seconds=timeout_seconds)

    def _exec(self, command: list[str], timeout_seconds: int) -> tuple[int, bytes, bytes]:
        from kubernetes.stream import stream

        resp = stream(
            self._core_api.connect_get_namespaced_pod_exec,
            self._runner_pod_name,
            self._namespace,
            command=command,
            container=_RUNNER_CONTAINER,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        out = bytearray()
        err = bytearray()
        deadline = time.monotonic() + timeout_seconds
        try:
            while resp.is_open():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"runner exec timed out after {timeout_seconds}s")
                resp.update(timeout=1)
                if resp.peek_stdout():
                    out += resp.read_stdout().encode("utf-8", "replace")
                if resp.peek_stderr():
                    err += resp.read_stderr().encode("utf-8", "replace")
            returncode = self._exec_returncode(resp)
        finally:
            resp.close()
        return returncode, bytes(out), bytes(err)

    @staticmethod
    def _exec_returncode(resp: WSClient) -> int:
        """Extract the remote command exit code from a closed exec stream."""
        rc = getattr(resp, "returncode", None)
        if isinstance(rc, int):
            return rc
        try:
            from kubernetes.stream.ws_client import ERROR_CHANNEL

            raw = resp.read_channel(ERROR_CHANNEL)
        except Exception:
            return 1
        return RangePodSSHExecutor._exit_code_from_error_status(raw)

    @staticmethod
    def _exit_code_from_error_status(raw: str | None) -> int:
        """Map a kubernetes exec ERROR_CHANNEL status payload to an exit code.

        Empty payload means success (0). A malformed or non-Success payload
        falls through to the ExitCode cause scan, which yields the generic
        failure code 1 when no explicit exit code is present.
        """
        if not raw:
            return 0
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
        status = parsed if isinstance(parsed, dict) else {}
        if status.get("status") == "Success":
            return 0
        return RangePodSSHExecutor._exit_code_from_causes(status)

    @staticmethod
    def _exit_code_from_causes(status: dict[str, Any]) -> int:
        """Return the ExitCode cause value from a non-Success exec status, else 1."""
        for cause in (status.get("details") or {}).get("causes") or []:
            if cause.get("reason") == "ExitCode":
                try:
                    return int(cause.get("message", "1"))
                except (ValueError, TypeError):
                    return 1
        return 1
