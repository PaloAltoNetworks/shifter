"""The Actions compatibility artifacts come from the canonical Helm chart."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml


@pytest.mark.integration
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
    assert ("Deployment", "model-provider-egress") in identities
    assert ("NetworkPolicy", "model-provider-egress-boundary") in identities
    assert ("Deployment", "portal-web") not in identities
    assert ("ValidatingAdmissionPolicy", "restrict-provisioner-jobs") not in identities
    policy = next(doc for doc in docs if doc["metadata"]["name"] == "allow-platform-private-service-egress")
    assert policy["spec"]["podSelector"]["matchExpressions"][0]["values"] == ["model-broker", "model-provider-egress"]


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
                    {
                        "key": "app.kubernetes.io/component",
                        "operator": "NotIn",
                        "values": ["model-broker", "model-provider-egress"],
                    }
                ]
            }
        },
    }
    unrelated = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "portal-web"}}
    combined = list(
        yaml.safe_load_all(module.combine_resources(yaml.safe_dump_all([broad, unrelated]), yaml.safe_dump(narrow)))
    )
    assert combined == [unrelated, narrow]


def test_normal_apply_projects_selected_capacity_profile():
    path = Path(__file__).resolve().parents[1] / "render_model_broker.py"
    spec = importlib.util.spec_from_file_location("render_model_broker_capacity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    documents = [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": "shifter-platform"},
            "spec": {
                "replicas": 1,
                "template": {
                    "metadata": {},
                    "spec": {
                        "containers": [{"name": container, "resources": {}}],
                    },
                },
            },
        }
        for name, container in (
            ("portal-web", "portal"),
            ("guacd", "guacd"),
            ("guacamole-client", "guacamole-client"),
        )
    ]
    documents.append(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "platform-runtime", "namespace": "shifter-platform"},
            "data": {},
        }
    )

    applied = list(
        yaml.safe_load_all(module.apply_capacity_profile(yaml.safe_dump_all(documents), "gcp-shared-v1-p10"))
    )
    portal = next(document for document in applied if document.get("metadata", {}).get("name") == "portal-web")
    assert portal["spec"]["replicas"] == 2
    assert portal["spec"]["template"]["spec"]["containers"][0]["resources"] == {
        "requests": {"cpu": "500m", "memory": "2Gi", "ephemeral-storage": "256Mi"},
        "limits": {"cpu": "2", "memory": "4Gi", "ephemeral-storage": "256Mi"},
    }
    assert portal["metadata"]["annotations"]["shifter.dev/capacity-profile"] == "gcp-shared-v1-p10"
    assert portal["spec"]["template"]["metadata"]["labels"]["shifter.dev/capacity-profile"] == ("gcp-shared-v1-p10")
    runtime = next(document for document in applied if document.get("kind") == "ConfigMap")
    assert runtime["data"]["SHARED_SERVICE_CAPACITY_PROFILE"] == "gcp-shared-v1-p10"
    assert runtime["data"]["PORTAL_WEB_WORKERS"] == "4"
    # The release apply owns the autoscalers and the Guacamole connection ceiling,
    # so a tier change through CI cannot keep the bootstrap-time bounds.
    autoscalers = {
        document["metadata"]["name"]: document["spec"]
        for document in applied
        if document.get("kind") == "HorizontalPodAutoscaler"
    }
    assert {name: (spec["minReplicas"], spec["maxReplicas"]) for name, spec in autoscalers.items()} == {
        "portal-web": (2, 4),
        "guacd": (1, 3),
    }
    assert autoscalers["portal-web"]["scaleTargetRef"]["name"] == "portal-web"
    client = next(document for document in applied if document.get("metadata", {}).get("name") == "guacamole-client")
    assert {"name": "POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS", "value": "10"} in (
        client["spec"]["template"]["spec"]["containers"][0]["env"]
    )


def test_a_tier_change_replaces_stale_autoscalers_and_the_connection_ceiling():
    path = Path(__file__).resolve().parents[1] / "render_model_broker.py"
    spec = importlib.util.spec_from_file_location("render_model_broker_tier_change", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    documents = [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": "shifter-platform"},
            "spec": {
                "replicas": 1,
                "template": {
                    "metadata": {},
                    "spec": {
                        "containers": [
                            {
                                "name": container,
                                "resources": {},
                                "env": [{"name": "POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS", "value": "30"}],
                            }
                        ]
                    },
                },
            },
        }
        for name, container in (
            ("portal-web", "portal"),
            ("guacd", "guacd"),
            ("guacamole-client", "guacamole-client"),
        )
    ]
    documents += [
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "platform-runtime"}, "data": {}},
        {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {"name": "portal-web", "namespace": "shifter-platform"},
            "spec": {"minReplicas": 5, "maxReplicas": 10},
        },
    ]

    applied = list(
        yaml.safe_load_all(module.apply_capacity_profile(yaml.safe_dump_all(documents), "gcp-shared-v1-p300"))
    )

    portal_autoscalers = [
        document
        for document in applied
        if document.get("kind") == "HorizontalPodAutoscaler" and document["metadata"]["name"] == "portal-web"
    ]
    assert len(portal_autoscalers) == 1
    assert (portal_autoscalers[0]["spec"]["minReplicas"], portal_autoscalers[0]["spec"]["maxReplicas"]) == (38, 76)
    client = next(document for document in applied if document.get("metadata", {}).get("name") == "guacamole-client")
    env = client["spec"]["template"]["spec"]["containers"][0]["env"]
    assert [entry["value"] for entry in env if entry["name"] == "POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS"] == ["300"]


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


def test_migration_does_not_load_the_unmounted_runtime_catalog(tmp_path):
    import subprocess
    import sys

    from shared.model_access.runtime import load_mounted_catalog

    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/_gcp-dev.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Run database migrations")
    )
    assert "scripts/gcp/render_migration_job.py" in step["run"]
    outputs = tmp_path / "outputs.json"
    outputs.write_text(
        json.dumps(
            {
                "identity_platform_project_id": {"value": "synthetic-project"},
                "workload_service_accounts": {"value": {}},
            }
        )
    )
    manifest = tmp_path / "migration.yaml"
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/gcp/render_migration_job.py"),
            "--terraform-output",
            str(outputs),
            "--image",
            "example.invalid/platform@sha256:" + "1" * 64,
            "--job-name",
            "platform-migration-test",
            "--output",
            str(manifest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    container = yaml.safe_load(manifest.read_text())["spec"]["template"]["spec"]["containers"][0]
    assert container["args"] == [
        "/bin/sh",
        "-c",
        "python manage.py reconcile_gcp_database_duties"
        " && python manage.py bootstrap_inbox_catalog"
        " && python manage.py seed_raes_image_registry"
        " && python manage.py acquire_feature_artifacts",
    ]
    effective = {
        "MODEL_ACCESS_ENABLED": "true",
        "MODEL_ACCESS_CATALOG_PATH": "/unmounted/catalog.json",
        "MODEL_ACCESS_CATALOG_DIGEST": "sha256:" + "a" * 64,
        **{item["name"]: item["value"] for item in container["env"] if "value" in item},
    }
    assert (
        load_mounted_catalog(
            enabled=effective["MODEL_ACCESS_ENABLED"] == "true",
            path=effective["MODEL_ACCESS_CATALOG_PATH"],
            expected_digest=effective["MODEL_ACCESS_CATALOG_DIGEST"],
        )
        is None
    )


@pytest.mark.integration
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
                "spec": {
                    "containers": [
                        {
                            "name": "model-access-control",
                            "env": [
                                {"name": "MODEL_ACCESS_ENABLED", "value": "true"},
                                {
                                    "name": "MODEL_ACCESS_CATALOG_PATH",
                                    "value": "/etc/shifter/model-access/catalog.json",
                                },
                                {"name": "MODEL_ACCESS_CATALOG_DIGEST", "value": "old"},
                            ],
                        }
                    ]
                },
            }
        },
    }
    catalog = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "model-broker-catalog", "namespace": "shifter-platform"},
        "data": {"enrollment.json": json.dumps({"MODEL_BROKER_GUEST_VIP": "10.40.0.25"})},
    }
    versions = []
    for value in ("old", "new", "new"):
        control["spec"]["template"]["spec"]["containers"][0]["env"][2]["value"] = value
        combined = list(
            yaml.safe_load_all(
                module.combine_resources(
                    base + "\n---\n" + yaml.safe_dump(runtime), yaml.safe_dump_all([control, catalog])
                )
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
                "values": ["model-broker", "model-provider-egress"],
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
    applied_runtime = next(
        doc for doc in combined if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == "platform-runtime"
    )
    assert applied_runtime["data"]["MODEL_BROKER_GUEST_VIP"] == "10.40.0.25"
    assert applied_runtime["data"]["MODEL_ACCESS_ENABLED"] == "true"
    assert applied_runtime["data"]["MODEL_ACCESS_CATALOG_DIGEST"] == "new"
    applied_worker = next(
        doc for doc in combined if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "worker-engine"
    )
    assert any(
        mount["mountPath"] == "/etc/shifter/model-access"
        for mount in applied_worker["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
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
