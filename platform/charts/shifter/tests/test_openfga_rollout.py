"""Opt-in real-scheduler check on a disposable, exactly two-worker kind cluster.

Run with OPENFGA_ROLLOUT_KUBECONFIG pointing at the kubeconfig for the dedicated
kind-shifter-2315-rollout context. Never uses the operator's current context.
"""

from __future__ import annotations

import json
import os
import subprocess
from uuid import uuid4

import pytest
import yaml

from test_openfga import _render


@pytest.mark.skipif(not os.environ.get("OPENFGA_ROLLOUT_KUBECONFIG"), reason="requires disposable two-worker kind cluster")
def test_openfga_upgrade_completes_with_only_two_eligible_nodes(tmp_path) -> None:
    kubeconfig = os.environ["OPENFGA_ROLLOUT_KUBECONFIG"]

    def kubectl(*args: str, manifest: dict | None = None) -> str:
        result = subprocess.run(
            ["kubectl", "--kubeconfig", kubeconfig, "--context", "kind-shifter-2315-rollout", *args],
            input=json.dumps(manifest) if manifest else None,
            capture_output=True,
            text=True,
            timeout=210,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    nodes = json.loads(kubectl("get", "nodes", "-o", "json"))["items"]
    workers = [node for node in nodes if "node-role.kubernetes.io/control-plane" not in node["metadata"]["labels"]]
    assert len(workers) == 2
    result = _render(tmp_path, "values-aws-dev.yaml")
    assert result.returncode == 0, result.stderr
    deployment = next(
        item for item in yaml.safe_load_all(result.stdout)
        if item and item["kind"] == "Deployment" and item["metadata"]["name"] == "openfga"
    )
    namespace = f"openfga-rollout-{uuid4().hex[:10]}"
    deployment["metadata"]["namespace"] = namespace
    pod = deployment["spec"]["template"]["spec"]
    # Retain the rendered controller strategy, replicas, required anti-affinity,
    # security, resources and released server image. This placement-only fixture
    # uses in-memory storage, no credentials, and no exposed Service.
    pod.pop("serviceAccountName")
    pod.pop("volumes", None)
    pod["nodeSelector"] = {"openfga-rollout-worker": "true"}
    container = pod["containers"][0]
    container["args"] = ["run", "--datastore-engine=memory", "--playground-enabled=false"]
    container.pop("env")
    container.pop("volumeMounts", None)
    for probe in ("readinessProbe", "livenessProbe"):
        container[probe]["httpGet"]["scheme"] = "HTTP"
    for node in workers:
        kubectl("label", "node", node["metadata"]["name"], "openfga-rollout-worker=true", "--overwrite")
    kubectl("create", "namespace", namespace)
    try:
        kubectl("apply", "-f", "-", manifest=deployment)
        kubectl("-n", namespace, "rollout", "status", "deployment/openfga", "--timeout=180s")
        before = json.loads(kubectl("-n", namespace, "get", "pods", "-o", "json"))["items"]
        assert len(before) == 2
        assert len({item["spec"]["nodeName"] for item in before}) == 2
        deployment["spec"]["template"]["metadata"]["annotations"] = {"rollout-test/revision": "2"}
        kubectl("apply", "-f", "-", manifest=deployment)
        kubectl("-n", namespace, "rollout", "status", "deployment/openfga", "--timeout=180s")
        status = json.loads(kubectl("-n", namespace, "get", "deployment", "openfga", "-o", "json"))["status"]
        assert status["updatedReplicas"] == status["readyReplicas"] == status["availableReplicas"] == 2
        after = json.loads(kubectl("-n", namespace, "get", "pods", "-o", "json"))["items"]
        active = [item for item in after if not item["metadata"].get("deletionTimestamp")]
        assert len(active) == 2
        assert not ({item["metadata"]["uid"] for item in before} & {item["metadata"]["uid"] for item in active})
    finally:
        kubectl("delete", "namespace", namespace, "--wait=false")
