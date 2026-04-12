"""Tests for rendering GKE Workload Identity service account patches."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(module_filename: str, module_name: str):
    module_path = Path(__file__).resolve().parents[1] / module_filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_serviceaccount_patch_uses_project_service_accounts():
    module = _load_module("render_serviceaccount_patch.py", "render_serviceaccount_patch")

    rendered = module.render_serviceaccount_patch(
        {
            "portal": "shiftergcpdev-portal@prod-rwctxzl6shxk.iam.gserviceaccount.com",
            "workers": "shiftergcpdev-workers@prod-rwctxzl6shxk.iam.gserviceaccount.com",
            "provisioner": "shiftergcpdev-provisioner@prod-rwctxzl6shxk.iam.gserviceaccount.com",
        }
    )

    assert "iam.gke.io/gcp-service-account: shiftergcpdev-portal@prod-rwctxzl6shxk.iam.gserviceaccount.com" in rendered
    assert "iam.gke.io/gcp-service-account: shiftergcpdev-workers@prod-rwctxzl6shxk.iam.gserviceaccount.com" in rendered
    assert "iam.gke.io/gcp-service-account: shiftergcpdev-provisioner@prod-rwctxzl6shxk.iam.gserviceaccount.com" in rendered


def test_render_serviceaccount_patch_requires_all_roles():
    module = _load_module("render_serviceaccount_patch.py", "render_serviceaccount_patch")

    try:
        module.render_serviceaccount_patch(
            {
                "portal": "portal@example.com",
                "workers": "workers@example.com",
            }
        )
    except ValueError as exc:
        assert "provisioner" in str(exc)
    else:
        raise AssertionError("render_serviceaccount_patch should fail when a required role is missing")
