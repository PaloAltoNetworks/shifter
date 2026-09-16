"""Kubernetes manifest builders for the task Job launched by ``KubernetesTaskRunner``.

Extracted from the GCP task-runner package (#1824). These are pure builder
functions over the dynamically loaded Kubernetes ``client`` module; none of them
talk to the Kubernetes API or read provider settings. Provider-variable choices
(labels, service account, pull/backoff/TTL, provisioner hardening) arrive via the
injected ``KubernetesTaskProfile``.
"""

from __future__ import annotations

from typing import Any

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.sensitive_env import split_env

from ._helpers import (
    _SHIFTER_ANNOTATION_TASK_IDENTITY,
    _api_call,
    _shifter_resource_labels,
)
from ._profile import KubernetesTaskProfile, ProvisionerHardeningProfile
from .naming import build_idempotent_job_name, build_job_generate_name


def _build_env(
    client: object,
    env_overrides: dict[str, str] | None,
    sensitive_secret_name: str | None = None,
) -> list[Any] | None:
    """Build the env-var list for the Job container.

    Issue #1185 — sensitive values must NOT appear as literal ``value=`` env
    vars on the Pod spec. They are routed through ``valueFrom.secretKeyRef``
    pointing at an ephemeral per-Job Kubernetes Secret. ``sensitive_secret_name``
    MUST be provided when any key in ``env_overrides`` classifies as sensitive
    (per ``sensitive_env.split_env``); the caller creates the Secret before the
    Job is submitted.
    """
    if not env_overrides:
        return None
    sensitive, plain = split_env(env_overrides)
    if sensitive and not sensitive_secret_name:
        raise CloudTaskError("Kubernetes task runner: sensitive env vars present but no Secret was created")
    entries: list[Any] = []
    for name, value in sorted(plain.items()):
        entries.append(_api_call(client, "V1EnvVar", name=name, value=value))
    for name in sorted(sensitive.keys()):
        entries.append(
            _api_call(
                client,
                "V1EnvVar",
                name=name,
                value_from=_api_call(
                    client,
                    "V1EnvVarSource",
                    secret_key_ref=_api_call(client, "V1SecretKeySelector", name=sensitive_secret_name, key=name),
                ),
            )
        )
    return entries


def _build_sensitive_secret(
    client: object,
    secret_name: str,
    sensitive_env: dict[str, str],
    container_name: str,
    runner_label_value: str,
) -> object:
    """Build the ephemeral Secret manifest for the sensitive env vars.

    The Secret name is derived from ``container_name`` and the launch-intent
    identity when one is available, so a redelivery can safely recreate or repair
    the same object. Labels mirror the Job's labels so operators can correlate the
    Secret with the Job in kubectl. ``string_data`` carries plaintext values which
    the apiserver base64-encodes into ``data`` on write.
    """
    labels = _shifter_resource_labels(container_name, include_task_runner=True, runner_label_value=runner_label_value)
    labels["shifter.dev/secret-purpose"] = "provisioner-sensitive-env"
    return _api_call(
        client,
        "V1Secret",
        api_version="v1",
        kind="Secret",
        type="Opaque",
        metadata=_api_call(client, "V1ObjectMeta", name=secret_name, labels=labels),
        string_data=dict(sensitive_env),
    )


def _build_container_security_context(client: object, hardening: ProvisionerHardeningProfile) -> object:
    """Build the container-level SecurityContext for a hardened task Job.

    Issue #1103: lock the hardened Job's writable surface to the explicit volumes
    built below. ALL capabilities dropped, no privilege escalation, non-root,
    read-only root FS.
    """
    return _api_call(
        client,
        "V1SecurityContext",
        read_only_root_filesystem=True,
        run_as_non_root=True,
        run_as_user=hardening.run_as_uid,
        run_as_group=hardening.run_as_gid,
        allow_privilege_escalation=False,
        capabilities=_api_call(client, "V1Capabilities", drop=["ALL"]),
    )


def _build_pod_security_context(client: object, hardening: ProvisionerHardeningProfile) -> object:
    """Build the Pod-level SecurityContext for a hardened task Job.

    seccompProfile=RuntimeDefault matches the platform's worker-engine baseline
    and is required for restricted Pod Security Standard admission (ADR-006).
    fsGroup makes the kubelet chown mounted emptyDir volumes to the runtime group
    so the non-root container can write to them without an init-chown or
    fsGroupChangePolicy=Always (which would also re-chown read-only mounts on
    every start).
    """
    return _api_call(
        client,
        "V1PodSecurityContext",
        seccomp_profile=_api_call(client, "V1SeccompProfile", type="RuntimeDefault"),
        fs_group=hardening.run_as_gid,
        fs_group_change_policy="OnRootMismatch",
    )


def _build_writable_volumes(client: object, hardening: ProvisionerHardeningProfile) -> list[Any]:
    """Build the emptyDir Volumes backing the hardened task's writable mounts."""
    volumes: list[object] = []
    for name, _mount_path, medium, size_limit in hardening.writable_mounts:
        empty_dir_kwargs: dict[str, Any] = {}
        if medium:
            empty_dir_kwargs["medium"] = medium
        if size_limit:
            empty_dir_kwargs["size_limit"] = size_limit
        volumes.append(
            _api_call(
                client,
                "V1Volume",
                name=name,
                empty_dir=_api_call(client, "V1EmptyDirVolumeSource", **empty_dir_kwargs),
            ),
        )
    return volumes


def _build_container_volume_mounts(client: object, hardening: ProvisionerHardeningProfile) -> list[Any]:
    """Build the container VolumeMounts backing the hardened task's writable mounts."""
    return [
        _api_call(client, "V1VolumeMount", name=name, mount_path=mount_path)
        for name, mount_path, _medium, _size_limit in hardening.writable_mounts
    ]


def _build_container(
    client: object,
    container_name: str,
    image: str,
    command: list[str],
    env: list[Any] | None,
    profile: KubernetesTaskProfile,
) -> object:
    """Build the task container spec, applying #1103 hardening when the profile opts in."""
    kwargs: dict[str, Any] = {
        "name": container_name,
        "image": image,
        "args": command,
        "env": env,
        "image_pull_policy": profile.image_pull_policy,
    }
    if profile.resource_requests is not None or profile.resource_limits is not None:
        kwargs["resources"] = _api_call(
            client,
            "V1ResourceRequirements",
            requests=dict(profile.resource_requests or {}),
            limits=dict(profile.resource_limits or {}),
        )
    hardening = profile.hardening_for(container_name)
    if hardening is not None:
        kwargs["security_context"] = _build_container_security_context(client, hardening)
        kwargs["volume_mounts"] = _build_container_volume_mounts(client, hardening)
    return _api_call(client, "V1Container", **kwargs)


def _build_job(
    client: object,
    image: str,
    container_name: str,
    command: list[str],
    env: list[Any] | None,
    profile: KubernetesTaskProfile,
    task_identity: str | None = None,
) -> object:
    """Build the batch/v1 Job manifest for one task launch."""
    pod_spec_kwargs: dict[str, Any] = {
        "containers": [_build_container(client, container_name, image, command, env, profile)],
        "restart_policy": "Never",
    }
    hardening = profile.hardening_for(container_name)
    if hardening is not None:
        pod_spec_kwargs["security_context"] = _build_pod_security_context(client, hardening)
        pod_spec_kwargs["volumes"] = _build_writable_volumes(client, hardening)
        pod_spec_kwargs["automount_service_account_token"] = False

    if profile.service_account_name:
        pod_spec_kwargs["service_account_name"] = profile.service_account_name
    if profile.image_pull_secrets:
        pod_spec_kwargs["image_pull_secrets"] = [
            _api_call(client, "V1LocalObjectReference", name=name) for name in profile.image_pull_secrets
        ]
    if profile.node_selector:
        # Provider-injected node placement (#1711): pins the launched Job onto a
        # dedicated node pool so its pod IP comes from that pool's dedicated pod
        # range (the range VPC scopes management ingress to it).
        pod_spec_kwargs["node_selector"] = dict(profile.node_selector)
    if profile.tolerations:
        pod_spec_kwargs["tolerations"] = [
            _api_call(client, "V1Toleration", key=key, operator=operator, value=value, effect=effect)
            for (key, operator, value, effect) in profile.tolerations
        ]
    pod_spec = _api_call(client, "V1PodSpec", **pod_spec_kwargs)

    metadata_kwargs: dict[str, Any] = {
        "labels": _shifter_resource_labels(
            container_name, include_task_runner=True, runner_label_value=profile.runner_label_value
        ),
        "annotations": {"shifter.dev/task-image": image},
    }
    if task_identity:
        metadata_kwargs["name"] = build_idempotent_job_name(container_name, task_identity)
        metadata_kwargs["annotations"][_SHIFTER_ANNOTATION_TASK_IDENTITY] = task_identity
    else:
        metadata_kwargs["generate_name"] = build_job_generate_name(container_name, command)
    metadata = _api_call(client, "V1ObjectMeta", **metadata_kwargs)

    template = _api_call(
        client,
        "V1PodTemplateSpec",
        metadata=_api_call(
            client,
            "V1ObjectMeta",
            labels=_shifter_resource_labels(
                container_name, include_task_runner=False, runner_label_value=profile.runner_label_value
            ),
        ),
        spec=pod_spec,
    )

    deadline = (
        {"active_deadline_seconds": profile.active_deadline_seconds}
        if profile.active_deadline_seconds is not None
        else {}
    )
    spec = _api_call(
        client,
        "V1JobSpec",
        template=template,
        backoff_limit=profile.backoff_limit,
        ttl_seconds_after_finished=profile.ttl_seconds_after_finished,
        **deadline,
    )

    return _api_call(
        client,
        "V1Job",
        api_version="batch/v1",
        kind="Job",
        metadata=metadata,
        spec=spec,
    )
