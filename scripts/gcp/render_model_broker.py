#!/usr/bin/env python3
"""Project optional broker resources from the canonical chart for the GCP lane."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess  # nosec B404 - required CLI adapter; calls below use argv without a shell.
import sys
import tempfile
from pathlib import Path

import yaml
from installation.capacity_profiles_gcp import resolve_capacity_profile
from installation.errors import InstallationConfigError
from installation.gcp_model_broker import project_model_broker, validate_model_broker_readback
from installation.loader import load_root_config
from installation.render import render_model_access_catalog, render_model_access_env

_ROOT = Path(__file__).resolve().parents[2]
BROKER_RESOURCE_NAMES = frozenset(
    {
        "model-broker",
        "model-access-control",
        "model-provider-egress",
        "model-provider-egress-boundary",
        "model-broker-catalog",
        "model-broker-boundary",
        "model-access-control-ingress",
        "model-enrollment-control-egress",
    }
)
_SHARED_POLICIES = frozenset({"allow-platform-provider-apis-egress", "allow-platform-private-service-egress"})
_CAPACITY_WORKLOADS = {
    "portal": ("portal-web", "portal"),
    "guacd": ("guacd", "guacd"),
    "guacamoleClient": ("guacamole-client", "guacamole-client"),
}
# Workloads whose autoscaler the profile owns (the chart's capacity-autoscaling.yaml).
_CAPACITY_AUTOSCALED = ("portal", "guacd")


def _control_access_env(control: dict[str, object]) -> dict[str, str]:
    keys = {"MODEL_ACCESS_ENABLED", "MODEL_ACCESS_CATALOG_PATH", "MODEL_ACCESS_CATALOG_DIGEST"}
    container = control["spec"]["template"]["spec"]["containers"][0]
    values = {item["name"]: item["value"] for item in container["env"] if item.get("name") in keys and "value" in item}
    if set(values) != keys:
        raise ValueError("control deployment lacks the complete model-access environment")
    return values


def _mount_catalog_for_runtime_consumers(documents: list[dict], digest: str) -> None:
    for document in documents:
        if document.get("kind") != "Deployment":
            continue
        template = document["spec"]["template"]
        pod = template["spec"]
        consumers = [
            container
            for container in pod["containers"]
            if any(
                ref.get("configMapRef", {}).get("name") == "platform-runtime" for ref in container.get("envFrom", [])
            )
        ]
        if not consumers:
            continue
        volumes = pod.setdefault("volumes", [])
        if not any(volume.get("name") == "model-access-catalog" for volume in volumes):
            volumes.append({"name": "model-access-catalog", "configMap": {"name": "model-broker-catalog"}})
        for container in consumers:
            mounts = container.setdefault("volumeMounts", [])
            if not any(mount.get("name") == "model-access-catalog" for mount in mounts):
                mounts.append(
                    {"name": "model-access-catalog", "mountPath": "/etc/shifter/model-access", "readOnly": True}
                )
        template.setdefault("metadata", {}).setdefault("annotations", {})["checksum/model-access-catalog"] = digest


def apply_capacity_profile(base: str, profile_id: str) -> str:
    """Project the selected capacity contract into the normal GCP apply.

    Bootstrap renders these values through Helm. The release workflow later
    applies the Kustomize base, so it must carry the same profile or it would
    silently restore the base resource limits. It also owns the autoscalers and
    the Guacamole connection ceiling: otherwise a tier change kept the
    bootstrap-time autoscaler bounds, which immediately scaled the new replica
    count back to the old maximum.
    """
    projection = resolve_capacity_profile(profile_id).helm_projection()
    documents = [document for document in yaml.safe_load_all(base) if document]

    for projection_key, (deployment_name, container_name) in _CAPACITY_WORKLOADS.items():
        workload = projection[projection_key]
        matches = [
            document
            for document in documents
            if document.get("kind") == "Deployment" and document.get("metadata", {}).get("name") == deployment_name
        ]
        if len(matches) != 1:
            raise ValueError(f"capacity projection requires exactly one {deployment_name} Deployment")
        deployment = matches[0]
        deployment["metadata"].setdefault("annotations", {})["shifter.dev/capacity-profile"] = profile_id
        deployment["spec"]["replicas"] = workload["replicas"]
        template = deployment["spec"]["template"]
        template.setdefault("metadata", {}).setdefault("labels", {})["shifter.dev/capacity-profile"] = profile_id
        template["spec"]["terminationGracePeriodSeconds"] = workload["terminationGracePeriodSeconds"]
        containers = [
            container for container in template["spec"]["containers"] if container.get("name") == container_name
        ]
        if len(containers) != 1:
            raise ValueError(f"capacity projection requires exactly one {container_name} container")
        containers[0]["resources"] = copy.deepcopy(workload["resources"])
        if projection_key == "guacamoleClient":
            _set_env(containers[0], "POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS", workload["postgresqlAbsoluteMaxConnections"])
        if projection_key in _CAPACITY_AUTOSCALED:
            documents = [
                document
                for document in documents
                if not (
                    document.get("kind") == "HorizontalPodAutoscaler"
                    and document.get("metadata", {}).get("name") == deployment_name
                )
            ]
            if workload["autoscaling"]["enabled"]:
                documents.append(_autoscaler(deployment, workload["autoscaling"], profile_id))

    runtime_matches = [
        document
        for document in documents
        if document.get("kind") == "ConfigMap" and document.get("metadata", {}).get("name") == "platform-runtime"
    ]
    if len(runtime_matches) != 1:
        raise ValueError("capacity projection requires exactly one platform-runtime ConfigMap")
    runtime_matches[0].setdefault("data", {}).update(
        {key: str(value) for key, value in projection["runtimeEnv"].items()}
    )
    return yaml.safe_dump_all(documents, sort_keys=False)


def _set_env(container: dict, name: str, value: object) -> None:
    """Set one literal environment variable on a container, replacing any prior value."""
    env = [entry for entry in container.get("env", []) if entry.get("name") != name]
    env.append({"name": name, "value": str(value)})
    container["env"] = env


def _autoscaler(deployment: dict, autoscaling: dict, profile_id: str) -> dict:
    """Return the profile's HorizontalPodAutoscaler for one Deployment (chart capacity-autoscaling.yaml)."""
    metadata = deployment["metadata"]
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {
            "name": metadata["name"],
            "namespace": metadata.get("namespace", "shifter-platform"),
            "labels": {"app.kubernetes.io/part-of": "shifter"},
            "annotations": {"shifter.dev/capacity-profile": profile_id},
        },
        "spec": {
            "scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": metadata["name"]},
            "minReplicas": autoscaling["minReplicas"],
            "maxReplicas": autoscaling["maxReplicas"],
            "behavior": {"scaleDown": {"stabilizationWindowSeconds": autoscaling["scaleDownStabilizationSeconds"]}},
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {
                        "name": "cpu",
                        "target": {
                            "type": "Utilization",
                            "averageUtilization": autoscaling["cpuUtilizationPercentage"],
                        },
                    },
                }
            ],
        },
    }


def combine_resources(base: str, broker: str) -> str:
    """Replace shared policies before apply, avoiding a transient broad grant."""
    additions = list(yaml.safe_load_all(broker)) if broker.strip() else []

    def identity(document):
        metadata = document.get("metadata", {})
        return document.get("kind"), metadata.get("namespace"), metadata.get("name")

    replacements = {identity(document) for document in additions}
    documents = [
        document for document in yaml.safe_load_all(base) if document and identity(document) not in replacements
    ]
    if additions:
        # Policy grants are additive. Narrow every incumbent platform egress
        # policy irrespective of its Kustomize/generated name. The broker's
        # dedicated policy owns its complete egress, including DNS.
        for document in documents:
            if (
                document.get("kind") != "NetworkPolicy"
                or document.get("metadata", {}).get("namespace") != "shifter-platform"
            ):
                continue
            policy = document["spec"]
            if "Egress" in policy.get("policyTypes", []) or "egress" in policy:
                expressions = policy.setdefault("podSelector", {}).setdefault("matchExpressions", [])
                exclusion = {
                    "key": "app.kubernetes.io/component",
                    "operator": "NotIn",
                    "values": ["model-broker", "model-provider-egress"],
                }
                if exclusion not in expressions:
                    expressions.append(exclusion)
        controls = [
            doc
            for doc in additions
            if doc.get("kind") == "Deployment" and doc.get("metadata", {}).get("name") == "model-access-control"
        ]
        if controls:
            runtime = [
                doc for doc in documents if identity(doc) == ("ConfigMap", "shifter-platform", "platform-runtime")
            ]
            if len(runtime) != 1:
                raise ValueError("control deployment requires exactly one applied runtime ConfigMap")
            workers = [doc for doc in documents if identity(doc) == ("Deployment", "shifter-platform", "worker-engine")]
            if len(workers) != 1:
                raise ValueError("control deployment requires exactly one applied Engine worker")
            containers = workers[0]["spec"]["template"]["spec"]["containers"]
            engine = [container for container in containers if container["name"] == "worker-engine"]
            if len(engine) != 1 or not engine[0].get("envFrom"):
                raise ValueError("control deployment requires the Engine runtime references")
            catalogs = [
                doc
                for doc in additions
                if doc.get("kind") == "ConfigMap" and doc.get("metadata", {}).get("name") == "model-broker-catalog"
            ]
            if len(catalogs) != 1:
                raise ValueError("control deployment requires exactly one broker catalog")
            access_env = _control_access_env(controls[0])
            runtime[0].setdefault("data", {}).update(json.loads(catalogs[0]["data"]["enrollment.json"]))
            runtime[0]["data"].update(access_env)
            _mount_catalog_for_runtime_consumers(documents, access_env["MODEL_ACCESS_CATALOG_DIGEST"])
            checksum = hashlib.sha256(json.dumps(runtime[0].get("data", {}), sort_keys=True).encode()).hexdigest()
            for control in controls:
                control["spec"]["template"]["metadata"].setdefault("annotations", {})["checksum/runtime-config"] = (
                    checksum
                )
                control["spec"]["template"]["spec"]["containers"][0]["envFrom"] = copy.deepcopy(engine[0]["envFrom"])
    return yaml.safe_dump_all(documents + additions, sort_keys=False)


def render_resources(broker: dict[str, object], *, image: str, private_service_cidrs: list[str]) -> str:
    """Render the actual chart, selecting only owned resources and narrowed policies."""
    if broker.get("enabled") is not True:
        return ""
    values = {
        "provider": {"name": "gcp"},
        "modelBroker": broker,
        "images": {"platform": image},
        "network": {
            "providerApiCidrs": ["199.36.153.4/30", "199.36.153.8/30"],
            "privateServiceCidrs": private_service_cidrs,
        },
    }
    with tempfile.TemporaryDirectory(prefix="model-broker-render-") as directory:
        path = Path(directory) / "values.json"
        path.write_text(json.dumps(values), encoding="utf-8")
        # Fixed Helm template command and chart; deployment values travel through a generated file, never shell text.
        result = subprocess.run(  # nosec B603 B607 - fixed CLI from the operator/CI toolchain.
            ["helm", "template", "shifter", str(_ROOT / "platform/charts/shifter"), "-f", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    selected = []
    for document in yaml.safe_load_all(result.stdout):
        if not isinstance(document, dict):
            continue
        name = document.get("metadata", {}).get("name")
        if name in BROKER_RESOURCE_NAMES or (document.get("kind") == "NetworkPolicy" and name in _SHARED_POLICIES):
            selected.append(document)
    return yaml.safe_dump_all(selected, sort_keys=False)


def main(argv: list[str] | None = None) -> int:
    """Validate root intent against applied Terraform output before rendering."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--terraform-output", required=True)
    parser.add_argument("--platform-image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-manifests")
    args = parser.parse_args(argv)
    config = load_root_config(args.config)
    outputs = json.loads(Path(args.terraform_output).read_text(encoding="utf-8"))
    output = outputs.get("model_broker", {}).get("value")
    validate_model_broker_readback(output, config)
    broker = project_model_broker(
        output,
        catalog_json=render_model_access_catalog(config),
        model_access_env=render_model_access_env(config),
        runtime_settings=config.settings.get("model_broker_runtime"),
    )
    # The incumbent renderer owns private-service CIDR extraction.
    sys.path.insert(0, str(_ROOT / "scripts/bootstrap"))
    from gcp_control_plane import _gcp_private_service_cidrs

    rendered = render_resources(
        broker, image=args.platform_image, private_service_cidrs=_gcp_private_service_cidrs(outputs)
    )
    if args.base_manifests:
        profile_id = str(config.settings.get("shared_service_capacity_profile", "gcp-shared-v1-p10"))
        base = apply_capacity_profile(Path(args.base_manifests).read_text(encoding="utf-8"), profile_id)
        rendered = combine_resources(base, rendered)
    Path(args.output).write_text(rendered, encoding="utf-8")
    Path(args.output + ".enabled").write_text("true" if broker["enabled"] else "false", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InstallationConfigError, ValueError, OSError, subprocess.SubprocessError):
        sys.stderr.write("model broker configuration or cloud readback failed; no qualification asserted\n")
        raise SystemExit(1) from None
