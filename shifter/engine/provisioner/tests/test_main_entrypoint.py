"""Tests for the provisioner CLI entrypoint."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

PROVISIONER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROVISIONER_ROOT))


class Recorder:
    def __init__(self, return_value: Any = None) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.return_value = return_value

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.return_value

    def assert_called_once_with(self, *args: Any, **kwargs: Any) -> None:
        assert self.calls == [(args, kwargs)]


def _install_module(monkeypatch, name: str, **attrs: Any) -> None:
    module = ModuleType(name)
    for attr, value in attrs.items():
        setattr(module, attr, value)
    monkeypatch.setitem(sys.modules, name, module)


def _install_entrypoint_fakes(monkeypatch) -> dict[str, Recorder]:
    calls = {
        "configure_logging": Recorder(),
        "run_ngfw_operation": Recorder(),
        "run_ngfw_terraform": Recorder(),
        "run_range_terraform": Recorder(),
        "run_range_pause": Recorder(),
        "run_range_resume": Recorder(),
        "run_polaris_splice": Recorder(SimpleNamespace(status="healthy")),
        "run_raes_range_provision": Recorder(),
        "run_raes_range_destroy": Recorder(),
        "run_raes_range_activate": Recorder(),
    }
    _install_module(monkeypatch, "logging_config", configure_logging=calls["configure_logging"])
    _install_module(monkeypatch, "ngfw_runtime_ops", run_ngfw_operation=calls["run_ngfw_operation"])
    _install_module(monkeypatch, "ngfw_terraform", run_ngfw_terraform=calls["run_ngfw_terraform"])
    _install_module(monkeypatch, "terraform_ops", run_range_terraform=calls["run_range_terraform"])
    _install_module(
        monkeypatch,
        "range_ops",
        run_range_pause=calls["run_range_pause"],
        run_range_resume=calls["run_range_resume"],
    )
    _install_module(
        monkeypatch,
        "raes_range_ops",
        run_raes_range_provision=calls["run_raes_range_provision"],
        run_raes_range_destroy=calls["run_raes_range_destroy"],
        run_raes_range_activate=calls["run_raes_range_activate"],
    )
    _install_module(
        monkeypatch,
        "polaris_splice_credentials",
        run_request_polaris_splice_credential_operation=calls["run_polaris_splice"],
    )
    return calls


def test_raes_activate_dispatches_activation(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "raes-range", "activate", "--request-id", "req-warm")

    assert calls["run_raes_range_activate"].calls == [(("req-warm",), {"operation_id": None})]
    assert calls["run_raes_range_provision"].calls == []
    assert calls["run_raes_range_destroy"].calls == []


def _run_main(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    runpy.run_path(str(PROVISIONER_ROOT / "main.py"), run_name="__main__")


def test_range_provision_dispatches_terraform_up(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "provision", "--request-id", "req-1")

    calls["configure_logging"].assert_called_once_with()
    calls["run_range_terraform"].assert_called_once_with("up", "req-1", operation_id=None)


def test_range_destroy_dispatches_terraform_destroy(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "destroy", "--request-id", "req-2")

    calls["run_range_terraform"].assert_called_once_with("destroy", "req-2", operation_id=None)


def test_range_provision_threads_operation_id_when_present(monkeypatch) -> None:
    """ADR-043 (#1834): --operation-id, when present, reaches run_range_terraform."""
    calls = _install_entrypoint_fakes(monkeypatch)
    operation_id = "11111111-1111-1111-1111-111111111111"

    _run_main(monkeypatch, "range", "provision", "--request-id", "req-1", "--operation-id", operation_id)

    calls["run_range_terraform"].assert_called_once_with("up", "req-1", operation_id=operation_id)


def test_range_pause_dispatches_range_ops(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "pause", "--request-id", "req-3")

    calls["run_range_pause"].assert_called_once_with("req-3", operation_id=None)


def test_range_resume_dispatches_range_ops(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "resume", "--request-id", "req-4")

    calls["run_range_resume"].assert_called_once_with("req-4", operation_id=None)


def test_range_splice_check_dispatches_read_only_health(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "splice-check", "--request-id", "req-5")

    calls["run_polaris_splice"].assert_called_once_with("req-5", repair=False)


def test_range_splice_repair_dispatches_explicit_mutation(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "splice-repair", "--request-id", "req-6")

    calls["run_polaris_splice"].assert_called_once_with("req-6", repair=True)


def test_range_pause_threads_operation_id_when_present(monkeypatch) -> None:
    """ADR-043 phase 4 (#1836): the generation must reach the pause path.

    Without it the provisioner appends no result and the applier -- now the
    authoritative writer for this family -- would never see the outcome.
    """
    calls = _install_entrypoint_fakes(monkeypatch)
    operation_id = "22222222-2222-2222-2222-222222222222"

    _run_main(monkeypatch, "range", "pause", "--request-id", "req-3", "--operation-id", operation_id)

    calls["run_range_pause"].assert_called_once_with("req-3", operation_id=operation_id)


def test_range_resume_threads_operation_id_when_present(monkeypatch) -> None:
    """ADR-043 phase 4 (#1836): the generation must reach the resume path."""
    calls = _install_entrypoint_fakes(monkeypatch)
    operation_id = "33333333-3333-3333-3333-333333333333"

    _run_main(monkeypatch, "range", "resume", "--request-id", "req-4", "--operation-id", operation_id)

    calls["run_range_resume"].assert_called_once_with("req-4", operation_id=operation_id)


def test_ngfw_provision_dispatches_terraform_up(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "ngfw", "provision", "--request-id", "ngfw-1")

    calls["run_ngfw_terraform"].assert_called_once_with("up", "ngfw-1", operation_id=None)


def test_ngfw_deprovision_dispatches_terraform_destroy(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "ngfw", "deprovision", "--request-id", "ngfw-2")

    calls["run_ngfw_terraform"].assert_called_once_with("destroy", "ngfw-2", operation_id=None)


def test_ngfw_start_dispatches_runtime_operation_with_ec2_instance(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(
        monkeypatch,
        "ngfw",
        "start",
        "--request-id",
        "ngfw-3",
        "--ec2-instance-id",
        "i-123",
    )

    calls["run_ngfw_operation"].assert_called_once_with("start", "ngfw-3", operation_id=None, ec2_instance_id="i-123")


def test_ngfw_stop_dispatches_runtime_operation_without_optional_kwargs(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "ngfw", "stop", "--request-id", "ngfw-4")

    calls["run_ngfw_operation"].assert_called_once_with("stop", "ngfw-4", operation_id=None)


def test_ngfw_provision_threads_operation_id_when_present(monkeypatch) -> None:
    """ADR-043 (#1834): --operation-id, when present, reaches run_ngfw_terraform."""
    calls = _install_entrypoint_fakes(monkeypatch)
    operation_id = "22222222-2222-2222-2222-222222222222"

    _run_main(monkeypatch, "ngfw", "provision", "--request-id", "ngfw-1", "--operation-id", operation_id)

    calls["run_ngfw_terraform"].assert_called_once_with("up", "ngfw-1", operation_id=operation_id)


def test_ngfw_start_threads_operation_id_when_present(monkeypatch) -> None:
    """ADR-043 (#1834): --operation-id, when present, reaches run_ngfw_operation."""
    calls = _install_entrypoint_fakes(monkeypatch)
    operation_id = "33333333-3333-3333-3333-333333333333"

    _run_main(monkeypatch, "ngfw", "start", "--request-id", "ngfw-3", "--operation-id", operation_id)

    calls["run_ngfw_operation"].assert_called_once_with("start", "ngfw-3", operation_id=operation_id)


# ADR-043 phase 5 (#1837): the RAES family is cut over, so its entrypoint must
# carry the canonical generation. Before this, raes-range was the only resource
# whose dispatch dropped --operation-id on the floor, leaving the realization
# path with no fence and no input row to read.
def test_raes_provision_threads_operation_id(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)
    operation_id = "44444444-4444-4444-4444-444444444444"

    _run_main(monkeypatch, "raes-range", "provision", "--request-id", "raes-1", "--operation-id", operation_id)

    calls["run_raes_range_provision"].assert_called_once_with("raes-1", operation_id=operation_id)


def test_raes_destroy_threads_operation_id(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)
    operation_id = "55555555-5555-5555-5555-555555555555"

    _run_main(monkeypatch, "raes-range", "destroy", "--request-id", "raes-2", "--operation-id", operation_id)

    calls["run_raes_range_destroy"].assert_called_once_with("raes-2", operation_id=operation_id)


def test_raes_dispatch_without_a_generation_passes_none_through(monkeypatch) -> None:
    # main.py does not decide the policy; raes_range_ops refuses. Threading None
    # explicitly is what lets it refuse instead of silently realizing unfenced.
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "raes-range", "provision", "--request-id", "raes-3")

    calls["run_raes_range_provision"].assert_called_once_with("raes-3", operation_id=None)
