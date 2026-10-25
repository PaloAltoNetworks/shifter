#!/usr/bin/env python3
"""Bind running GKE container image IDs to an exact release image set."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_RUNTIME_PREFIXES = ("containerd://", "docker-pullable://", "docker://")

# The shifter-platform namespace is a closed release boundary. Every intended
# workload has exactly one declared container, and each container maps to one
# of the three continuously running release images. Provisioner is deliberately
# absent: it is an ephemeral task image verified by admission policy instead.
_RELEASE_CONTAINERS: dict[str, dict[str, str]] = {
    "ctf-communication-worker": {"ctf-communication-worker": "portal"},
    "ctf-scheduler": {"ctf-scheduler": "portal"},
    "guacamole-bootstrap-prune": {"guacamole-bootstrap-prune": "portal"},
    "guacamole-client": {"guacamole-client": "guacamole-client"},
    "guacd": {"guacd": "guacd"},
    "portal": {"portal": "portal"},
    "raes-operation-record-prune": {"raes-operation-record-prune": "portal"},
    "worker-cms": {"worker-cms": "portal"},
    "worker-engine": {"worker-engine": "portal"},
    "worker-mc": {"worker-mc": "portal"},
    "worker-operation-result-applier": {"worker-operation-result-applier": "portal"},
    "worker-outbox-drainer": {"worker-outbox-drainer": "portal"},
    "worker-provisioner-launcher": {"worker-provisioner-launcher": "portal"},
    "worker-reconciler": {"worker-reconciler": "portal"},
    "worker-warm-pool-reconciler": {"worker-warm-pool-reconciler": "portal"},
}

# The controller names are part of the same closed release contract. The deploy
# workflow asks this script for the complete list before it records evidence, so
# a new continuously running component cannot be added to verification without
# also joining the rollout-convergence gate.
_RELEASE_DEPLOYMENTS: dict[str, str] = {
    "ctf-communication-worker": "ctf-communication-worker",
    "ctf-scheduler": "ctf-scheduler",
    "guacamole-bootstrap-prune": "guacamole-bootstrap-prune",
    "guacamole-client": "guacamole-client",
    "guacd": "guacd",
    "portal": "portal-web",
    "raes-operation-record-prune": "raes-operation-record-prune",
    "worker-cms": "worker-cms",
    "worker-engine": "worker-engine",
    "worker-mc": "worker-mc",
    "worker-operation-result-applier": "worker-operation-result-applier",
    "worker-outbox-drainer": "worker-outbox-drainer",
    "worker-provisioner-launcher": "worker-provisioner-launcher",
    "worker-reconciler": "worker-reconciler",
    "worker-warm-pool-reconciler": "worker-warm-pool-reconciler",
}


_BROKER_CONTAINERS = {
    "model-broker": {"model-broker": "portal"},
    "model-access-control": {"model-access-control": "portal"},
    "model-provider-egress": {"provider-egress": "portal"},
}


def release_deployments(*, model_broker_enabled: bool = False) -> tuple[str, ...]:
    """Return every Deployment that must converge before evidence is sampled."""
    if set(_RELEASE_DEPLOYMENTS) != set(_RELEASE_CONTAINERS):
        raise ValueError("release deployment and container component maps disagree")
    deployments = tuple(sorted(_RELEASE_DEPLOYMENTS.values()))
    if len(deployments) != len(set(deployments)):
        raise ValueError("release deployment map contains duplicate controllers")
    return tuple(sorted((*deployments, *_BROKER_CONTAINERS))) if model_broker_enabled else deployments


def parse_expected_images(values: list[str]) -> dict[str, dict[str, str]]:
    """Parse ``name=repository@sha256`` arguments into a validated mapping."""
    expected: dict[str, dict[str, str]] = {}
    for value in values:
        name, separator, reference = value.partition("=")
        root, digest_separator, digest = reference.rpartition("@")
        if not separator or not name or not root or not digest_separator or not _DIGEST_RE.fullmatch(digest):
            raise ValueError("expected images must use name=repository@sha256:<64 lowercase hex> syntax")
        if name in expected:
            raise ValueError(f"duplicate expected image name: {name}")
        expected[name] = {"root": root, "digest": digest}
    if not expected:
        raise ValueError("at least one expected image is required")
    return expected


def _runtime_reference(image_id: str) -> str:
    for prefix in _RUNTIME_PREFIXES:
        if image_id.startswith(prefix):
            return image_id[len(prefix) :]
    if "://" in image_id:
        raise ValueError("running workloads report an unsupported imageID scheme")
    return image_id


def _pod_identity(
    pod: object,
    containers: dict[str, dict[str, str]],
) -> tuple[str, str, dict[str, object], dict[str, object]]:
    if not isinstance(pod, dict):
        raise ValueError("pod inventory contains a malformed item")
    metadata = pod.get("metadata", {})
    spec = pod.get("spec", {})
    status = pod.get("status", {})
    if not isinstance(metadata, dict) or not isinstance(spec, dict) or not isinstance(status, dict):
        raise ValueError("pod inventory contains malformed metadata, spec, or status")
    pod_name = str(metadata.get("name", ""))
    labels = metadata.get("labels", {})
    if not pod_name or not isinstance(labels, dict):
        raise ValueError("pod inventory contains an unnamed or unlabeled pod")
    if metadata.get("deletionTimestamp") is not None:
        raise ValueError(f"terminating release pod remains in the runtime inventory: {pod_name}")
    if labels.get("app.kubernetes.io/part-of") != "shifter":
        raise ValueError(f"unexpected pod outside the closed Shifter release set: {pod_name}")
    component = str(labels.get("app.kubernetes.io/component", ""))
    if component not in containers:
        raise ValueError(f"unexpected Shifter workload component: {component or '<missing>'}")
    return pod_name, component, spec, status


def _container_entries(
    pod_name: str,
    document: dict[str, object],
    fields: tuple[str, ...],
    kind: str,
) -> list[tuple[str, dict[str, object]]]:
    entries: list[tuple[str, dict[str, object]]] = []
    for field in fields:
        values = document.get(field, [])
        if not isinstance(values, list):
            raise ValueError(f"pod {pod_name} has malformed {field}")
        for container in values:
            if not isinstance(container, dict):
                raise ValueError(f"pod {pod_name} has a malformed {kind} container")
            entries.append((field, container))
    return entries


def _require_closed_names(
    pod_name: str,
    kind: str,
    entries: list[tuple[str, dict[str, object]]],
    expected_names: set[str],
) -> None:
    observed_names = [str(container.get("name", "")) for _, container in entries]
    if len(observed_names) != len(set(observed_names)):
        raise ValueError(f"pod {pod_name} reports duplicate {kind} container identities")
    unexpected_names = sorted(set(observed_names) - expected_names)
    if unexpected_names:
        raise ValueError(f"pod {pod_name} reports unexpected {kind} containers: {unexpected_names}")
    missing_names = sorted(expected_names - set(observed_names))
    if missing_names:
        raise ValueError(f"pod {pod_name} is missing expected {kind} containers: {missing_names}")


def _verify_pod_containers(
    pod_name: str,
    component: str,
    declared: list[tuple[str, dict[str, object]]],
    statuses: list[tuple[str, dict[str, object]]],
    expected: dict[str, dict[str, str]],
    containers: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    expected_containers = containers[component]
    expected_names = set(expected_containers)
    _require_closed_names(pod_name, "declared", declared, expected_names)
    _require_closed_names(pod_name, "status", statuses, expected_names)

    declared_images: dict[str, str] = {}
    for _, container in declared:
        container_name = str(container.get("name", ""))
        image_name = expected_containers[container_name]
        image = expected[image_name]
        exact_reference = f"{image['root']}@{image['digest']}"
        declared_image = str(container.get("image", ""))
        if declared_image != exact_reference:
            raise ValueError(
                f"pod {pod_name} container {container_name} does not declare its exact approved image identity"
            )
        declared_images[container_name] = declared_image

    observed: list[dict[str, str]] = []
    for status_field, container in statuses:
        container_name = str(container.get("name", ""))
        image_name = expected_containers[container_name]
        image = expected[image_name]
        exact_reference = f"{image['root']}@{image['digest']}"
        runtime_image = _runtime_reference(str(container.get("imageID", "")))
        # ``ContainerStatus.image`` is runtime-dependent display data. GKE's
        # containerd reports the local image config digest there even when the
        # pod was declared and pulled by an exact registry digest. The pod spec
        # above and the pullable ``imageID`` below are the two identity-bearing
        # fields, so require both of those exact references.
        if runtime_image != exact_reference:
            raise ValueError(
                f"pod {pod_name} container {container_name} does not run its exact approved image identity"
            )
        observed.append(
            {
                "pod": pod_name,
                "component": component,
                "container": container_name,
                "status_field": status_field,
                "declared_image": declared_images[container_name],
                "imageID": str(container.get("imageID", "")),
            }
        )
    return observed


def build_evidence(
    pods: dict[str, object],
    expected: dict[str, dict[str, str]],
    *,
    source_sha: str,
    model_broker_enabled: bool = False,
) -> dict[str, object]:
    """Return evidence only for the exact closed release workload/image map."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source SHA must be 40 lowercase hexadecimal characters")

    containers = {**_RELEASE_CONTAINERS, **(_BROKER_CONTAINERS if model_broker_enabled else {})}
    referenced_images = {image_name for containers in containers.values() for image_name in containers.values()}
    if set(expected) != referenced_images:
        raise ValueError("expected image set does not match the closed release workload map")

    observed: list[dict[str, str]] = []
    items = pods.get("items")
    if not isinstance(items, list):
        raise ValueError("pod inventory must contain an items array")
    seen_components: set[str] = set()
    for pod in items:
        pod_name, component, spec, status = _pod_identity(pod, containers)
        seen_components.add(component)
        declared = _container_entries(
            pod_name,
            spec,
            ("initContainers", "containers", "ephemeralContainers"),
            "declared",
        )
        statuses = _container_entries(
            pod_name,
            status,
            ("initContainerStatuses", "containerStatuses", "ephemeralContainerStatuses"),
            "status",
        )
        observed.extend(_verify_pod_containers(pod_name, component, declared, statuses, expected, containers))

    missing_components = sorted(set(containers) - seen_components)
    if missing_components:
        raise ValueError(f"running workloads are missing release components: {missing_components}")

    return {
        "schema_version": 2,
        "source_sha": source_sha,
        "expected_images": {name: f"{image['root']}@{image['digest']}" for name, image in expected.items()},
        "running_containers": observed,
    }


def _write_private_json(path: Path, value: dict[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-deployments", action="store_true")
    parser.add_argument("--model-broker-enabled", choices=("true", "false"), default="false")
    parser.add_argument("--pods-json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-sha")
    parser.add_argument("--expected-image", action="append", default=[])
    args = parser.parse_args()

    try:
        if args.list_deployments:
            if args.pods_json or args.output or args.source_sha or args.expected_image:
                parser.error("--list-deployments cannot be combined with evidence arguments")
            for deployment in release_deployments(model_broker_enabled=args.model_broker_enabled == "true"):
                print(deployment)
            return 0
        if not args.pods_json or not args.output or not args.source_sha:
            parser.error("--pods-json, --output, and --source-sha are required")
        pods = json.loads(args.pods_json.read_text(encoding="utf-8"))
        expected = parse_expected_images(args.expected_image)
        evidence = build_evidence(
            pods, expected, source_sha=args.source_sha, model_broker_enabled=args.model_broker_enabled == "true"
        )
        _write_private_json(args.output, evidence)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
