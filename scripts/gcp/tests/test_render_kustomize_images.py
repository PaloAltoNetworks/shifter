"""Tests for the GCP kustomization image renderer."""

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


def test_render_kustomization_rewrites_images_block():
    module = _load_module("render_kustomize_images.py", "render_kustomize_images")

    source = """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

images:
  - name: us-docker.pkg.dev/placeholder-project/shifter/portal
    newName: us-docker.pkg.dev/placeholder-project/shifter/portal
    newTag: 0.0.0
  - name: us-docker.pkg.dev/placeholder-project/shifter/guacd
    newName: us-docker.pkg.dev/placeholder-project/shifter/guacd
    newTag: 0.0.0
  - name: us-docker.pkg.dev/placeholder-project/shifter/guacamole-client
    newName: us-docker.pkg.dev/placeholder-project/shifter/guacamole-client
    newTag: 0.0.0

patches:
  - path: patch-serviceaccounts.yaml
"""

    rendered = module.render_kustomization(
        source,
        portal_image="us-central1-docker.pkg.dev/prod/shifter-portal/portal",
        guacd_image="us-central1-docker.pkg.dev/prod/shifter-guacd/guacd",
        guacamole_client_image="us-central1-docker.pkg.dev/prod/shifter-guacamole-client/guacamole-client",
        tag="abc1234",
    )

    assert "newName: us-central1-docker.pkg.dev/prod/shifter-portal/portal" in rendered
    assert "newName: us-central1-docker.pkg.dev/prod/shifter-guacd/guacd" in rendered
    assert (
        "newName: us-central1-docker.pkg.dev/prod/shifter-guacamole-client/guacamole-client"
        in rendered
    )
    assert rendered.count('newTag: "abc1234"') == 3
    assert "patches:\n  - path: patch-serviceaccounts.yaml\n" in rendered


def test_render_kustomization_requires_images_block():
    module = _load_module("render_kustomize_images.py", "render_kustomize_images")

    try:
        module.render_kustomization(
            "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\npatches:\n",
            portal_image="portal",
            guacd_image="guacd",
            guacamole_client_image="guac-client",
            tag="latest",
        )
    except ValueError as exc:
        assert "images block" in str(exc)
    else:
        raise AssertionError("render_kustomization should fail without an images block")
