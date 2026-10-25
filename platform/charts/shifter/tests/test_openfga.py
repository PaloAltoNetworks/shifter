"""Pinned private OpenFGA deployment contract (#2315)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1]
IMAGE = "openfga/openfga@sha256:d53ce5c48413d01e75ecf375f3f74eb35c50f155fc028c41d03dbc7c9838fb38"


def _values() -> dict[str, object]:
    return {
        "openfga": {
            "enabled": True,
            "storeId": "01J00000000000000000000001",
            "modelId": "01J00000000000000000000000",
            "databaseCidrs": ["10.60.0.12/32"],
            "runtimeDatabaseUser": "synthetic_runtime",
            "adminDatabaseUser": "synthetic_admin",
        }
    }


def _render(tmp_path: Path, provider_values: str, overrides: dict[str, object] | None = None):
    values = _values()
    if overrides:
        values["openfga"].update(overrides)  # type: ignore[union-attr]
    generated = tmp_path / "openfga.json"
    generated.write_text(json.dumps(values))
    return subprocess.run(
        [
            "helm",
            "template",
            "openfga-test",
            str(CHART),
            "-f",
            str(CHART / provider_values),
            "-f",
            str(generated),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("provider_values", ["values-aws-dev.yaml", "values-gcp-dev.yaml"])
def test_aws_and_gcp_render_the_same_private_server_contract(tmp_path, provider_values) -> None:
    result = _render(tmp_path, provider_values)
    assert result.returncode == 0, result.stderr
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]
    by_identity = {(item["kind"], item["metadata"]["name"]): item for item in documents}

    deployment = by_identity["Deployment", "openfga"]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    environment = {item["name"]: item for item in container["env"]}
    assert container["image"] == IMAGE
    assert deployment["spec"]["replicas"] == 2
    assert deployment["spec"]["strategy"] == {
        "type": "RollingUpdate",
        "rollingUpdate": {"maxSurge": 0, "maxUnavailable": 1},
    }
    assert environment["OPENFGA_AUTHN_METHOD"]["value"] == "preshared"
    assert environment["OPENFGA_HTTP_TLS_ENABLED"]["value"] == "true"
    assert environment["OPENFGA_GRPC_ADDR"]["value"] == "127.0.0.1:8081"
    assert environment["OPENFGA_PLAYGROUND_ENABLED"]["value"] == "false"
    assert environment["OPENFGA_PROFILER_ENABLED"]["value"] == "false"
    assert environment["OPENFGA_DATASTORE_URI"]["valueFrom"]["secretKeyRef"]["key"] == "datastore-uri"
    assert by_identity["Service", "openfga"]["spec"]["type"] == "ClusterIP"
    assert ("Ingress", "openfga") not in by_identity

    migration = by_identity["Job", "openfga-datastore-migrate"]
    assert migration["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert migration["spec"]["template"]["spec"]["serviceAccountName"] == "openfga-migrator"
    admin_service_account = by_identity["ServiceAccount", "openfga-migrator"]
    assert admin_service_account["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert int(admin_service_account["metadata"]["annotations"]["helm.sh/hook-weight"]) < int(
        migration["metadata"]["annotations"]["helm.sh/hook-weight"]
    )
    assert "before-hook-creation" in admin_service_account["metadata"]["annotations"]["helm.sh/hook-delete-policy"]
    assert "hook-succeeded" not in admin_service_account["metadata"]["annotations"]["helm.sh/hook-delete-policy"]
    migration_policy = by_identity["NetworkPolicy", "allow-openfga-migration-egress"]
    policy_hooks = migration_policy["metadata"]["annotations"]
    assert policy_hooks["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert int(policy_hooks["helm.sh/hook-weight"]) < int(migration["metadata"]["annotations"]["helm.sh/hook-weight"])
    assert "hook-succeeded" not in policy_hooks["helm.sh/hook-delete-policy"]
    assert migration_policy["spec"]["egress"][0]["to"] == [{"ipBlock": {"cidr": "10.60.0.12/32"}}]
    assert by_identity["PodDisruptionBudget", "openfga"]["spec"]["minAvailable"] == 1

    portal = by_identity["Deployment", "portal-web"]["spec"]["template"]["spec"]
    portal_environment = {item["name"]: item for item in portal["containers"][0]["env"]}
    assert portal_environment["OPENFGA_API_TOKEN_FILE"]["value"] == "/run/secrets/openfga/token"
    assert portal_environment["OPENFGA_CA_CERT_PATH"]["value"] == "/run/secrets/openfga-ca/ca.crt"
    assert ("NetworkPolicy", "allow-portal-to-openfga") in by_identity
    assert ("NetworkPolicy", "allow-openfga-postgres-egress") in by_identity


@pytest.mark.parametrize(
    "overrides",
    [
        {"image": "openfga/openfga:v1.20.0"},
        {"databaseCidrs": []},
        {"storeId": "latest"},
    ],
)
def test_enabled_contract_rejects_unpinned_or_incomplete_values(tmp_path, overrides) -> None:
    result = _render(tmp_path, "values-aws-dev.yaml", overrides)
    assert result.returncode != 0


def test_policy_runtime_admin_and_schema_owner_have_separate_delivery(tmp_path) -> None:
    result = _render(tmp_path, "values-gcp-dev.yaml")
    assert result.returncode == 0, result.stderr
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]
    objects = {(item["kind"], item["metadata"]["name"]): item for item in documents}
    migration = objects["Job", "openfga-datastore-migrate"]["spec"]["template"]["spec"]
    runtime = objects["Deployment", "openfga"]["spec"]["template"]["spec"]
    admin = objects["Deployment", "openfga-admin"]["spec"]["template"]["spec"]
    assert len({pod["serviceAccountName"] for pod in (migration, runtime, admin)}) == 3
    runtime_env = {item["name"]: item for item in runtime["containers"][0]["env"]}
    admin_env = {item["name"]: item for item in admin["containers"][0]["env"]}
    runtime_secret = runtime_env["OPENFGA_DATASTORE_URI"]["valueFrom"]["secretKeyRef"]["name"]
    admin_secret = admin_env["OPENFGA_DATASTORE_URI"]["valueFrom"]["secretKeyRef"]["name"]
    migrate_env = {item["name"]: item for item in migration["initContainers"][0]["env"]}
    migration_secret = migrate_env["OPENFGA_DATASTORE_URI"]["valueFrom"]["secretKeyRef"]["name"]
    assert len({runtime_secret, admin_secret, migration_secret}) == 3
    assert runtime_env["OPENFGA_AUTHN_PRESHARED_KEYS"]["valueFrom"]["secretKeyRef"]["name"] == runtime_secret
    assert admin_env["OPENFGA_AUTHN_PRESHARED_KEYS"]["valueFrom"]["secretKeyRef"]["name"] == admin_secret
    assert objects["Service", "openfga-admin"]["spec"]["type"] == "ClusterIP"
    assert ("Ingress", "openfga-admin") not in objects
    duties = migration["containers"][0]
    assert duties["name"] == "reconcile-duties"
    assert "-f" in duties["args"]
    assert "runtime_login=synthetic_runtime" in duties["args"]
    assert "admin_login=synthetic_admin" in duties["args"]
    assert "password=" not in str(duties["args"])
    assert "postgres://" not in str(duties["args"])
    assert "openfga-duties.sql" in objects["ConfigMap", "openfga-duties"]["data"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"migrationSecretName": "openfga-runtime"},
        {"adminSecretName": "openfga-runtime"},
        {"adminDatabaseUser": "synthetic_runtime"},
    ],
)
def test_policy_delivery_rejects_collapsed_authority(tmp_path, overrides) -> None:
    assert _render(tmp_path, "values-gcp-dev.yaml", overrides).returncode != 0


def test_native_policy_servers_and_migration_use_their_attached_database_logins(tmp_path):
    users = {role: f"synthetic-{role}@synthetic-project.iam" for role in (
        "portal", "workers", "ctf-scheduler", "provisioner-launcher", "provisioner",
        "openfga-runtime", "openfga-admin", "openfga-migrator",
    )}
    values = _values()
    values["cloudSqlProxy"] = {"enabled": True, "instanceConnectionName": "synthetic-project:us-central1:platform-pg",
                               "databaseUsers": users, "databaseCidrs": ["10.60.0.12/32"]}
    values["openfga"].update(runtimeDatabaseUser=users["openfga-runtime"], adminDatabaseUser=users["openfga-admin"],
                            migrationDatabaseUser=users["openfga-migrator"])
    values["openfga"]["serviceAccountAnnotations"] = {
        duty: {"iam.gke.io/gcp-service-account": users[f"openfga-{duty}"] + ".gserviceaccount.com"}
        for duty in ("runtime", "admin", "migrator")
    }
    generated = tmp_path / "native-policy.json"
    generated.write_text(json.dumps(values))
    result = subprocess.run(["helm", "template", "native-test", str(CHART), "-f", str(CHART / "values-gcp-dev.yaml"),
                             "-f", str(generated)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    objects = {(item["kind"], item["metadata"]["name"]): item for item in yaml.safe_load_all(result.stdout) if item}
    for duty in ("runtime", "admin", "migrator"):
        assert objects["ServiceAccount", f"openfga-{duty}"]["metadata"]["annotations"]["iam.gke.io/gcp-service-account"] == users[f"openfga-{duty}"] + ".gserviceaccount.com"
    for name, role in (("openfga", "openfga-runtime"), ("openfga-admin", "openfga-admin")):
        pod = objects["Deployment", name]["spec"]["template"]["spec"]
        assert pod["initContainers"][0]["restartPolicy"] == "Always"
        assert "--auto-iam-authn" in pod["initContainers"][0]["args"]
        env = {item["name"]: item for item in pod["containers"][0]["env"]}
        assert env["OPENFGA_DATASTORE_URI"]["value"] == "postgres://" + users[role].replace("@", "%40") + "@127.0.0.1:5432/openfga?sslmode=disable"
    migration = objects["Job", "openfga-datastore-migrate"]["spec"]["template"]["spec"]
    assert migration["initContainers"][0]["name"] == "cloud-sql-proxy"
    assert migration["initContainers"][1]["name"] == "migrate"
    assert migration["volumes"][0]["configMap"]["name"] == "openfga-migration-connection"
    service = objects["ConfigMap", "openfga-migration-connection"]["data"]["pg-service.conf"]
    assert f'user={users["openfga-migrator"]}' in service
    assert "password" not in service


def test_partial_policy_binding_and_collapsed_migration_duties_are_rejected(tmp_path):
    for overrides in ({"modelId": ""}, {"migrationDatabaseUser": "synthetic_runtime"}):
        result = _render(tmp_path, "values-gcp-dev.yaml", overrides)
        assert result.returncode != 0


def test_policy_administration_network_is_separate_from_portal_and_worker_clients(tmp_path):
    from test_model_broker import selected

    result = _render(tmp_path, "values-gcp-dev.yaml")
    assert result.returncode == 0, result.stderr
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]
    for target, allowed in (("openfga", {"portal"}), ("openfga-admin", {"openfga-publisher"})):
        selectors = [{"app.kubernetes.io/component": target}]
        ingress = [rule for document in documents if document["kind"] == "NetworkPolicy"
                   and document["metadata"]["namespace"] == "shifter-platform"
                   and selected(document["spec"]["podSelector"], selectors[0])
                   for rule in document["spec"].get("ingress", [])]
        peers = [peer for rule in ingress for peer in rule.get("from", [])
                 if any(port["port"] == 8080 for port in rule.get("ports", []))]
        admitted = {component for component in ("portal", "workers", "worker-engine", "guacamole-client", "openfga-publisher")
                    if any("namespaceSelector" not in peer and "podSelector" in peer
                           and selected(peer["podSelector"], {"app.kubernetes.io/component": component}) for peer in peers)}
        assert admitted == allowed
