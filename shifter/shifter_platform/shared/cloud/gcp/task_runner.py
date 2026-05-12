"""GKE-native Kubernetes Job adapter implementing TaskRunner protocol."""

from __future__ import annotations

import importlib
import logging
import os
import uuid
from typing import Any

from django.conf import settings

from shared.cloud import PROVISIONER_CONTAINER_NAME
from shared.cloud.exceptions import CloudTaskError
from shared.cloud.gcp.base import build_job_generate_name, parse_job_task_id
from shared.cloud.sensitive_env import split_env

__all__ = ("PROVISIONER_CONTAINER_NAME", "GCPTaskRunner")

logger = logging.getLogger(__name__)

_PROVISIONER_RUN_AS_UID = 1000
_PROVISIONER_RUN_AS_GID = 1000

# Memory-backed workspace volume size cap. Terraform staging trees are tiny
# (a few MB), but a runaway plan log or provider download could otherwise
# consume node memory unbounded. 256Mi is generous for the staged terraform/
# tree plus typical plan output without putting the node under pressure.
_PROVISIONER_WORKSPACE_SIZE_LIMIT = "256Mi"

# Writable mount points the provisioner image needs at runtime. /app and the
# rest of the root filesystem are read-only (issue #1103); these explicit
# emptyDir volumes are the only paths the runtime user can write to.
# - workspace: terraform_base._stage_workspace target. Memory-backed (medium=Memory)
#   so terraform.tfvars.json (which can carry secrets) does not persist on disk;
#   capped at _PROVISIONER_WORKSPACE_SIZE_LIMIT to bound the worst-case node memory
#   pressure from a runaway plan log or large provider download.
# - /tmp: Python tempfile, kubectl temp kubeconfigs (gdc_*), etc.
# - tf plugin cache and pulumi home: Terraform/Pulumi tool state under HOME.
_PROVISIONER_WRITABLE_MOUNTS: tuple[tuple[str, str, str | None, str | None], ...] = (
    ("provisioner-workspace", "/var/run/provisioner/workspace", "Memory", _PROVISIONER_WORKSPACE_SIZE_LIMIT),
    ("tmp", "/tmp", None, None),  # noqa: S108 # nosec B108 — Kubernetes mount path, not a tempfile API call
    ("tf-plugin-cache", "/home/appuser/.terraform.d/plugin-cache", None, None),
    ("pulumi-home", "/home/appuser/.pulumi", None, None),
)


def _is_provisioner_task(container_name: str) -> bool:
    """Return True if the Job being built is the provisioner task.

    Hardening from issue #1103 (read-only root filesystem, writable workspace
    volume, drop-ALL capabilities, etc.) is provisioner-specific. CMS
    experiments and any future shared-runner caller keep their current,
    less-prescribed contract until the runner protocol grows a per-task
    runtime profile parameter.
    """
    return container_name == PROVISIONER_CONTAINER_NAME


class GCPTaskRunner:
    """Kubernetes Job implementation of TaskRunner protocol.

    The generic TaskRunner interface remains ECS-shaped in existing call sites.
    For GCP:

    - ``cluster`` is interpreted as the Kubernetes namespace.
    - ``task_definition`` is interpreted as the container image to run.
    - ``command`` is passed as container args so the image ENTRYPOINT is kept.
    """

    def _load_kubernetes_api(self) -> tuple[Any, Any, Any, type[Exception]]:
        try:
            kubernetes = importlib.import_module("kubernetes")
        except ImportError as e:
            raise CloudTaskError("GCP task runner support requires kubernetes") from e

        config = kubernetes.config
        config_exception = getattr(getattr(config, "config_exception", None), "ConfigException", Exception)

        try:
            if os.environ.get("KUBERNETES_SERVICE_HOST"):
                try:
                    config.load_incluster_config()
                except config_exception:
                    config.load_kube_config()
            else:
                config.load_kube_config()
        except Exception as e:
            raise CloudTaskError(f"Failed to load Kubernetes client configuration: {e}") from e

        client = kubernetes.client
        api_exception = getattr(getattr(client, "exceptions", None), "ApiException", Exception)
        return client.BatchV1Api(), client.CoreV1Api(), client, api_exception

    def _build_env(
        self,
        client: Any,
        env_overrides: dict[str, str] | None,
        sensitive_secret_name: str | None = None,
    ) -> list[Any] | None:
        """Build the env-var list for the Job container.

        Issue #1185 — sensitive provisioner values must NOT appear as
        literal ``value=`` env vars on the Pod spec. They are routed
        through ``valueFrom.secretKeyRef`` pointing at an ephemeral
        per-Job Kubernetes Secret. ``sensitive_secret_name`` MUST be
        provided when any key in ``env_overrides`` classifies as
        sensitive (per ``sensitive_env.split_env``); the caller
        (``run_task``) creates the Secret before the Job is submitted.
        """
        if not env_overrides:
            return None
        sensitive, plain = split_env(env_overrides)
        if sensitive and not sensitive_secret_name:
            raise CloudTaskError("GCP task runner: sensitive env vars present but no Secret was created")
        entries: list[Any] = []
        for name, value in sorted(plain.items()):
            entries.append(client.V1EnvVar(name=name, value=value))
        for name in sorted(sensitive.keys()):
            entries.append(
                client.V1EnvVar(
                    name=name,
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name=sensitive_secret_name,
                            key=name,
                        ),
                    ),
                )
            )
        return entries

    def _build_sensitive_secret(
        self,
        client: Any,
        secret_name: str,
        sensitive_env: dict[str, str],
        container_name: str,
    ) -> Any:
        """Build the ephemeral Secret manifest for the sensitive env vars.

        The Secret is anonymous from the Job's perspective: name is
        derived from ``container_name`` plus a fresh UUID12 so two
        concurrent provisioner runs cannot collide. Labels mirror the
        Job's labels so operators can correlate the Secret with the
        Job in kubectl. ``string_data`` carries plaintext values which
        the apiserver base64-encodes into ``data`` on write.
        """
        return client.V1Secret(
            api_version="v1",
            kind="Secret",
            type="Opaque",
            metadata=client.V1ObjectMeta(
                name=secret_name,
                labels={
                    "app.kubernetes.io/part-of": "shifter",
                    "app.kubernetes.io/component": container_name[:63],
                    "shifter.dev/task-runner": "gcp",
                    "shifter.dev/secret-purpose": "provisioner-sensitive-env",
                },
            ),
            string_data=dict(sensitive_env),
        )

    @staticmethod
    def _build_secret_name(container_name: str) -> str:
        """Derive a unique Secret name for a provisioner Job.

        Kubernetes object names cap at 253 characters and follow DNS
        subdomain rules. We keep the prefix under 50 characters and
        append a 12-char UUID hex slice so collisions across
        concurrent runs are negligible.
        """
        # Lowercase + replace any non-DNS-subdomain characters.
        prefix = container_name.lower().replace("_", "-")
        # Trim to a generous bound; the runtime contract is just "unique".
        prefix = prefix[:40].rstrip("-") or "provisioner"
        return f"{prefix}-secrets-{uuid.uuid4().hex[:12]}"

    def _build_container_security_context(self, client: Any) -> Any:
        # Issue #1103: lock the provisioner Job's writable surface to the
        # explicit volumes built below. ALL capabilities dropped, no privilege
        # escalation, non-root, read-only root FS.
        return client.V1SecurityContext(
            read_only_root_filesystem=True,
            run_as_non_root=True,
            run_as_user=_PROVISIONER_RUN_AS_UID,
            run_as_group=_PROVISIONER_RUN_AS_GID,
            allow_privilege_escalation=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        )

    def _build_pod_security_context(self, client: Any) -> Any:
        # seccompProfile=RuntimeDefault matches the platform's worker-engine
        # baseline and is required for restricted Pod Security Standard
        # admission (ADR-006). fsGroup=1000 makes the kubelet chown mounted
        # emptyDir volumes to the runtime group so the non-root container can
        # write to them without an init-chown or fsGroupChangePolicy=Always
        # (which would also re-chown read-only mounts on every start).
        return client.V1PodSecurityContext(
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
            fs_group=_PROVISIONER_RUN_AS_GID,
            fs_group_change_policy="OnRootMismatch",
        )

    def _build_writable_volumes(self, client: Any) -> list[Any]:
        volumes = []
        for name, _mount_path, medium, size_limit in _PROVISIONER_WRITABLE_MOUNTS:
            empty_dir_kwargs: dict[str, Any] = {}
            if medium:
                empty_dir_kwargs["medium"] = medium
            if size_limit:
                empty_dir_kwargs["size_limit"] = size_limit
            volumes.append(
                client.V1Volume(name=name, empty_dir=client.V1EmptyDirVolumeSource(**empty_dir_kwargs)),
            )
        return volumes

    def _build_container_volume_mounts(self, client: Any) -> list[Any]:
        return [
            client.V1VolumeMount(name=name, mount_path=mount_path)
            for name, mount_path, _medium, _size_limit in _PROVISIONER_WRITABLE_MOUNTS
        ]

    def _build_container(
        self,
        client: Any,
        container_name: str,
        image: str,
        command: list[str],
        env: list[Any] | None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "name": container_name,
            "image": image,
            "args": command,
            "env": env,
            "image_pull_policy": getattr(settings, "ENGINE_TASK_IMAGE_PULL_POLICY", "IfNotPresent"),
        }
        if _is_provisioner_task(container_name):
            kwargs["security_context"] = self._build_container_security_context(client)
            kwargs["volume_mounts"] = self._build_container_volume_mounts(client)
        return client.V1Container(**kwargs)

    def _build_job(
        self,
        client: Any,
        image: str,
        container_name: str,
        command: list[str],
        env: list[Any] | None,
    ) -> Any:
        pod_spec_kwargs: dict[str, Any] = {
            "containers": [self._build_container(client, container_name, image, command, env)],
            "restart_policy": "Never",
        }
        if _is_provisioner_task(container_name):
            pod_spec_kwargs["security_context"] = self._build_pod_security_context(client)
            pod_spec_kwargs["volumes"] = self._build_writable_volumes(client)
        pod_spec = client.V1PodSpec(**pod_spec_kwargs)

        service_account_name = getattr(settings, "ENGINE_TASK_SERVICE_ACCOUNT_NAME", "")
        if service_account_name:
            pod_spec.service_account_name = service_account_name

        metadata = client.V1ObjectMeta(
            generate_name=build_job_generate_name(container_name, command),
            labels={
                "app.kubernetes.io/part-of": "shifter",
                "app.kubernetes.io/component": container_name[:63],
                "shifter.dev/task-runner": "gcp",
            },
            annotations={
                "shifter.dev/task-image": image,
            },
        )

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app.kubernetes.io/part-of": "shifter",
                    "app.kubernetes.io/component": container_name[:63],
                }
            ),
            spec=pod_spec,
        )

        spec = client.V1JobSpec(
            template=template,
            backoff_limit=getattr(settings, "ENGINE_TASK_BACKOFF_LIMIT", 0),
            ttl_seconds_after_finished=getattr(settings, "ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED", 3600),
        )

        return client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=metadata,
            spec=spec,
        )

    def _extract_stopped_reason(self, core_api: Any, namespace: str, job_name: str) -> str | None:
        try:
            pods = core_api.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
        except Exception:
            logger.debug("get_task_status: failed to list pods for job=%s", job_name, exc_info=True)
            return None

        for pod in getattr(pods, "items", []):
            container_statuses = getattr(getattr(pod, "status", None), "container_statuses", None) or []
            for container_status in container_statuses:
                state = getattr(container_status, "state", None)
                terminated = getattr(state, "terminated", None)
                if terminated:
                    return getattr(terminated, "message", None) or getattr(terminated, "reason", None)
        return None

    def _read_job_status(self, batch_api: Any, namespace: str, job_name: str, api_exception: type[Exception]) -> Any:
        try:
            return batch_api.read_namespaced_job_status(name=job_name, namespace=namespace)
        except api_exception as e:
            if getattr(e, "status", None) == 404:
                return None
            raise

    def _build_status_payload(self, status: Any, core_api: Any, namespace: str, job_name: str) -> dict[str, Any]:
        active = int(getattr(status, "active", 0) or 0)
        failed = int(getattr(status, "failed", 0) or 0)
        succeeded = int(getattr(status, "succeeded", 0) or 0)
        started_at = getattr(status, "start_time", None)
        stopped_at = getattr(status, "completion_time", None)
        stopped_reason = None

        for condition in getattr(status, "conditions", None) or []:
            if getattr(condition, "type", "") in {"Failed", "Complete"}:
                stopped_reason = getattr(condition, "message", None) or getattr(condition, "reason", None)
                break

        if succeeded > 0:
            state = "SUCCEEDED"
        elif failed > 0:
            state = "FAILED"
        elif active > 0:
            state = "RUNNING"
        else:
            state = "SUBMITTED"

        if state in {"SUCCEEDED", "FAILED"} and not stopped_reason:
            stopped_reason = self._extract_stopped_reason(core_api, namespace, job_name)

        return {
            "task_id": f"{namespace}/{job_name}",
            "status": state,
            "desired_status": "RUNNING" if state in {"SUBMITTED", "RUNNING"} else "COMPLETED",
            "started_at": started_at,
            "stopped_at": stopped_at,
            "stopped_reason": stopped_reason,
        }

    def run_task(
        self,
        task_definition: str,
        cluster: str,
        command: list[str],
        container_name: str,
        env_overrides: dict[str, str] | None = None,
        network_config: dict[str, Any] | None = None,
    ) -> str | None:
        del network_config  # Networking is handled by the cluster and namespace policies.
        logger.debug("run_task: task_definition=%s cluster=%s", task_definition, cluster)

        namespace = cluster
        image = task_definition
        if not namespace:
            raise CloudTaskError("GCP task runner requires a Kubernetes namespace in ENGINE_TASK_CLUSTER")
        if not image:
            raise CloudTaskError("GCP task runner requires a container image in ENGINE_TASK_DEFINITION")

        try:
            batch_api, core_api, client, _api_exception = self._load_kubernetes_api()
            # Partition env so sensitive values flow through a per-Job
            # Secret instead of literal value= entries on the Pod spec
            # (issue #1185).
            sensitive_env, _plain_env = split_env(env_overrides or {})
            secret_name: str | None = None
            if sensitive_env:
                secret_name = self._build_secret_name(container_name)
                secret_body = self._build_sensitive_secret(client, secret_name, sensitive_env, container_name)
                core_api.create_namespaced_secret(namespace=namespace, body=secret_body)
            # Codex review #1180 cycle 2 finding 3: every operation
            # between Secret creation and ownerReference installation
            # must be inside the unwind scope. _build_env / _build_job
            # are local Python helpers that should not raise, but a
            # future refactor or upstream client model change could
            # introduce a TypeError or attribute lookup failure that
            # would otherwise orphan the Secret with no ownerReference
            # target.
            try:
                env = self._build_env(client, env_overrides, sensitive_secret_name=secret_name)
                job = self._build_job(client, image, container_name, command, env)
                created = batch_api.create_namespaced_job(namespace=namespace, body=job)
            except Exception:
                self._cleanup_sensitive_secret(core_api, secret_name, namespace)
                raise
            job_name = getattr(getattr(created, "metadata", None), "name", None)
            if not job_name:
                # The apiserver accepted the Job but the response
                # was malformed (no name). The Job may or may not
                # actually run, but we cannot return a usable task_id
                # AND the Secret we created earlier would orphan
                # without an ownerReference target. Tear both down
                # so the namespace stays clean. Codex review #1180
                # cycle 1 finding 6.
                self._cleanup_sensitive_secret(core_api, secret_name, namespace)
                raise CloudTaskError("Kubernetes API did not return a Job name")
            # Owner-reference installation is part of the success
            # contract (codex review #1180 cycle 1 finding 6): if we
            # cannot install it, the Secret becomes an indefinite
            # orphan no Job GC will ever reach. Treat the patch
            # failure as a run-level failure — delete the Job + the
            # Secret and raise. This surfaces permission mismatches
            # loudly instead of silently leaving secrets behind.
            if secret_name is not None:
                self._install_owner_reference_or_unwind(
                    client=client,
                    batch_api=batch_api,
                    core_api=core_api,
                    namespace=namespace,
                    job_name=job_name,
                    job_uid=getattr(getattr(created, "metadata", None), "uid", None),
                    secret_name=secret_name,
                )
            task_id = f"{namespace}/{job_name}"
            logger.info("run_task: started job=%s image=%s", task_id, image)
            return task_id
        except CloudTaskError:
            raise
        except Exception as e:
            logger.error("run_task: failed task_definition=%s error=%s", task_definition, e)
            raise CloudTaskError(f"Failed to create Kubernetes Job: {e}") from e

    @staticmethod
    def _owner_ref_to_dict(owner_ref: Any) -> dict[str, Any]:
        """Convert a V1OwnerReference to the camelCase dict shape the
        apiserver expects in a strategic-merge patch body."""
        return {
            "apiVersion": owner_ref.api_version,
            "kind": owner_ref.kind,
            "name": owner_ref.name,
            "uid": owner_ref.uid,
            "controller": owner_ref.controller,
            "blockOwnerDeletion": owner_ref.block_owner_deletion,
        }

    @staticmethod
    def _cleanup_sensitive_secret(core_api: Any, secret_name: str | None, namespace: str) -> None:
        """Delete an orphan sensitive-env Secret. Best-effort: log on
        failure so the operator can clean up manually, but never raise
        — the caller is already on an error path."""
        if not secret_name:
            return
        try:
            core_api.delete_namespaced_secret(name=secret_name, namespace=namespace)
        except Exception:
            logger.warning(
                "run_task: failed to clean up orphan secret=%s namespace=%s",
                secret_name,
                namespace,
                exc_info=True,
            )

    def _install_owner_reference_or_unwind(
        self,
        *,
        client: Any,
        batch_api: Any,
        core_api: Any,
        namespace: str,
        job_name: str,
        job_uid: str | None,
        secret_name: str,
    ) -> None:
        """Patch the Secret's ownerReferences. If the patch fails (or
        the Job uid was unavailable), delete BOTH the Job and the
        Secret and raise CloudTaskError — the alternative is an
        indefinite orphan Secret with sensitive payload."""
        if not job_uid:
            self._unwind_run(
                batch_api,
                core_api,
                namespace,
                job_name,
                secret_name,
                detail="created Job lacks a uid we can use as ownerReference target",
            )
            raise CloudTaskError(
                f"GCP task runner: cannot install Secret ownerReference (Job {job_name} returned no uid); rolled back"
            )

        owner_ref = client.V1OwnerReference(
            api_version="batch/v1",
            kind="Job",
            name=job_name,
            uid=job_uid,
            controller=True,
            block_owner_deletion=True,
        )
        patch_body = {"metadata": {"ownerReferences": [self._owner_ref_to_dict(owner_ref)]}}
        try:
            core_api.patch_namespaced_secret(name=secret_name, namespace=namespace, body=patch_body)
        except Exception as patch_err:
            self._unwind_run(
                batch_api,
                core_api,
                namespace,
                job_name,
                secret_name,
                detail=f"ownerReference patch failed: {patch_err}",
            )
            raise CloudTaskError(
                f"GCP task runner: failed to install Secret ownerReference for Job {job_name}: {patch_err}"
            ) from patch_err

    @staticmethod
    def _unwind_run(
        batch_api: Any,
        core_api: Any,
        namespace: str,
        job_name: str,
        secret_name: str,
        *,
        detail: str,
    ) -> None:
        """Delete the Job and the Secret we created earlier in this
        run. Each delete is best-effort: we log and continue so the
        caller's exception (raised after we return) carries the
        original cause."""
        logger.warning(
            "run_task: unwinding run for job=%s secret=%s namespace=%s reason=%s",
            job_name,
            secret_name,
            namespace,
            detail,
        )
        try:
            batch_api.delete_namespaced_job(name=job_name, namespace=namespace)
        except Exception:
            logger.warning(
                "run_task: failed to delete Job during unwind job=%s namespace=%s",
                job_name,
                namespace,
                exc_info=True,
            )
        try:
            core_api.delete_namespaced_secret(name=secret_name, namespace=namespace)
        except Exception:
            logger.warning(
                "run_task: failed to delete Secret during unwind secret=%s namespace=%s",
                secret_name,
                namespace,
                exc_info=True,
            )

    def get_task_status(self, cluster: str, task_id: str) -> dict[str, Any] | None:
        logger.debug("get_task_status: cluster=%s task_id=%s", cluster, task_id)
        if not task_id:
            return None

        namespace, job_name = parse_job_task_id(task_id, cluster)
        if not namespace or not job_name:
            return None

        try:
            batch_api, core_api, _client, api_exception = self._load_kubernetes_api()
            job = self._read_job_status(batch_api, namespace, job_name, api_exception)
            if job is None:
                return None
            return self._build_status_payload(getattr(job, "status", None), core_api, namespace, job_name)
        except CloudTaskError:
            raise
        except Exception as e:
            logger.error("get_task_status: failed task_id=%s error=%s", task_id, e)
            raise CloudTaskError(f"Failed to get Kubernetes Job status: {e}") from e
