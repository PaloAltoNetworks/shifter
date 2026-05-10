"""Tests for the ``shifter-config`` CLI (``installation.cli``)."""

from __future__ import annotations

import subprocess
import sys

import yaml

from installation.cli import main


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


class TestValidateCommand:
    def test_valid_file_exits_zero_and_reports_ok(self, tmp_path, capsys, minimal_config):
        cfg_path = tmp_path / "shifter.yaml"
        _write_yaml(cfg_path, minimal_config)
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

    def test_default_path_is_shifter_yaml_in_cwd(self, tmp_path, monkeypatch, capsys, minimal_config):
        _write_yaml(tmp_path / "shifter.yaml", minimal_config)
        monkeypatch.chdir(tmp_path)
        assert main(["validate"]) == 0
        assert "shifter.yaml" in capsys.readouterr().out

    def test_default_path_missing_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        assert main(["validate"]) == 1
        assert "shifter.yaml" in capsys.readouterr().err


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


class TestModuleEntrypoint:
    """``python -m installation`` is the documented entry point — exercise it end to end."""

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
