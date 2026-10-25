"""Kustomize and Helm consume the same native database and policy contracts."""

import importlib.util
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/gcp/render_native_identity.py"


def test_native_projection_reuses_chart_clients_and_separates_policy_migration():
    spec = importlib.util.spec_from_file_location("native_projection", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "platform/k8s/gcp/base")], capture_output=True, text=True, check=True
    ).stdout
    users = {
        role: f"synthetic-{role}@synthetic-project.iam"
        for role in (
            "portal",
            "workers",
            "ctf-scheduler",
            "provisioner-launcher",
            "provisioner",
            "openfga-runtime",
            "openfga-admin",
            "openfga-migrator",
        )
    }
    accounts = {role: user + ".gserviceaccount.com" for role, user in users.items()}
    accounts["guacamole-client"] = "synthetic-guac@synthetic-project.iam.gserviceaccount.com"
    outputs = {
        "native_identity": {
            "value": {
                "enabled": True,
                "openfga_enabled": True,
                "instance_connection_name": "synthetic-project:us-central1:platform-pg",
                "database_users": users,
            }
        },
        "identity_platform_project_id": {"value": "synthetic-project"},
        "workload_service_accounts": {"value": accounts},
        "control_plane_database": {"value": {"private_ip": "10.60.0.12"}},
    }
    policy = {
        "enabled": True,
        "runtime_secret_ref": "projects/synthetic-project/secrets/runtime",
        "admin_secret_ref": "projects/synthetic-project/secrets/admin",
        "ca_secret_ref": "projects/synthetic-project/secrets/ca",
    }
    manifest, migration = module.project_manifest(base, outputs, openfga_settings=policy)
    objects = {(item["kind"], item["metadata"]["name"]): item for item in yaml.safe_load_all(manifest) if item}
    for name, role in (
        ("portal-web", "portal"),
        ("worker-engine", "workers"),
        ("worker-provisioner-launcher", "provisioner-launcher"),
    ):
        pod = objects["Deployment", name]["spec"]["template"]["spec"]
        assert pod["initContainers"][0]["restartPolicy"] == "Always"
        assert any(item == {"name": "DB_USER", "value": users[role]} for item in pod["containers"][0]["env"])
    assert ("Deployment", "openfga") in objects and ("Deployment", "openfga-admin") in objects
    assert ("Job", "openfga-datastore-migrate") not in objects
    assert migration["metadata"]["name"] == "openfga-datastore-migrate"
    assert migration["spec"]["template"]["spec"]["initContainers"][0]["name"] == "cloud-sql-proxy"
    assert (
        objects["ServiceAccount", "guacamole-client"]["metadata"]["annotations"]["iam.gke.io/gcp-service-account"]
        == accounts["guacamole-client"]
    )
    assert "projects/synthetic-project/secrets/runtime" not in json.dumps(list(objects.values()))
    assert "OPENFGA_ENABLED" not in str(objects["Deployment", "portal-web"])  # fresh datastore: publish IDs first
    policy.update(store_id="01J00000000000000000000001", model_id="01J00000000000000000000000")
    bound, _ = module.project_manifest(base, outputs, openfga_settings=policy)
    repeated, _ = module.project_manifest(bound, outputs, openfga_settings=policy)
    assert list(yaml.safe_load_all(bound)) == list(yaml.safe_load_all(repeated))


def test_native_projection_preserves_active_model_control_database_identity(tmp_path):
    CHART = ROOT / "platform/charts/shifter"
    users = {
        role: f"synthetic-{role}@synthetic-project.iam"
        for role in (
            "portal",
            "workers",
            "ctf-scheduler",
            "provisioner-launcher",
            "provisioner",
        )
    }
    values = {
        "cloudSqlProxy": {
            "enabled": True,
            "instanceConnectionName": "synthetic-project:us-central1:platform-pg",
            "databaseUsers": users,
            "databaseCidrs": ["10.60.0.12/32"],
        }
    }
    fixture_spec = importlib.util.spec_from_file_location("model_broker_fixture", CHART / "tests/test_model_broker.py")
    fixture = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture)

    values["modelBroker"] = fixture.enabled_values()["modelBroker"]
    broker = values["modelBroker"]
    catalog = json.loads((CHART.parents[2] / "docs/architecture/model-access/example-policy.v3.json").read_text())
    catalog["enabled"] = True
    broker.update(
        catalog_json=json.dumps(catalog),
        catalog_digest=catalog["digest"],
        provisioner_subject="provisioner@synthetic-project.iam.gserviceaccount.com",
        providers_json="{}",
        fingerprint_secret_name="fingerprint-v1",
        fingerprint_key_version="v1",
        broker_subject_id="123456789012345678901",
        provisioner_subject_id="123456789012345678902",
    )
    broker["control_env"].update(MODEL_ACCESS_ENABLED="true", MODEL_ACCESS_CATALOG_DIGEST=catalog["digest"])
    path = tmp_path / "model-native.json"
    path.write_text(json.dumps(values))
    result = subprocess.run(
        ["helm", "template", "combined-native", str(CHART), "-f", str(CHART / "values-gcp-dev.yaml"), "-f", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]

    spec = importlib.util.spec_from_file_location(
        "native_projection", CHART.parents[2] / "scripts/gcp/render_native_identity.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outputs = {
        "native_identity": {
            "value": {
                "enabled": True,
                "openfga_enabled": False,
                "instance_connection_name": values["cloudSqlProxy"]["instanceConnectionName"],
                "database_users": users,
            }
        },
        "identity_platform_project_id": {"value": "synthetic-project"},
        "workload_service_accounts": {"value": {role: user + ".gserviceaccount.com" for role, user in users.items()}},
        "control_plane_database": {"value": {"private_ip": "10.60.0.12"}},
    }
    # The broker renderer runs first and its control pod initially has legacy SQL wiring.
    control = next(
        item
        for item in documents
        if item["kind"] == "Deployment" and item["metadata"]["name"] == "model-access-control"
    )
    control_pod = control["spec"]["template"]["spec"]
    control_pod.pop("initContainers")
    control_pod["containers"][0]["env"] = [
        item for item in control_pod["containers"][0]["env"] if not item["name"].startswith("DB_")
    ]
    projected, _ = module.project_manifest(yaml.safe_dump_all(documents), outputs, model_broker_values=broker)
    projected_control = next(
        item
        for item in yaml.safe_load_all(projected)
        if item and item["kind"] == "Deployment" and item["metadata"]["name"] == "model-access-control"
    )["spec"]["template"]["spec"]
    assert projected_control["initContainers"][0]["restartPolicy"] == "Always"
    assert {"name": "DB_USER", "value": users["workers"]} in projected_control["containers"][0]["env"]
