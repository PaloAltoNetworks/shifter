"""Native database configuration reaches every GCP client with its own identity."""

import json
from ipaddress import ip_address, ip_network
import subprocess
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[1]


def test_native_proxy_and_database_user_reach_all_runtime_consumers(tmp_path):
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
    from test_model_broker import enabled_values

    values["modelBroker"] = enabled_values()["modelBroker"]
    broker = values["modelBroker"]
    catalog = json.loads(
        (
            CHART.parents[2] / "docs/architecture/model-access/example-policy.v3.json"
        ).read_text()
    )
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
    broker["control_env"].update(
        MODEL_ACCESS_ENABLED="true", MODEL_ACCESS_CATALOG_DIGEST=catalog["digest"]
    )
    path = tmp_path / "native.json"
    path.write_text(json.dumps(values))
    result = subprocess.run(
        [
            "helm",
            "template",
            "native-test",
            str(CHART),
            "-f",
            str(CHART / "values-gcp-dev.yaml"),
            "-f",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]
    guacamole = next(
        item
        for item in documents
        if item["kind"] == "Deployment"
        and item["metadata"]["name"] == "guacamole-client"
    )
    guac_pod = guacamole["spec"]["template"]["spec"]
    assert guac_pod["serviceAccountName"] == "guacamole-client"
    assert "--auto-iam-authn" not in guac_pod["initContainers"][0]["args"]
    assert {"name": "POSTGRESQL_HOSTNAME", "value": "127.0.0.1"} in guac_pod[
        "containers"
    ][0]["env"]
    from test_model_broker import selected

    for component, expected in (
        ("portal", True),
        ("model-access-control", True),
        ("guacamole-client", True),
        ("migrator", True),
        ("guacd", False),
        ("runtime-plugin", False),
    ):
        policies = [
            item["spec"]
            for item in documents
            if item["kind"] == "NetworkPolicy"
            and item["metadata"]["namespace"] == "shifter-platform"
            and selected(
                item["spec"]["podSelector"], {"app.kubernetes.io/component": component}
            )
        ]
        for destination in ("10.60.0.12", "10.60.0.13"):
            permitted = any(
                any(port["port"] == 3307 for port in rule.get("ports", []))
                and any(
                    "ipBlock" in peer
                    and ip_address(destination) in ip_network(peer["ipBlock"]["cidr"])
                    for peer in rule.get("to", [])
                )
                for policy in policies
                for rule in policy.get("egress", [])
            )
            assert permitted == (expected and destination == "10.60.0.12")
    for document in documents:
        if document["kind"] != "Deployment":
            continue
        pod = document["spec"]["template"]["spec"]
        if not any(
            ref.get("configMapRef", {}).get("name") == "platform-runtime"
            for container in pod["containers"]
            for ref in container.get("envFrom", [])
        ):
            continue
        proxy = pod["initContainers"][0]
        assert len(pod["initContainers"]) == 1
        assert proxy["restartPolicy"] == "Always"
        assert "--address=127.0.0.1" in proxy["args"]
        assert "--private-ip" in proxy["args"]
        if document["metadata"]["name"] == "guacamole-client":
            assert "--auto-iam-authn" not in proxy["args"]
            continue
        role = pod["serviceAccountName"]
        environment = {item["name"]: item for item in pod["containers"][0]["env"]}
        assert "--auto-iam-authn" in proxy["args"]
        assert environment["DB_USER"]["value"] == users[role]
        assert environment["DB_AUTH_MODE"]["value"] == "cloud-sql-proxy"
        assert environment["DB_HOST"]["value"] == "127.0.0.1"
