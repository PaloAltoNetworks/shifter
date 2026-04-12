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
    output_path = module._REPO_ROOT / "temp" / "test-artifacts" / tmp_path.name / "platform-edge.txt"

    with pytest.raises(ValueError, match="YAML file"):
        module._validated_output_path(output_path)


def test_validated_output_path_rejects_paths_outside_repo(tmp_path):
    module = _load_module()

    with pytest.raises(ValueError, match="inside the repository"):
        module._validated_output_path(Path("/tmp/platform-edge.generated.yaml"))


def test_output_path_for_environment_returns_repo_managed_manifest_location():
    module = _load_module()

    output_path = module._output_path_for_environment("gcp-dev")

    assert output_path == module._REPO_ROOT / "platform/k8s/gcp/overlays/gcp-dev/platform-edge.generated.yaml"


def test_main_writes_to_repo_managed_output_path(tmp_path, monkeypatch):
    module = _load_module()
    tf_output = tmp_path / "terraform-output.json"
    tf_output.write_text(json.dumps(_outputs()))
    output_path = tmp_path / "platform-edge.generated.yaml"

    monkeypatch.setattr(module, "_output_path_for_environment", lambda environment: output_path)
    monkeypatch.setattr(module, "_TERRAFORM_OUTPUT_PATH", tf_output)

    monkeypatch.setattr(
        "sys.argv",
        [
            "render_edge_manifest.py",
            "--environment",
            "gcp-dev",
        ],
    )

    assert module.main() == 0
    assert output_path.parent.exists()


def test_main_writes_manifest_to_stdout(tmp_path, monkeypatch, capsys):
    module = _load_module()
    tf_output = tmp_path / "terraform-output.json"
    tf_output.write_text(json.dumps(_outputs(public_hostname="portal.example.test", managed_tls_enabled=True)))

    monkeypatch.setattr(module, "_output_path_for_environment", lambda environment: tmp_path / "platform-edge.generated.yaml")
    monkeypatch.setattr(module, "_TERRAFORM_OUTPUT_PATH", tf_output)
    monkeypatch.setattr(
        "sys.argv",
        [
            "render_edge_manifest.py",
            "--environment",
            "gcp-dev",
        ],
    )

    assert module.main() == 0
    captured = capsys.readouterr()
    assert "kind: Ingress" in captured.out
    assert "platform-managed-cert" in captured.out
