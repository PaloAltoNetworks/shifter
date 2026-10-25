#!/usr/bin/env python3
"""Project chart-owned native clients and policy resources into the GCP apply."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess  # nosec B404
import tempfile
from pathlib import Path

import yaml
from installation.gcp_model_broker import project_model_broker, validate_model_broker_readback
from installation.gcp_native_identity import project_native_helm
from installation.loader import load_root_config
from installation.render import render_model_access_catalog, render_model_access_env
from installation.settings_gcp import GcpBackendSettings

_ROOT = Path(__file__).resolve().parents[2]
_DATABASE_ENV = {"DB_AUTH_MODE", "DB_HOST", "DB_PORT", "DB_USER", "DB_SECRET_ID"}
_NATIVE_POLICIES = {"allow-platform-native-sql-egress", "allow-jobs-native-sql-egress"}


def _identity(document: dict) -> tuple:
    return document["kind"], document["metadata"].get("namespace", ""), document["metadata"]["name"]


def _patch_deployment(document: dict, reference: dict, *, native_enabled: bool) -> None:
    pod = document["spec"]["template"]["spec"]
    source = reference["spec"]["template"]["spec"]
    if native_enabled and source.get("initContainers"):
        pod["initContainers"] = copy.deepcopy(source["initContainers"])
    for container in pod["containers"]:
        candidate = next((c for c in source["containers"] if c["name"] == container["name"]), None)
        if candidate is None:
            continue
        added = [
            item
            for item in candidate.get("env", [])
            if item["name"] in _DATABASE_ENV
            or item["name"].startswith("OPENFGA_")
            or (document["metadata"]["name"] == "guacamole-client" and item["name"] == "POSTGRESQL_HOSTNAME")
        ]
        if added:
            replaced = {item["name"] for item in added}
            container["env"] = [item for item in container.get("env", []) if item["name"] not in replaced] + added
        for mount in candidate.get("volumeMounts", []):
            if mount["name"].startswith("openfga-"):
                container["volumeMounts"] = [
                    existing for existing in container.get("volumeMounts", []) if existing["name"] != mount["name"]
                ]
                container.setdefault("volumeMounts", []).append(copy.deepcopy(mount))
    for volume in source.get("volumes", []):
        if volume["name"].startswith("openfga-"):
            pod["volumes"] = [existing for existing in pod.get("volumes", []) if existing["name"] != volume["name"]]
            pod.setdefault("volumes", []).append(copy.deepcopy(volume))


def project_manifest(
    manifest: str, outputs: dict, *, openfga_settings: object = None, model_broker_values: dict | None = None
) -> tuple[str, dict | None]:
    values = project_native_helm(outputs, openfga_settings=openfga_settings)
    values["provider"] = {"name": "gcp"}
    values["capabilities"] = {"kubernetesJobLauncher": True}
    if model_broker_values:
        values["modelBroker"] = model_broker_values
    with tempfile.TemporaryDirectory(prefix="native-identity-render-") as directory:
        path = Path(directory) / "values.json"
        path.write_text(json.dumps(values))
        # Chart and CLI are fixed; public deployment values travel through the generated file.
        rendered = subprocess.run(  # nosec B603 B607
            [
                "helm",
                "template",
                "shifter",
                str(_ROOT / "platform/charts/shifter"),
                "-f",
                str(_ROOT / "platform/charts/shifter/values-gcp-dev.yaml"),
                "-f",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    chart = [item for item in yaml.safe_load_all(rendered.stdout) if item]
    chart_objects = {_identity(item): item for item in chart}
    documents = [item for item in yaml.safe_load_all(manifest) if item]
    for document in documents:
        name = document["metadata"]["name"]
        if document["kind"] == "ServiceAccount" and name == "guacamole-client":
            account = outputs["workload_service_accounts"]["value"].get(name)
            if values["cloudSqlProxy"]["enabled"] and account:
                document["metadata"].setdefault("annotations", {})["iam.gke.io/gcp-service-account"] = account
        reference = chart_objects.get(_identity(document))
        if not reference or document["kind"] != "Deployment":
            continue
        _patch_deployment(document, reference, native_enabled=values["cloudSqlProxy"]["enabled"])
    existing = {_identity(item) for item in documents}
    migration = None
    for document in chart:
        name = document["metadata"]["name"]
        owned = name.startswith("openfga") or "openfga" in name or name in _NATIVE_POLICIES
        if not owned:
            continue
        if document["kind"] == "Job" and name == "openfga-datastore-migrate":
            migration = document
        elif _identity(document) not in existing:
            documents.append(document)
    return yaml.safe_dump_all(documents, sort_keys=False), migration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--terraform-output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--migration-output", type=Path, required=True)
    args = parser.parse_args()
    config = load_root_config(args.config)
    settings = GcpBackendSettings.from_root_settings(config.settings)
    outputs = json.loads(args.terraform_output.read_text())
    broker_output = outputs.get("model_broker", {}).get("value")
    validate_model_broker_readback(broker_output, config)
    broker = project_model_broker(
        broker_output,
        catalog_json=render_model_access_catalog(config),
        model_access_env=render_model_access_env(config),
        runtime_settings=config.settings.get("model_broker_runtime"),
    )
    if outputs.get("native_identity", {}).get("value", {}).get("enabled", False) != settings.cloud_sql_iam_auth:
        raise ValueError("native SQL readback differs from the configured deployment intent")
    manifest, migration = project_manifest(
        args.manifest.read_text(), outputs, openfga_settings=settings.openfga.model_dump(), model_broker_values=broker
    )
    args.output.write_text(manifest)
    args.migration_output.write_text(yaml.safe_dump(migration, sort_keys=False) if migration else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
