from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "prepare_model_broker_overlay.py"
SPEC = importlib.util.spec_from_file_location("prepare_model_broker_overlay", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
# A reviewed broker overlay, kept as a fixture so the test owns its input.
TEMPLATE = Path(__file__).resolve().parent / "fixtures" / "model-broker-overlay.template.json"


def test_reviewed_overlay_binds_only_the_deployment_project_and_seals_catalog():
    rendered = MODULE.render_overlay(TEMPLATE, project_id="example-platform", ca_pem="public-ca")
    policy = json.loads(rendered)["settings"]
    assert "__GCP_PROJECT_ID__" not in rendered
    assert policy["model_broker"]["model_projects"] == {"example-platform": "nazgul-model-invoke"}
    assert policy["model_broker_runtime"]["guest_trust_ca_pem"] == "public-ca"
    assert policy["model_access"]["catalog"]["digest"].startswith("sha256:")
    assert policy["model_access"]["catalog"]["quota_pools"][0]["provider_quota_identity"].startswith(
        "project:example-platform/"
    )


def test_reviewed_overlay_rejects_unbound_project_or_ambiguous_template(tmp_path):
    with pytest.raises(ValueError, match="project id"):
        MODULE.render_overlay(TEMPLATE, project_id="INVALID", ca_pem="public-ca")
    value = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    value["settings"]["model_access"]["catalog"]["digest"] = "unreviewed"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="digest placeholder"):
        MODULE.render_overlay(path, project_id="example-platform", ca_pem="public-ca")


def test_generated_leaf_certificates_bind_the_guest_vip_and_control_name(tmp_path):
    MODULE._generate_ca(tmp_path)
    guest_cert, guest_key = MODULE._generate_leaf(
        tmp_path,
        name="broker",
        common_name="models.example.internal",
        san="DNS:models.example.internal,IP:10.40.15.250",
    )
    MODULE._verify_leaf(
        tmp_path,
        name="broker",
        cert=guest_cert,
        key=guest_key,
        dns_name="models.example.internal",
        vip="10.40.15.250",
    )
    with pytest.raises(RuntimeError, match="deployment command failed"):
        MODULE._verify_leaf(
            tmp_path,
            name="wrong-ip",
            cert=guest_cert,
            key=guest_key,
            dns_name="models.example.internal",
            vip="10.40.15.251",
        )


def test_signer_readback_must_match_public_trust(monkeypatch):
    cert = b"public-ca"
    monkeypatch.setattr(MODULE, "_secret_bytes", lambda _context, _name, _key: cert)
    monkeypatch.setattr(
        MODULE,
        "_get_object",
        lambda _context, kind, _name: {"data": {"ca.crt": "different"}} if kind == "configmap" else {"data": {}},
    )
    with pytest.raises(ValueError, match="differs"):
        MODULE.read_trust("example-context")
