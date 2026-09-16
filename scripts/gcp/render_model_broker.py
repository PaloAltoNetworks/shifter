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
from installation.errors import InstallationConfigError
from installation.gcp_model_broker import project_model_broker, validate_model_broker_readback
from installation.loader import load_root_config
from installation.render import render_model_access_catalog, render_model_access_env

_ROOT = Path(__file__).resolve().parents[2]
BROKER_RESOURCE_NAMES = frozenset(
    {
        "model-broker",
        "model-access-control",
        "model-broker-catalog",
        "model-broker-boundary",
        "model-access-control-ingress",
    }
)
_SHARED_POLICIES = frozenset({"allow-platform-provider-apis-egress", "allow-platform-private-service-egress"})


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
                exclusion = {"key": "app.kubernetes.io/component", "operator": "NotIn", "values": ["model-broker"]}
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
        output, catalog_json=render_model_access_catalog(config), model_access_env=render_model_access_env(config)
    )
    # The incumbent renderer owns private-service CIDR extraction.
    sys.path.insert(0, str(_ROOT / "scripts/bootstrap"))
    from gcp_control_plane import _gcp_private_service_cidrs

    rendered = render_resources(
        broker, image=args.platform_image, private_service_cidrs=_gcp_private_service_cidrs(outputs)
    )
    if args.base_manifests:
        rendered = combine_resources(Path(args.base_manifests).read_text(encoding="utf-8"), rendered)
    Path(args.output).write_text(rendered, encoding="utf-8")
    Path(args.output + ".enabled").write_text("true" if broker["enabled"] else "false", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InstallationConfigError, ValueError, OSError, subprocess.SubprocessError):
        sys.stderr.write("model broker configuration or cloud readback failed; no qualification asserted\n")
        raise SystemExit(1) from None
