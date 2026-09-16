"""The Actions compatibility artifacts come from the canonical Helm chart."""

import importlib.util
import json
from pathlib import Path

import yaml


def test_disabled_and_enabled_projection_use_real_chart(tmp_path):
    path = Path(__file__).resolve().parents[1] / "render_model_broker.py"
    spec = importlib.util.spec_from_file_location("render_model_broker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.render_resources({"enabled": False}, image="unused", private_service_cidrs=[]) == ""
    root = path.parents[2]
    catalog = (root / "docs/architecture/model-access/example-policy.v1.json").read_text()
    broker = {
        "enabled": True,
        "hostname": "models.example.test",
        "vip": "10.40.0.25",
        "admitted_subnets": ["10.50.1.0/24"],
        "global_access": False,
        "tls_secret_name": "model-broker-tls-v1",
        "control_tls_secret_name": "model-control-tls-v1",
        "trust_configmap_name": "model-ca-v1",
        "gsa": "model-broker@platform-example.iam.gserviceaccount.com",
        "region": "us-central1",
        "catalog_json": catalog,
        "catalog_digest": json.loads(catalog)["digest"],
        "control_env": {
            "MODEL_ACCESS_ENABLED": "false",
            "MODEL_ACCESS_CATALOG_PATH": "/etc/shifter/model-access/catalog.json",
            "MODEL_ACCESS_CATALOG_DIGEST": json.loads(catalog)["digest"],
        },
        "identities_json": "{}",
    }
    rendered = module.render_resources(
        broker, image="registry.example/platform@sha256:" + "1" * 64, private_service_cidrs=["10.60.0.1/32"]
    )
    docs = list(yaml.safe_load_all(rendered))
    identities = {(doc["kind"], doc["metadata"]["name"]) for doc in docs}
    assert ("Deployment", "model-broker") in identities
    assert ("Deployment", "model-access-control") in identities
    assert ("Deployment", "portal-web") not in identities
    assert ("ValidatingAdmissionPolicy", "restrict-provisioner-jobs") not in identities
    policy = next(doc for doc in docs if doc["metadata"]["name"] == "allow-platform-private-service-egress")
    assert policy["spec"]["podSelector"]["matchExpressions"][0]["values"] == ["model-broker"]


def test_combining_manifests_replaces_shared_policies_before_any_apply():
    path = Path(__file__).resolve().parents[1] / "render_model_broker.py"
    spec = importlib.util.spec_from_file_location("render_model_broker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    broad = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "allow-platform-private-service-egress", "namespace": "shifter-platform"},
        "spec": {"podSelector": {}},
    }
    narrow = {
        **broad,
        "spec": {
            "podSelector": {
                "matchExpressions": [
                    {"key": "app.kubernetes.io/component", "operator": "NotIn", "values": ["model-broker"]}
                ]
            }
        },
    }
    unrelated = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "portal-web"}}
    combined = list(
        yaml.safe_load_all(module.combine_resources(yaml.safe_dump_all([broad, unrelated]), yaml.safe_dump(narrow)))
    )
    assert combined == [unrelated, narrow]


def test_deploy_job_installs_renderer_dependencies_before_use():
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/_gcp-dev.yml").read_text())
    steps = workflow["jobs"]["deploy"]["steps"]
    render_index = next(
        index for index, step in enumerate(steps) if "scripts/gcp/render_model_broker.py" in step.get("run", "")
    )
    setup = steps[:render_index]
    assert any(step.get("uses", "").startswith("astral-sh/setup-uv@") for step in setup)
    helm = [step for step in setup if "HELM_SHA256" in step.get("env", {})]
    assert len(helm) == 1
    assert "sha256sum -c -" in helm[0]["run"]
    assert "GITHUB_PATH" in helm[0]["run"]


def test_actual_actions_policies_are_narrowed_and_control_rolls_with_runtime():
    import subprocess

    import test_render_private_service_netpol as private

    root = Path(__file__).resolve().parents[3]
    path = root / "scripts/gcp/render_model_broker.py"
    spec = importlib.util.spec_from_file_location("broker_combined_review", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = subprocess.run(
        ["kubectl", "kustomize", str(root / "platform/k8s/gcp/base")], check=True, capture_output=True, text=True
    ).stdout
    base_docs = list(yaml.safe_load_all(base))
    patches = list(
        yaml.safe_load_all((root / "platform/k8s/gcp/overlays/gcp-dev/patch-runtime-secretref.patch").read_text())
    )
    worker_patch = next(doc for doc in patches if doc["metadata"]["name"] == "worker-engine")
    worker = next(
        doc for doc in base_docs if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "worker-engine"
    )
    worker["spec"]["template"]["spec"]["containers"][0]["envFrom"] = worker_patch["spec"]["template"]["spec"][
        "containers"
    ][0]["envFrom"]
    base = yaml.safe_dump_all(base_docs)
    netpol = private._load_module("render_private_service_netpol.py", "private_review")
    base += "\n---\n" + netpol.render_netpol(private._outputs())
    # The deployment lane's generated runtime ConfigMap is part of this same apply.
    runtime = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "platform-runtime", "namespace": "shifter-platform"},
        "data": {"MODEL_ACCESS_CATALOG_DIGEST": "old"},
    }
    control = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "model-access-control", "namespace": "shifter-platform"},
        "spec": {
            "template": {
                "metadata": {"annotations": {"checksum/runtime-config": "empty"}},
                "spec": {"containers": [{"name": "model-access-control"}]},
            }
        },
    }
    versions = []
    for value in ("old", "new", "new"):
        runtime["data"]["MODEL_ACCESS_CATALOG_DIGEST"] = value
        combined = list(
            yaml.safe_load_all(
                module.combine_resources(base + "\n---\n" + yaml.safe_dump(runtime), yaml.safe_dump(control))
            )
        )
        policies = {
            doc["metadata"]["name"]: doc["spec"]
            for doc in combined
            if doc["kind"] == "NetworkPolicy"
            and doc["metadata"].get("namespace") == "shifter-platform"
            and doc["spec"].get("egress")
        }
        assert {
            "allow-platform-google-apis-egress",
            "allow-platform-private-service-egress-generated",
        } <= policies.keys()
        for policy in policies.values():
            assert {
                "key": "app.kubernetes.io/component",
                "operator": "NotIn",
                "values": ["model-broker"],
            } in policy["podSelector"].get("matchExpressions", [])
        versions.append(
            next(
                doc
                for doc in combined
                if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "model-access-control"
            )["spec"]["template"]["metadata"]["annotations"]["checksum/runtime-config"]
        )
    applied_control = next(
        doc for doc in combined if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "model-access-control"
    )
    assert (
        applied_control["spec"]["template"]["spec"]["containers"][0]["envFrom"]
        == worker_patch["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    )
    assert versions[0] != versions[1]
    assert versions[1] == versions[2]


def test_disable_waits_for_dependents_and_control_restarts_after_secret_sync():
    root = Path(__file__).resolve().parents[3]
    steps = yaml.safe_load((root / ".github/workflows/_gcp-dev.yml").read_text())["jobs"]["deploy"]["steps"]
    apply = next(step["run"] for step in steps if "scripts/gcp/render_model_broker.py" in step.get("run", ""))
    delete = apply[apply.index("kubectl delete deployment") : apply.index("kubectl delete service,")]
    assert "--cascade=foreground" in delete and "--wait=true" in delete and "--timeout=180s" in delete
    assert (
        apply.index("kubectl delete deployment")
        < apply.index("kubectl delete networkpolicy")
        < apply.index("kubectl apply")
    )
    sync = next(index for index, step in enumerate(steps) if step.get("name") == "Sync Guacamole runtime secret")
    restart = next(step["run"] for step in steps[sync + 1 :] if step.get("name") == "Restart control-plane deployments")
    assert 'if [ "${MODEL_BROKER_ENABLED}" = true ]; then' in restart
    assert "kubectl rollout restart deployment/model-access-control" in restart
