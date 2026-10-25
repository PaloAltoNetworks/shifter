"""The CI lane projects acquisition from the canonical chart, matching bootstrap (#2479)."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "render_feature_artifact_acquisition.py"
IMAGE = "registry.example.test/shifter/portal@sha256:" + "c" * 64
ACQUIRER = "acquirer@platform-example.iam.gserviceaccount.com"
BASE = """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: platform-runtime
  namespace: shifter-platform
data:
  CLOUD_PROVIDER: gcp
---
apiVersion: v1
kind: Namespace
metadata:
  name: shifter-platform
"""


def _module():
    spec = importlib.util.spec_from_file_location("render_feature_artifact_acquisition", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(tmp_path, accounts):
    module = _module()
    outputs = tmp_path / "outputs.json"
    outputs.write_text(json.dumps({"workload_service_accounts": {"value": accounts}}))
    manifest = tmp_path / "base.yaml"
    manifest.write_text(BASE)
    output = tmp_path / "out.yaml"
    assert (
        module.main(
            [
                "--terraform-output",
                str(outputs),
                "--platform-image",
                IMAGE,
                "--manifest",
                str(manifest),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    return [doc for doc in yaml.safe_load_all(output.read_text()) if doc]


def test_without_acquirer_identity_manifest_is_unchanged(tmp_path):
    documents = _run(tmp_path, {"portal": "portal@platform-example.iam.gserviceaccount.com"})
    assert documents == [doc for doc in yaml.safe_load_all(BASE) if doc]


def test_add_acquisition_requires_one_runtime_configmap():
    module = _module()
    with pytest.raises(ValueError, match="platform-runtime"):
        module.add_acquisition("apiVersion: v1\nkind: Namespace\nmetadata:\n  name: x\n", [], image=IMAGE)


@pytest.mark.integration
def test_acquirer_identity_projects_chart_resources_and_job_image(tmp_path):
    documents = _run(tmp_path, {"artifact-acquirer": ACQUIRER})
    runtime = next(doc for doc in documents if doc["kind"] == "ConfigMap")
    assert runtime["data"] == {"CLOUD_PROVIDER": "gcp", "FEATURE_ARTIFACT_JOB_IMAGE": IMAGE}
    added = {(doc["kind"], doc["metadata"].get("namespace"), doc["metadata"]["name"]) for doc in documents[2:]}
    assert ("Namespace", None, "shifter-acquisition") in added
    assert ("ServiceAccount", "shifter-acquisition", "artifact-acquirer") in added
    assert ("RoleBinding", "shifter-acquisition", "acquisition-controller") in added
    assert ("NetworkPolicy", "shifter-acquisition", "acquisition-https-egress") in added
    assert ("ValidatingAdmissionPolicyBinding", None, "restrict-feature-artifact-jobs") in added
    assert all(
        doc["metadata"].get("namespace") == "shifter-acquisition"
        or doc["metadata"]["name"] in {"shifter-acquisition", "restrict-feature-artifact-jobs"}
        for doc in documents[2:]
    )
    account = next(doc for doc in documents if doc["kind"] == "ServiceAccount")
    assert account["metadata"]["annotations"] == {"iam.gke.io/gcp-service-account": ACQUIRER}
    policy = next(doc for doc in documents if doc["kind"] == "ValidatingAdmissionPolicy")
    assert f"variables.container.image == '{IMAGE}'" in json.dumps(policy)
    binding = next(doc for doc in documents if doc["kind"] == "RoleBinding")
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": "provisioner-launcher", "namespace": "shifter-platform"}
    ]
