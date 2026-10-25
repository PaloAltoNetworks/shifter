"""Tests for the GCP overlay deploy-identity renderer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "render_overlay_identity.py"
    spec = importlib.util.spec_from_file_location("render_overlay_identity", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PLACEHOLDER_KUSTOMIZATION = """\
images:
  - name: us-docker.pkg.dev/placeholder-project/shifter/portal
    newName: us-central1-docker.pkg.dev/shifter-orthanc/shifter-orthanc-portal/portal
    newTag: 0.0.0
  - name: us-docker.pkg.dev/placeholder-project/shifter/guacd
    newName: us-central1-docker.pkg.dev/shifter-orthanc/shifter-orthanc-guacd/guacd
    newTag: 0.0.0
"""

_PLACEHOLDER_SA_PATCH = """\
apiVersion: v1
kind: ServiceAccount
metadata:
  name: portal
  namespace: shifter-platform
  annotations:
    iam.gke.io/gcp-service-account: shifterorthanc-portal@shifter-orthanc.iam.gserviceaccount.com
---
apiVersion: v1
kind: ServiceAccount
metadata:
  # account_id is shortened to "prov-launcher" (GCP 30-char SA id cap).
  name: provisioner-launcher
  namespace: shifter-platform
  annotations:
    iam.gke.io/gcp-service-account: shifterorthanc-prov-launcher@shifter-orthanc.iam.gserviceaccount.com
"""

_IMAGE_ROOTS = {
    "portal": "us-central1-docker.pkg.dev/example-gcp-project/shifter-orthanc-portal/portal",
    "guacd": "us-central1-docker.pkg.dev/example-gcp-project/shifter-orthanc-guacd/guacd",
    "guacamole-client": (
        "us-central1-docker.pkg.dev/example-gcp-project/shifter-orthanc-guacamole-client/guacamole-client"
    ),
}

_WORKLOAD_SERVICE_ACCOUNTS = {
    "portal": "shifterorthanc-portal@example-gcp-project.iam.gserviceaccount.com",
    "provisioner-launcher": "shifterorthanc-prov-launcher@example-gcp-project.iam.gserviceaccount.com",
}


def test_render_kustomization_images_rewrites_newname_from_outputs():
    module = _load_module()

    rendered = module.render_kustomization_images(_PLACEHOLDER_KUSTOMIZATION, _IMAGE_ROOTS)

    assert "shifter-orthanc/shifter-orthanc-portal/portal" not in rendered
    assert "newName: us-central1-docker.pkg.dev/example-gcp-project/shifter-orthanc-portal/portal" in rendered
    assert "newName: us-central1-docker.pkg.dev/example-gcp-project/shifter-orthanc-guacd/guacd" in rendered
    # newTag lines are left for the digest-pin step.
    assert rendered.count("newTag: 0.0.0") == 2


def test_render_kustomization_images_fails_closed_on_unknown_component():
    module = _load_module()

    with pytest.raises(KeyError):
        module.render_kustomization_images(_PLACEHOLDER_KUSTOMIZATION, {"portal": _IMAGE_ROOTS["portal"]})


def test_render_service_account_patch_rewrites_email_preserving_localparts():
    module = _load_module()

    rendered = module.render_service_account_patch(_PLACEHOLDER_SA_PATCH, _WORKLOAD_SERVICE_ACCOUNTS)

    assert "@shifter-orthanc.iam.gserviceaccount.com" not in rendered
    assert "shifterorthanc-portal@example-gcp-project.iam.gserviceaccount.com" in rendered
    # The shortened prov-launcher localpart is preserved, not regenerated.
    assert "shifterorthanc-prov-launcher@example-gcp-project.iam.gserviceaccount.com" in rendered
    # Comments and structure survive the rewrite.
    assert "name: provisioner-launcher" in rendered
    assert "GCP 30-char SA id cap" in rendered


def test_render_service_account_patch_fails_closed_on_unknown_localpart():
    module = _load_module()

    with pytest.raises(KeyError):
        module.render_service_account_patch(
            _PLACEHOLDER_SA_PATCH,
            {"portal": _WORKLOAD_SERVICE_ACCOUNTS["portal"]},
        )


def test_render_overlay_writes_both_files(tmp_path, monkeypatch):
    module = _load_module()

    overlay = tmp_path / "platform/k8s/gcp/overlays/orthanc"
    overlay.mkdir(parents=True)
    (overlay / "kustomization.yaml").write_text(_PLACEHOLDER_KUSTOMIZATION, encoding="utf-8")
    (overlay / "patch-serviceaccounts.patch").write_text(_PLACEHOLDER_SA_PATCH, encoding="utf-8")
    monkeypatch.setattr(module, "_REPO_ROOT", tmp_path)

    outputs = {
        "artifact_registry_image_roots": {"value": _IMAGE_ROOTS},
        "workload_service_accounts": {"value": _WORKLOAD_SERVICE_ACCOUNTS},
    }
    module.render_overlay("orthanc", outputs)

    assert "example-gcp-project" in (overlay / "kustomization.yaml").read_text(encoding="utf-8")
    assert "example-gcp-project" in (overlay / "patch-serviceaccounts.patch").read_text(encoding="utf-8")


def test_render_overlay_rejects_path_traversal_environment(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "_REPO_ROOT", tmp_path)

    with pytest.raises(ValueError):
        module.render_overlay("../../etc", {})
