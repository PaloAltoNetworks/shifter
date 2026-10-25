"""Policy secrets cross only the named provider/Kubernetes boundaries."""

import base64
import importlib.util
import json
from pathlib import Path

import pytest


def test_policy_secret_delivery_is_separate_and_rejects_overlapping_authority(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "policy_secrets", Path(__file__).resolve().parents[1] / "sync_openfga_secrets.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime_key, admin_key = "synthetic-runtime-key-" + "r" * 32, "synthetic-admin-key-" + "a" * 32
    payloads = {
        "runtime": {
            "server-preshared-keys": runtime_key,
            "api-token": runtime_key,
            "tls.crt": "runtime-cert",
            "tls.key": "runtime-private-key",
        },
        "admin": {
            "server-preshared-keys": admin_key,
            "api-token": admin_key,
            "tls.crt": "admin-cert",
            "tls.key": "admin-private-key",
        },
        "ca": {"ca.crt": "public-ca"},
    }
    delivered = []
    calls = []

    def run(command, **kwargs):
        from subprocess import CompletedProcess

        calls.append(command)
        if command[0] == "gcloud":
            payload = payloads[command[-1]]
            return CompletedProcess(command, 0, json.dumps(payload), "")
        assert command == ["kubectl", "apply", "--server-side", "--field-manager=shifter-policy-secrets", "-f", "-"]
        delivered.append(json.loads(kwargs["input"]))
        return CompletedProcess(command, 0, "applied", "")

    monkeypatch.setattr(module.subprocess, "run", run)
    policy = {
        "enabled": True,
        "runtime_secret_ref": "projects/synthetic-project/secrets/runtime",
        "admin_secret_ref": "projects/synthetic-project/secrets/admin",
        "ca_secret_ref": "projects/synthetic-project/secrets/ca",
    }
    module.sync(policy)
    assert {item["metadata"]["name"] for item in delivered} == {"openfga-runtime", "openfga-admin", "openfga-ca"}
    assert delivered[-1]["kind"] == "ConfigMap" and delivered[-1]["data"] == {"ca.crt": "public-ca"}
    assert "admin-private-key" not in json.dumps(delivered[0])
    assert base64.b64decode(delivered[0]["data"]["runtime-preshared-key"]).decode() == runtime_key
    assert runtime_key not in json.dumps(calls) and admin_key not in json.dumps(calls)
    assert "kubectl.kubernetes.io/last-applied-configuration" not in json.dumps(delivered)
    import subprocess

    import yaml

    values = {
        "openfga": {
            "enabled": True,
            "storeId": "01J00000000000000000000001",
            "modelId": "01J00000000000000000000000",
            "databaseCidrs": ["10.60.0.12/32"],
            "runtimeDatabaseUser": "synthetic_runtime",
            "adminDatabaseUser": "synthetic_admin",
        },
    }
    # Restore the real tool boundary for Helm; retain the already captured Secret payload.
    monkeypatch.undo()
    chart = Path(__file__).resolve().parents[3] / "platform/charts/shifter"
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "values.json"
        path.write_text(json.dumps(values))
        rendered = subprocess.run(
            ["helm", "template", "key-contract", str(chart), "-f", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
    portal = next(
        item
        for item in yaml.safe_load_all(rendered.stdout)
        if item and item["kind"] == "Deployment" and item["metadata"]["name"] == "portal-web"
    )
    volumes = portal["spec"]["template"]["spec"]["volumes"]
    required = next(item for item in volumes if item["name"] == "openfga-token")["secret"]
    assert required["secretName"] == delivered[0]["metadata"]["name"]
    assert {item["key"] for item in required["items"]} <= delivered[0]["data"].keys()
    monkeypatch.setattr(module.subprocess, "run", run)
    payloads["admin"]["server-preshared-keys"] = runtime_key
    delivered.clear()
    with pytest.raises(ValueError, match="separate"):
        module.sync(policy)
    assert delivered == []
