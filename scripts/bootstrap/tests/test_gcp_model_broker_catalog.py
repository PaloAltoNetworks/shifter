"""Real deployment adapters bind the control process to the configured catalog."""

import json
import subprocess
from pathlib import Path

import pytest

import deploy
import gcp_control_plane

from .test_gcp_control_plane import PINNED_IMAGE_TAG, _sample_gcp_control_plane_outputs


@pytest.mark.parametrize("adapter", ["bootstrap", "actions"])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.integration
def test_control_binds_root_catalog_through_both_deployment_adapters(tmp_path, adapter, enabled):
    """The mounted catalog overrides inherited disabled defaults only for control."""
    import importlib.util

    import yaml
    from shared.model_access import seal_catalog
    from shared.model_access.runtime import load_mounted_catalog

    root = Path(__file__).resolve().parents[3]
    catalog = json.loads((root / "docs/architecture/model-access/example-policy.v3.json").read_text())
    catalog.pop("digest")
    catalog["enabled"] = True
    catalog = seal_catalog(catalog).model_dump(mode="json")
    broker = {
        "enabled": True,
        "hostname": "models.example.test",
        "vip": "10.40.0.25",
        "admitted_subnets": ["10.50.1.0/24"],
        "tls_secret_name": "broker-tls-v1",
        "control_tls_secret_name": "control-tls-v1",
        "trust_configmap_name": "model-ca-v1",
        "model_projects": {"models-example": "model-invoke"},
    }
    ca_path = tmp_path / "broker-ca.pem"
    subprocess.run(
        [
            "/usr/bin/openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(tmp_path / "test-key.pem"),
            "-out",
            str(ca_path),
            "-days",
            "1",
            "-subj",
            "/CN=Example test CA",
        ],
        check=True,
        capture_output=True,
    )
    runtime = {
        "provider_inventory": {
            "contract_version": "model-broker-providers/v1",
            "targets": [
                {
                    "shard_id": "vertex-primary",
                    "provider": "vertex-v1",
                    "region": "europe-west4",
                    "count_region": "eu",
                    "model": "publishers/anthropic/models/claude-sonnet",
                    "credential_reference": "impersonate:gsa/model-invoke",
                    "principal": "model-invoke@models-example.iam.gserviceaccount.com",
                    "project": "models-example",
                    "context_window_tokens": 200000,
                }
            ],
        },
        "fingerprint_secret_name": "broker-fingerprint-v1",
        "fingerprint_key_version": "v1",
        "guest_trust_ca_pem": ca_path.read_text(),
        "fingerprint_previous_secret_name": "broker-fingerprint-retained",
    }
    root_path = tmp_path / "shifter.yaml"
    root_path.write_text(
        yaml.safe_dump(
            {
                "backend": "gcp",
                "deployment": {"name": "shifter", "domain": "shifter.example.test"},
                "secrets": {"django_secret_key": "prompt"},
                "settings": {
                    "project_id": "platform-example",
                    "dynamic_secret_project_id": "secrets-example",
                    "region": "us-central1",
                    "model_broker": broker,
                    "model_broker_runtime": runtime,
                    "model_access": {"enabled": enabled, "catalog": catalog},
                },
            }
        )
    )
    config = deploy.GDCBootstrapConfig(project_id="platform-example", shifter_config_path=str(root_path))
    outputs = _sample_gcp_control_plane_outputs(config.project_id)
    outputs["model_broker"] = {
        "value": {
            **broker,
            "global_access": False,
            "region": "us-central1",
            "gsa": "model-broker@platform-example.iam.gserviceaccount.com",
            "provisioner_subject": "provisioner@platform-example.iam.gserviceaccount.com",
            "broker_subject_id": "123456789012345678901",
            "provisioner_subject_id": "123456789012345678902",
            "model_identities": {"models-example": "model-invoke@models-example.iam.gserviceaccount.com"},
        }
    }
    chart = root / "platform/charts/shifter"
    if adapter == "bootstrap":
        values_path = gcp_control_plane.stage_gcp_control_plane_values(
            config,
            outputs,
            tmp_path,
            image_tag=PINNED_IMAGE_TAG,
            image_identities=outputs["attested_image_identities"]["value"],
        )
        rendered = subprocess.run(
            [
                "helm",
                "template",
                "shifter",
                str(chart),
                "-f",
                str(chart / "values-gcp-dev.yaml"),
                "-f",
                str(values_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    else:
        spec = importlib.util.spec_from_file_location(
            "broker_catalog_regression", root / "scripts/gcp/render_model_broker.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        outputs_path = tmp_path / "outputs.json"
        outputs_path.write_text(json.dumps(outputs))
        # Actions inherits these defaults, but only control mounts a catalog.
        base_path = tmp_path / "base.yaml"
        capacity_workloads = [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name, "namespace": "shifter-platform"},
                "spec": {
                    "replicas": 1,
                    "template": {
                        "metadata": {},
                        "spec": {"containers": [{"name": container, "resources": {}}]},
                    },
                },
            }
            for name, container in (
                ("portal-web", "portal"),
                ("guacd", "guacd"),
                ("guacamole-client", "guacamole-client"),
            )
        ]
        base_path.write_text(
            yaml.safe_dump_all(
                [
                    {
                        "apiVersion": "v1",
                        "kind": "ConfigMap",
                        "metadata": {"name": "platform-runtime", "namespace": "shifter-platform"},
                        "data": {
                            "MODEL_ACCESS_ENABLED": "false",
                            "MODEL_ACCESS_CATALOG_PATH": "",
                            "MODEL_ACCESS_CATALOG_DIGEST": "",
                        },
                    },
                    {
                        "apiVersion": "apps/v1",
                        "kind": "Deployment",
                        "metadata": {"name": "worker-engine", "namespace": "shifter-platform"},
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [
                                        {
                                            "name": "worker-engine",
                                            "envFrom": [{"configMapRef": {"name": "platform-runtime"}}],
                                        }
                                    ]
                                }
                            }
                        },
                    },
                    *capacity_workloads,
                ]
            )
        )
        output_path = tmp_path / "broker.yaml"
        assert (
            module.main(
                [
                    "--config",
                    str(root_path),
                    "--terraform-output",
                    str(outputs_path),
                    "--platform-image",
                    outputs["attested_image_identities"]["value"]["platform"],
                    "--base-manifests",
                    str(base_path),
                    "--output",
                    str(output_path),
                ]
            )
            == 0
        )
        rendered = output_path.read_text()
    docs = [doc for doc in yaml.safe_load_all(rendered) if doc]
    control = next(
        doc for doc in docs if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "model-access-control"
    )
    assert control["spec"]["replicas"] == (2 if enabled else 0)
    broker_deployment = next(
        doc for doc in docs if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "model-broker"
    )
    assert broker_deployment["spec"]["replicas"] == (2 if enabled else 0)
    if enabled:
        import base64

        runtime_config = next(
            doc for doc in docs if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == "platform-runtime"
        )
        assert runtime_config["data"]["MODEL_BROKER_GUEST_URL"] == "https://models.example.test"
        assert base64.b64decode(runtime_config["data"]["MODEL_ENROLLMENT_CA_PEM_B64"]).decode() == ca_path.read_text()
        assert (
            runtime_config["data"]["MODEL_ENROLLMENT_CONTROL_URL"]
            == "https://model-access-control.shifter-platform.svc:8444"
        )
        broker_pod = broker_deployment["spec"]["template"]["spec"]
        secret_names = {volume["secret"]["secretName"] for volume in broker_pod["volumes"] if "secret" in volume}
        assert {"broker-fingerprint-v1", "broker-fingerprint-retained"} <= secret_names
        broker_env = {item["name"]: item.get("value") for item in broker_pod["containers"][0]["env"]}
        assert broker_env["MODEL_BROKER_PROVIDER"] == "gcp"
        assert broker_env["MODEL_BROKER_FINGERPRINT_KEY_VERSION"] == "v1"
        artifact = next(doc for doc in docs if doc["kind"] == "ConfigMap" and "providers.json" in doc.get("data", {}))
        assert json.loads(artifact["data"]["providers.json"]) == runtime["provider_inventory"]
    pod = control["spec"]["template"]["spec"]
    container = pod["containers"][0]
    env = {item["name"]: item.get("value") for item in container["env"]}
    assert env.get("MODEL_ACCESS_ENABLED") == str(enabled).lower()
    assert env["MODEL_ACCESS_CATALOG_DIGEST"] == catalog["digest"]
    mount = next(item for item in container["volumeMounts"] if item["name"] == "catalog")
    volume = next(item for item in pod["volumes"] if item["name"] == mount["name"])
    artifact = next(
        doc for doc in docs if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == volume["configMap"]["name"]
    )
    filename = str(Path(env["MODEL_ACCESS_CATALOG_PATH"]).relative_to(mount["mountPath"]))
    mounted = tmp_path / filename
    mounted.write_text(artifact["data"][filename])
    assert (
        load_mounted_catalog(
            enabled=enabled, path=str(mounted), expected_digest=env["MODEL_ACCESS_CATALOG_DIGEST"]
        ).digest
        == catalog["digest"]
    )
    others = {
        doc["metadata"]["name"]: doc["spec"]["template"]["spec"]["containers"]
        for doc in docs
        if doc["kind"] == "Deployment" and doc["metadata"]["name"] != "model-access-control"
    }
    assert {"model-broker", "worker-engine"} <= others.keys()
    for containers in others.values():
        assert containers
        for other in containers:
            assert "MODEL_ACCESS_ENABLED" not in {item["name"] for item in other.get("env", [])}
