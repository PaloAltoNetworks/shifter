"""Tests for the provisioner CLI entrypoint."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

PROVISIONER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROVISIONER_ROOT))


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))

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
    return calls


def _run_main(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    runpy.run_path(str(PROVISIONER_ROOT / "main.py"), run_name="__main__")


def test_range_provision_dispatches_terraform_up(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "provision", "--request-id", "req-1")

    calls["configure_logging"].assert_called_once_with()
    calls["run_range_terraform"].assert_called_once_with("up", "req-1")


def test_range_destroy_dispatches_terraform_destroy(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "destroy", "--request-id", "req-2")

    calls["run_range_terraform"].assert_called_once_with("destroy", "req-2")


def test_range_pause_dispatches_range_ops(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "pause", "--request-id", "req-3")

    calls["run_range_pause"].assert_called_once_with("req-3")


def test_range_resume_dispatches_range_ops(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "range", "resume", "--request-id", "req-4")

    calls["run_range_resume"].assert_called_once_with("req-4")


def test_ngfw_provision_dispatches_terraform_up(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "ngfw", "provision", "--request-id", "ngfw-1")

    calls["run_ngfw_terraform"].assert_called_once_with("up", "ngfw-1")


def test_ngfw_deprovision_dispatches_terraform_destroy(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "ngfw", "deprovision", "--request-id", "ngfw-2")

    calls["run_ngfw_terraform"].assert_called_once_with("destroy", "ngfw-2")


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

    calls["run_ngfw_operation"].assert_called_once_with("start", "ngfw-3", ec2_instance_id="i-123")


def test_ngfw_stop_dispatches_runtime_operation_without_optional_kwargs(monkeypatch) -> None:
    calls = _install_entrypoint_fakes(monkeypatch)

    _run_main(monkeypatch, "ngfw", "stop", "--request-id", "ngfw-4")

    calls["run_ngfw_operation"].assert_called_once_with("stop", "ngfw-4")
