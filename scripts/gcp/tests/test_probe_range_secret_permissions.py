"""Tests for the inert-by-default GCP range-secret permission probe."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "probe_range_secret_permissions.py"
    spec = importlib.util.spec_from_file_location("probe_range_secret_permissions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _config(module):
    return module.ProbeConfig(
        platform_project="platform-project",
        dynamic_project="dynamic-project",
        unrelated_project="external-project",
        environment="gcp-dev",
        provisioner_service_account="provisioner@platform-project.iam.gserviceaccount.com",
        portal_service_account="portal@platform-project.iam.gserviceaccount.com",
        range_host_service_account="range-host@platform-project.iam.gserviceaccount.com",
        peer_range_host_service_account="peer-host@platform-project.iam.gserviceaccount.com",
        gateway_service_account="gateway@platform-project.iam.gserviceaccount.com",
        peer_gateway_service_account="peer-gateway@platform-project.iam.gserviceaccount.com",
        workers_service_account="workers@platform-project.iam.gserviceaccount.com",
        launcher_service_account="launcher@platform-project.iam.gserviceaccount.com",
        node_service_account="node@platform-project.iam.gserviceaccount.com",
    )


def test_probe_matrix_covers_positive_and_negative_real_identity_edges(tmp_path):
    module = _load_module()
    steps = module.build_probe_steps(_config(module), tmp_path / "payload", "abc123")
    expectations = {step.name: step.expect_success for step in steps}

    assert expectations["provisioner-create-participant"] is True
    assert expectations["portal-read-participant"] is True
    assert expectations["provisioner-create-platform-denied"] is False
    assert expectations["provisioner-create-external-denied"] is False
    assert expectations["provisioner-read-unrelated-denied"] is False
    assert expectations["provisioner-read-platform-denied"] is False
    assert expectations["provisioner-read-external-denied"] is False
    assert expectations["provisioner-update-unrelated-denied"] is False
    assert expectations["provisioner-delete-unrelated-denied"] is False
    assert expectations["portal-read-workload-denied"] is False
    assert expectations["range-host-read-before-grant-denied"] is False
    assert expectations["range-host-read-after-grant"] is True
    assert expectations["peer-range-host-read-denied"] is False
    assert expectations["range-host-project-wide-read-denied"] is False
    assert expectations["gateway-read-after-grant"] is True
    assert expectations["peer-gateway-read-denied"] is False
    assert expectations["gateway-project-wide-read-denied"] is False
    assert expectations["workers-read-participant-denied"] is False
    assert expectations["launcher-read-participant-denied"] is False
    assert expectations["node-read-participant-denied"] is False
    assert expectations["provisioner-delete-host-secret"] is True

    commands = "\n".join(" ".join(step.command) for step in steps)
    assert "--impersonate-service-account=provisioner@platform-project.iam.gserviceaccount.com" in commands
    assert "--impersonate-service-account=portal@platform-project.iam.gserviceaccount.com" in commands
    assert "--impersonate-service-account=range-host@platform-project.iam.gserviceaccount.com" in commands
    assert "--impersonate-service-account=gateway@platform-project.iam.gserviceaccount.com" in commands
    assert "--impersonate-service-account=node@platform-project.iam.gserviceaccount.com" in commands


def test_cleanup_covers_unexpected_platform_create():
    module = _load_module()
    commands = []

    module._cleanup(
        _config(module),
        "abc123",
        lambda command: commands.append(tuple(command)) or subprocess.CompletedProcess(command, 0, "", ""),
    )

    assert (
        "gcloud",
        "secrets",
        "delete",
        "shifter-gcp-dev-dynamic-workload-probe-host-range-abc123-credential",
        "--project=platform-project",
        "--quiet",
    ) in commands
    assert (
        "gcloud",
        "secrets",
        "delete",
        "shifter-gcp-dev-dynamic-workload-probe-external-range-abc123-credential",
        "--project=external-project",
        "--quiet",
    ) in commands
    assert (
        "gcloud",
        "secrets",
        "delete",
        "shifter-permission-probe-external-abc123",
        "--project=external-project",
        "--quiet",
    ) in commands


def test_cleanup_accepts_not_found_but_aggregates_other_failures_without_payloads():
    module = _load_module()
    calls = 0

    def runner(command):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(command, 1, "", "NOT_FOUND: secret absent")
        if calls == 2:
            return subprocess.CompletedProcess(
                command,
                1,
                "sensitive-stdout",
                "PERMISSION_DENIED: secret sensitive-name",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(module.ProbeCleanupError) as exc_info:
        module._cleanup(_config(module), "abc123", runner)

    detail = str(exc_info.value)
    assert "project_fp=" in detail
    assert "resource_fp=" in detail
    assert "exit=1" in detail
    assert "sensitive-stdout" not in detail
    assert "sensitive-name" not in detail


def test_probe_preserves_boundary_and_cleanup_failures(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module.uuid, "uuid4", lambda: type("Fixed", (), {"hex": "abc123def4567890"})())

    def runner(command):
        if len(command) > 2 and command[2] == "delete":
            return subprocess.CompletedProcess(command, 1, "", "PERMISSION_DENIED: cleanup denied")
        return subprocess.CompletedProcess(command, 1, "", "PERMISSION_DENIED: operation denied")

    with pytest.raises(ExceptionGroup) as exc_info:
        module.run_probe(_config(module), runner=runner)

    assert any("operator-seed-unrelated-secret" in str(error) for error in exc_info.value.exceptions)
    assert any(isinstance(error, module.ProbeCleanupError) for error in exc_info.value.exceptions)


def test_probe_refuses_same_project_compatibility_posture():
    module = _load_module()
    config = module.ProbeConfig(
        platform_project="same-project",
        dynamic_project="same-project",
        unrelated_project="external-project",
        environment="gcp-dev",
        provisioner_service_account="provisioner@example.test",
        portal_service_account="portal@example.test",
        range_host_service_account="host@example.test",
        peer_range_host_service_account="peer-host@example.test",
        gateway_service_account="gateway@example.test",
        peer_gateway_service_account="peer-gateway@example.test",
        workers_service_account="workers@example.test",
        launcher_service_account="launcher@example.test",
        node_service_account="node@example.test",
    )

    with pytest.raises(ValueError, match="dedicated dynamic project"):
        module.run_probe(config, runner=lambda command: None)


def test_cli_is_plan_only_without_execute(capsys):
    module = _load_module()

    result = module.main(
        [
            "--platform-project",
            "platform-project",
            "--dynamic-project",
            "dynamic-project",
            "--unrelated-project",
            "external-project",
            "--environment",
            "gcp-dev",
            "--provisioner-service-account",
            "provisioner@example.test",
            "--portal-service-account",
            "portal@example.test",
            "--range-host-service-account",
            "host@example.test",
            "--peer-range-host-service-account",
            "peer-host@example.test",
            "--gateway-service-account",
            "gateway@example.test",
            "--peer-gateway-service-account",
            "peer-gateway@example.test",
            "--workers-service-account",
            "workers@example.test",
            "--launcher-service-account",
            "launcher@example.test",
            "--node-service-account",
            "node@example.test",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "ALLOW provisioner-create-participant" in output
    assert "DENY provisioner-create-platform-denied" in output


def test_negative_probe_requires_real_boundary_denial_not_missing_state_or_impersonation_failure():
    module = _load_module()

    assert module._is_boundary_denial(
        subprocess.CompletedProcess([], 1, "", "PERMISSION_DENIED: secretmanager.versions.access denied")
    )
    assert not module._is_boundary_denial(subprocess.CompletedProcess([], 1, "", "NOT_FOUND: secret absent"))
    assert not module._is_boundary_denial(subprocess.CompletedProcess([], 1, "", "ALREADY_EXISTS: secret exists"))
    assert not module._is_boundary_denial(
        subprocess.CompletedProcess([], 1, "", "PERMISSION_DENIED: iam.serviceAccounts.getAccessToken denied")
    )


def test_permission_evidence_records_safe_context_without_resource_name(tmp_path):
    module = _load_module()
    step = next(
        step
        for step in module.build_probe_steps(_config(module), tmp_path / "payload", "abc123")
        if step.name == "portal-read-participant"
    )

    evidence = module._step_evidence(step, "abc123", 0.125, True)

    assert "PASS correlation=abc123" in evidence
    assert "principal=portal@platform-project.iam.gserviceaccount.com" in evidence
    assert "permission=secretmanager.versions.access" in evidence
    assert "resource_class=participant" in evidence
    assert "resource_fp=" in evidence
    assert "elapsed_ms=125" in evidence
    assert "shifter-gcp-dev-dynamic" not in evidence
