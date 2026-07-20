"""Tests for the ``shifter-config`` CLI (``installation.cli``)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from installation import cli
from installation.cli import main
from installation.doctor import CheckScope, CheckStatus, CheckTier, DoctorCheckResult, DoctorReport


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


class TestValidateCommand:
    def test_valid_file_exits_zero_and_reports_ok(self, tmp_path, capsys, aws_config):
        cfg_path = tmp_path / "shifter.yaml"
        _write_yaml(cfg_path, aws_config)
        rc = main(["validate", str(cfg_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK" in out
        assert "aws" in out

    def test_invalid_file_exits_nonzero_and_reports_issues_on_stderr(self, tmp_path, capsys):
        cfg_path = tmp_path / "shifter.yaml"
        _write_yaml(cfg_path, {"backend": "azure", "deployment": {"name": "Bad Name", "domain": "localhost"}})
        rc = main(["validate", str(cfg_path)])
        assert rc == 1
        captured = capsys.readouterr()
        assert "backend" in captured.err
        assert "deployment.name" in captured.err

    def test_missing_file_exits_nonzero(self, tmp_path, capsys):
        rc = main(["validate", str(tmp_path / "does-not-exist.yaml")])
        assert rc == 1
        assert "does-not-exist.yaml" in capsys.readouterr().err

    def test_default_path_is_shifter_yaml_in_cwd(self, tmp_path, monkeypatch, capsys, aws_config):
        _write_yaml(tmp_path / "shifter.yaml", aws_config)
        monkeypatch.chdir(tmp_path)
        assert main(["validate"]) == 0
        assert "shifter.yaml" in capsys.readouterr().out

    def test_default_path_missing_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        assert main(["validate"]) == 1
        assert "shifter.yaml" in capsys.readouterr().err


class TestInitCommand:
    def test_scaffolds_the_selected_backend(self, tmp_path, capsys):
        dest = tmp_path / "shifter.yaml"
        rc = main(["init", "--backend", "aws", "-o", str(dest)])
        assert rc == 0
        assert "backend: aws" in dest.read_text(encoding="utf-8")
        assert "doctor" in capsys.readouterr().out

    def test_no_backend_lists_available_backends(self, capsys):
        rc = main(["init"])
        assert rc == 2
        out = capsys.readouterr().out
        assert "aws" in out
        assert "gcp" in out

    def test_unknown_backend_exits_nonzero(self, tmp_path, capsys):
        rc = main(["init", "--backend", "azure", "-o", str(tmp_path / "shifter.yaml")])
        assert rc == 1
        assert "azure" in capsys.readouterr().err

    def test_refuses_overwrite_without_force(self, tmp_path, capsys):
        dest = tmp_path / "shifter.yaml"
        dest.write_text("keep: me\n", encoding="utf-8")
        assert main(["init", "--backend", "aws", "-o", str(dest)]) == 1
        assert dest.read_text(encoding="utf-8") == "keep: me\n"
        assert main(["init", "--backend", "aws", "-o", str(dest), "--force"]) == 0
        assert "backend: aws" in dest.read_text(encoding="utf-8")


class TestDoctorCommand:
    def test_invalid_config_exits_nonzero(self, tmp_path, capsys):
        _write_yaml(tmp_path / "shifter.yaml", {"backend": "azure", "deployment": {"name": "x", "domain": "localhost"}})
        rc = main(["doctor", str(tmp_path / "shifter.yaml"), "--repo-root", str(tmp_path)])
        assert rc == 1
        combined = capsys.readouterr()
        assert "FAIL" in combined.out
        assert "not ready" in combined.err

    def test_healthy_report_exits_zero_and_prints_tiers(self, tmp_path, monkeypatch, capsys):
        report = DoctorReport(
            backend="aws",
            profile="prod",
            results=[
                DoctorCheckResult("root-config", CheckTier.LOCAL, CheckStatus.PASS, "valid"),
                DoctorCheckResult("deployment-mutating", CheckTier.MUTATING, CheckStatus.INFO, "not run by doctor"),
            ],
        )
        monkeypatch.setattr(cli, "run_doctor", lambda *a, **k: report)
        rc = main(["doctor", str(tmp_path / "shifter.yaml")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "local-only" in out
        assert "deployment-mutating" in out
        assert "OK" in out

    def test_json_output_is_machine_readable(self, tmp_path, monkeypatch, capsys):
        import json

        report = DoctorReport(
            backend="gcp",
            profile="prod",
            results=[DoctorCheckResult("root-config", CheckTier.LOCAL, CheckStatus.PASS, "valid")],
        )
        monkeypatch.setattr(cli, "run_doctor", lambda *a, **k: report)
        rc = main(["doctor", str(tmp_path / "shifter.yaml"), "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["backend"] == "gcp"
        assert payload["ok"] is True

    def test_forwards_path_checks_and_repo_root_flags(self, tmp_path, monkeypatch):
        # A recording fake (not an argument-blind lambda) proves _cmd_doctor forwards the
        # config path, --checks scope, and --repo-root to run_doctor. Without this, a refactor
        # that hardcoded scope/repo_root would silently drop the operator's flags.
        calls: dict[str, object] = {}

        def fake_run_doctor(path, *, scope, repo_root, **kwargs):
            calls["path"] = path
            calls["scope"] = scope
            calls["repo_root"] = repo_root
            return DoctorReport(
                backend="aws",
                profile="prod",
                results=[DoctorCheckResult("root-config", CheckTier.LOCAL, CheckStatus.PASS, "valid")],
            )

        monkeypatch.setattr(cli, "run_doctor", fake_run_doctor)
        cfg = tmp_path / "shifter.yaml"
        other_root = tmp_path / "other-root"
        rc = main(["doctor", str(cfg), "--checks", "cloud", "--repo-root", str(other_root)])
        assert rc == 0
        assert calls["path"] == Path(str(cfg))
        assert calls["scope"] is CheckScope.CLOUD
        assert calls["repo_root"] == Path(str(other_root))


class TestArgParsing:
    def test_no_command_exits_nonzero(self, capsys):
        rc = main([])
        assert rc != 0

    def test_unknown_command_exits_nonzero(self, capsys):
        # argparse exits with SystemExit(2) for an unknown subcommand.
        try:
            rc = main(["frobnicate"])
        except SystemExit as exc:
            rc = exc.code
        assert rc != 0


@pytest.mark.integration
class TestModuleEntrypoint:
    """``python -m installation`` is the documented entry point — exercise it end to end.

    Marked ``integration`` because it spawns a subprocess (the test interpreter) rather
    than calling ``cli.main`` in process.
    """

    def test_python_m_installation_validates_an_example(self, examples_dir):
        example = examples_dir / "aws.yaml"
        result = subprocess.run(
            [sys.executable, "-m", "installation", "validate", str(example)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout

    def test_python_m_installation_fails_on_missing_file(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "installation", "validate", str(tmp_path / "nope.yaml")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "nope.yaml" in result.stderr
