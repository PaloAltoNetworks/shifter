"""Tests for the GCP edge manifest renderer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "render_edge_manifest.py"
    spec = importlib.util.spec_from_file_location("render_edge_manifest", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _outputs(
    *,
    public_hostname: str = "",
    managed_tls_enabled: bool = False,
) -> dict[str, object]:
    return {
        "public_hostname": {"value": public_hostname},
        "managed_tls_enabled": {"value": managed_tls_enabled},
        "public_ingress_ip_name": {"value": "shifter-gcp-dev-platform-ip"},
    }


def test_render_manifest_uses_plain_ingress_when_hostname_is_not_configured():
    module = _load_module()

    rendered = module.render_manifest(_outputs())

    assert "kind: ManagedCertificate" not in rendered
    assert "kubernetes.io/ingress.global-static-ip-name: shifter-gcp-dev-platform-ip" in rendered
    assert "host:" not in rendered


def test_render_manifest_adds_managed_certificate_when_tls_is_enabled():
    module = _load_module()

    rendered = module.render_manifest(_outputs(public_hostname="portal.example.test", managed_tls_enabled=True))

    assert "kind: FrontendConfig" in rendered
    assert "redirectToHttps:" in rendered
    assert "kind: ManagedCertificate" in rendered
    assert "networking.gke.io/managed-certificates: platform-managed-cert" in rendered
    assert "networking.gke.io/v1beta1.FrontendConfig: platform-frontend-config" in rendered
    assert "host: portal.example.test" in rendered


def test_validated_output_path_rejects_non_yaml_files(tmp_path):
    module = _load_module()
    output_path = Path.cwd() / "temp" / "test-artifacts" / tmp_path.name / "platform-edge.txt"

    with pytest.raises(ValueError, match="YAML file"):
        module._validated_output_path(output_path)


def test_validated_output_path_rejects_paths_outside_repo(tmp_path):
    module = _load_module()

    with pytest.raises(ValueError, match="inside the repository"):
        module._validated_output_path(Path("/tmp/platform-edge.generated.yaml"))


def test_main_rejects_non_yaml_output_path(tmp_path, monkeypatch):
    module = _load_module()
    tf_output = tmp_path / "terraform-output.json"
    tf_output.write_text(json.dumps(_outputs()))
    output_path = Path.cwd() / "temp" / "test-artifacts" / tmp_path.name / "platform-edge.txt"

    monkeypatch.setattr(
        "sys.argv",
        [
            "render_edge_manifest.py",
            "--terraform-output-json",
            str(tf_output),
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(ValueError, match="YAML file"):
        module.main()
