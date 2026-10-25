"""RAES participant-host readiness must not depend on the GCE image source kind."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrators.setup_orchestrator import SetupError
from raes_preconfigured_host_readiness import verify_preconfigured_hosts


def _host(source_machine_image: str = "") -> dict[str, object]:
    return {
        "gcp_bootstrap_capability": "preconfigured-machine-host",
        "gcp_source_machine_image": source_machine_image,
        "gcp_participant_container_name": "participant-desktop",
        "gcp_participant_username": "student",
        "gcp_participant_readiness_contract": "participant-readiness/v1",
        "gcp_participant_readiness_manifest_sha256": "a" * 64,
        "os": "kali",
        "role": "attacker",
    }


@pytest.mark.parametrize("source_machine_image", ["", "projects/example/global/machineImages/host-v1"])
def test_both_host_sources_run_fixed_participant_canary(monkeypatch, source_machine_image):
    execution = SimpleNamespace(
        wait_for_ready=MagicMock(return_value=True),
        executor=MagicMock(),
        target="10.0.0.2",
        document_name="shell",
        close=MagicMock(),
    )
    orchestrator = MagicMock()
    orchestrator.orchestrate.return_value = SimpleNamespace(success=True)
    monkeypatch.setattr("raes_preconfigured_host_readiness.SetupOrchestrator", lambda **_kwargs: orchestrator)

    verify_preconfigured_hosts([_host(source_machine_image)], execution_builder=lambda *_args, **_kwargs: execution)

    plan = orchestrator.orchestrate.call_args.args[1]
    assert [step.name for step in plan.steps] == ["wait_for_preconfigured_machine_host", "verify_participant_readiness"]
    execution.close.assert_called_once()


def test_host_canary_failure_blocks_readiness_and_closes_transport(monkeypatch):
    execution = SimpleNamespace(
        wait_for_ready=MagicMock(return_value=True),
        executor=MagicMock(),
        target="10.0.0.2",
        document_name="shell",
        close=MagicMock(),
    )
    orchestrator = MagicMock()
    orchestrator.orchestrate.return_value = SimpleNamespace(success=False, error="canary failed")
    monkeypatch.setattr("raes_preconfigured_host_readiness.SetupOrchestrator", lambda **_kwargs: orchestrator)

    with pytest.raises(SetupError, match="participant readiness"):
        verify_preconfigured_hosts([_host()], execution_builder=lambda *_args, **_kwargs: execution)
    execution.close.assert_called_once()


def test_native_ec2_host_is_gated_through_neutral_contract_keys(monkeypatch):
    """#2527: EC2 outputs carry provider-neutral keys; standard hosts are skipped."""
    execution = SimpleNamespace(
        wait_for_ready=MagicMock(return_value=True),
        executor=MagicMock(),
        target="10.0.0.2",
        document_name="shell",
        close=MagicMock(),
    )
    orchestrator = MagicMock()
    orchestrator.orchestrate.return_value = SimpleNamespace(success=True)
    monkeypatch.setattr("raes_preconfigured_host_readiness.SetupOrchestrator", lambda **_kwargs: orchestrator)
    ec2_host = {
        "asset_type": "ec2_vm",
        "bootstrap_capability": "preconfigured-machine-host",
        "participant_container_name": "participant-desktop",
        "participant_username": "student",
        "participant_readiness_contract": "participant-readiness/v1",
        "participant_readiness_manifest_sha256": "b" * 64,
        "os": "linux",
    }

    verify_preconfigured_hosts(
        [ec2_host, {"asset_type": "ec2_vm", "os": "linux"}], execution_builder=lambda *_a, **_k: execution
    )

    assert orchestrator.orchestrate.call_count == 1
    context = orchestrator.orchestrate.call_args.args[2]
    assert context["participant_container_name"] == "participant-desktop"
    assert context["participant_readiness_manifest_sha256"] == "b" * 64
