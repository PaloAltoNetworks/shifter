"""Tests for the Connect-Gateway-safe post-deploy smoke Job renderer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "render_smoke_job.py"
    spec = importlib.util.spec_from_file_location("render_smoke_job", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deployment() -> dict[str, object]:
    return {
        "metadata": {"name": "portal-web", "namespace": "shifter-platform"},
        "spec": {
            "template": {
                "metadata": {"labels": {"app.kubernetes.io/component": "portal"}},
                "spec": {
                    "serviceAccountName": "portal",
                    "automountServiceAccountToken": False,
                    "nodeSelector": {"node-restriction.kubernetes.io/shifter-pool": "access"},
                    "tolerations": [{"key": "dedicated", "value": "access", "effect": "NoSchedule"}],
                    "restartPolicy": "Always",
                    "containers": [
                        {
                            "name": "portal",
                            "image": f"registry.example/portal@sha256:{'1' * 64}",
                            "envFrom": [{"configMapRef": {"name": "platform-runtime"}}],
                            "ports": [{"name": "http", "containerPort": 8000}],
                            "readinessProbe": {"httpGet": {"path": "/health/", "port": "http"}},
                            "livenessProbe": {"httpGet": {"path": "/health/", "port": "http"}},
                            "securityContext": {"readOnlyRootFilesystem": True},
                        }
                    ],
                },
            }
        },
    }


def test_job_keeps_portal_runtime_without_entering_the_service_selector() -> None:
    module = _module()

    job = module.render_smoke_job(
        _deployment(),
        name="post-deploy-smoke-123-1",
        secret_name="post-deploy-smoke-123-1-identity",
        variant="linux",
        active_deadline_seconds=3600,
    )

    template = job["spec"]["template"]
    pod_spec = template["spec"]
    portal = pod_spec["containers"][0]
    assert template["metadata"]["labels"]["app.kubernetes.io/component"] == "post-deploy-smoke"
    assert "app.kubernetes.io/part-of" not in template["metadata"]["labels"]
    assert pod_spec["serviceAccountName"] == "portal"
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_spec["nodeSelector"] == {"node-restriction.kubernetes.io/shifter-pool": "access"}
    assert pod_spec["restartPolicy"] == "Never"
    assert portal["image"].endswith("1" * 64)
    assert "command" not in portal
    assert portal["args"] == ["python", "manage.py", "run_post_deploy_smoke", "--variant", "linux"]
    assert "ports" not in portal and "readinessProbe" not in portal and "livenessProbe" not in portal
    assert portal["env"] == [
        {
            "name": "SMOKE_TEST_USER_EMAIL",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "post-deploy-smoke-123-1-identity",
                    "key": "SMOKE_TEST_USER_EMAIL",
                }
            },
        }
    ]


def test_job_rejects_mutable_portal_image() -> None:
    module = _module()
    deployment = _deployment()
    deployment["spec"]["template"]["spec"]["containers"][0]["image"] = "registry.example/portal:latest"

    with pytest.raises(ValueError, match="exact digest"):
        module.render_smoke_job(
            deployment,
            name="post-deploy-smoke-123-1",
            secret_name="post-deploy-smoke-123-1-identity",
            variant="linux",
            active_deadline_seconds=3600,
        )
