"""Tests for ``installation.render`` and the ``shifter-config render`` CLI (#958).

The renderer is the single authoritative source that turns the validated, normalized
``settings.range_egress`` policy in ``shifter.yaml`` into the provider-specific Terraform
*bridge* variables, so operators no longer hand-maintain a second CIDR allowlist copy and
the configured policy cannot drift from the deployed firewall rules:

- AWS bridges into one variable, ``victim_allowed_cidrs`` (the AWS Network Firewall rule
  groups consume it). AWS also bridges ``range_egress_mode`` (``allowlist`` or ``none``).
  ``status-quo`` / ``deny-all`` / ``allowlist`` map to runtime ``allowlist``; ``none``
  maps to runtime ``none``. ``allowlist`` renders the canonical CIDRs; other modes render
  an empty list.
- GCP bridges into ``range_egress_mode`` + ``range_egress_allowed_cidrs`` (the GCP VPC
  firewall egress rules are conditional on the mode).

Values are constrained to canonical CIDR strings and a fixed mode enum by
``RangeEgressPolicy`` before they reach the renderer, so the emitted HCL is trusted input.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from installation.loader import load_root_config
from installation.render import render_tfvars


def _aws(settings: dict | None, aws_config: dict) -> dict:
    cfg = dict(aws_config)
    if settings is not None:
        cfg["settings"] = settings
    return cfg


def _gcp(settings: dict | None, gcp_config: dict) -> dict:
    cfg = dict(gcp_config)
    if settings is not None:
        cfg["settings"] = settings
    return cfg


class TestRenderAws:
    def test_allowlist_renders_victim_allowed_cidrs(self, write_config, aws_config):
        path = write_config(
            _aws({"range_egress": {"mode": "allowlist", "allowed_cidrs": ["203.0.113.0/24", "8.8.8.8/32"]}}, aws_config)
        )
        out = render_tfvars(load_root_config(path))
        assert "victim_allowed_cidrs = [" in out
        assert '"203.0.113.0/24"' in out
        assert '"8.8.8.8/32"' in out
        assert 'range_egress_mode = "allowlist"' in out

    def test_status_quo_renders_allowlist_mode_and_empty_list(self, write_config, aws_config):
        path = write_config(_aws({"range_egress": {"mode": "status-quo"}}, aws_config))
        out = render_tfvars(load_root_config(path))
        assert "victim_allowed_cidrs = []" in out
        assert 'range_egress_mode = "allowlist"' in out

    def test_deny_all_renders_allowlist_mode_and_empty_list(self, write_config, aws_config):
        path = write_config(_aws({"range_egress": {"mode": "deny-all"}}, aws_config))
        out = render_tfvars(load_root_config(path))
        assert "victim_allowed_cidrs = []" in out
        assert 'range_egress_mode = "allowlist"' in out

    def test_none_renders_none_mode_and_empty_list(self, write_config, aws_config):
        path = write_config(_aws({"range_egress": {"mode": "none"}}, aws_config))
        out = render_tfvars(load_root_config(path))
        assert "victim_allowed_cidrs = []" in out
        assert 'range_egress_mode = "none"' in out

    def test_omitted_block_defaults_to_allowlist_mode_and_empty_list(self, write_config, aws_config):
        path = write_config(_aws({"region": "us-east-2"}, aws_config))
        out = render_tfvars(load_root_config(path))
        assert "victim_allowed_cidrs = []" in out
        assert 'range_egress_mode = "allowlist"' in out

    def test_ipv6_allowlist_preserved(self, write_config, aws_config):
        path = write_config(
            _aws({"range_egress": {"mode": "allowlist", "allowed_cidrs": ["2001:db8::/32"]}}, aws_config)
        )
        out = render_tfvars(load_root_config(path))
        assert '"2001:db8::/32"' in out

    def test_ordering_preserved(self, write_config, aws_config):
        cidrs = ["198.51.100.0/24", "203.0.113.0/24", "8.8.8.8/32"]
        path = write_config(_aws({"range_egress": {"mode": "allowlist", "allowed_cidrs": cidrs}}, aws_config))
        out = render_tfvars(load_root_config(path))
        positions = [out.index(f'"{c}"') for c in cidrs]
        assert positions == sorted(positions)


class TestRenderGcp:
    def test_allowlist_renders_mode_and_cidrs(self, write_config, gcp_config):
        path = write_config(
            _gcp({"range_egress": {"mode": "allowlist", "allowed_cidrs": ["203.0.113.0/24"]}}, gcp_config)
        )
        out = render_tfvars(load_root_config(path))
        assert 'range_egress_mode = "allowlist"' in out
        assert "range_egress_allowed_cidrs = [" in out
        assert '"203.0.113.0/24"' in out
        # GCP does not use the AWS-internal variable name.
        assert "victim_allowed_cidrs" not in out

    def test_status_quo_renders_mode_and_empty_list(self, write_config, gcp_config):
        path = write_config(_gcp({"range_egress": {"mode": "status-quo"}}, gcp_config))
        out = render_tfvars(load_root_config(path))
        assert 'range_egress_mode = "status-quo"' in out
        assert "range_egress_allowed_cidrs = []" in out

    def test_deny_all_renders_mode_and_empty_list(self, write_config, gcp_config):
        path = write_config(_gcp({"range_egress": {"mode": "deny-all"}}, gcp_config))
        out = render_tfvars(load_root_config(path))
        assert 'range_egress_mode = "deny-all"' in out
        assert "range_egress_allowed_cidrs = []" in out

    def test_omitted_block_defaults_to_status_quo(self, write_config, gcp_config):
        path = write_config(_gcp({"region": "us-central1"}, gcp_config))
        out = render_tfvars(load_root_config(path))
        assert 'range_egress_mode = "status-quo"' in out
        assert "range_egress_allowed_cidrs = []" in out

    def test_none_rejected_for_gcp(self, write_config, gcp_config):
        from installation.errors import InstallationConfigError

        path = write_config(_gcp({"range_egress": {"mode": "none"}}, gcp_config))
        with pytest.raises(InstallationConfigError, match="AWS only"):
            render_tfvars(load_root_config(path))


class TestRenderShape:
    def test_output_is_deterministic(self, write_config, aws_config):
        path = write_config(
            _aws({"range_egress": {"mode": "allowlist", "allowed_cidrs": ["203.0.113.0/24"]}}, aws_config)
        )
        config = load_root_config(path)
        assert render_tfvars(config) == render_tfvars(config)

    def test_output_carries_generated_header(self, write_config, aws_config):
        path = write_config(_aws({"range_egress": {"mode": "status-quo"}}, aws_config))
        out = render_tfvars(load_root_config(path))
        # A generated file must announce itself so an operator does not hand-edit it.
        assert out.lstrip().startswith("#")
        assert "shifter-config render" in out

    def test_output_ends_with_newline(self, write_config, gcp_config):
        path = write_config(_gcp({"range_egress": {"mode": "status-quo"}}, gcp_config))
        out = render_tfvars(load_root_config(path))
        assert out.endswith("\n")


class TestRenderCli:
    def test_render_to_stdout(self, write_config, aws_config, capsys):
        from installation.cli import main

        path = write_config(
            _aws({"range_egress": {"mode": "allowlist", "allowed_cidrs": ["203.0.113.0/24"]}}, aws_config)
        )
        rc = main(["render", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "victim_allowed_cidrs = [" in out
        assert '"203.0.113.0/24"' in out

    def test_render_to_output_file(self, write_config, aws_config, tmp_path, capsys):
        from installation.cli import main

        path = write_config(_aws({"range_egress": {"mode": "status-quo"}}, aws_config))
        out_file = tmp_path / "victim_allowed_cidrs.auto.tfvars"
        rc = main(["render", str(path), "--output", str(out_file)])
        assert rc == 0
        assert out_file.read_text(encoding="utf-8").count("victim_allowed_cidrs = []") == 1
        # With --output, stdout stays clean so the file is the only product.
        assert capsys.readouterr().out == ""

    def test_render_invalid_config_exits_nonzero(self, write_config, capsys):
        from installation.cli import main

        path = write_config({"backend": "azure", "deployment": {"name": "Bad Name", "domain": "localhost"}})
        rc = main(["render", str(path)])
        assert rc == 1
        assert "backend" in capsys.readouterr().err

    def test_render_rejects_invalid_cidr(self, write_config, aws_config, capsys):
        from installation.cli import main

        path = write_config(_aws({"range_egress": {"mode": "allowlist", "allowed_cidrs": ["not-a-cidr"]}}, aws_config))
        rc = main(["render", str(path)])
        assert rc == 1
        assert "range_egress" in capsys.readouterr().err

    def test_render_missing_file_exits_nonzero(self, tmp_path, capsys):
        from installation.cli import main

        rc = main(["render", str(tmp_path / "does-not-exist.yaml")])
        assert rc == 1
        assert "does-not-exist.yaml" in capsys.readouterr().err

    def test_render_bad_output_target_exits_nonzero(self, write_config, aws_config, tmp_path, capsys):
        from installation.cli import main

        path = write_config(_aws({"range_egress": {"mode": "status-quo"}}, aws_config))
        bad_target = tmp_path / "no-such-dir" / "out.tfvars"
        rc = main(["render", str(path), "--output", str(bad_target)])
        assert rc == 1
        assert capsys.readouterr().err != ""

    def test_render_default_path_is_shifter_yaml_in_cwd(self, write_config, aws_config, monkeypatch, capsys):
        from installation.cli import main

        write_config(_aws({"range_egress": {"mode": "status-quo"}}, aws_config))
        monkeypatch.chdir(write_config(_aws({"range_egress": {"mode": "status-quo"}}, aws_config)).parent)
        rc = main(["render"])
        assert rc == 0
        assert "victim_allowed_cidrs = []" in capsys.readouterr().out


@pytest.mark.integration
class TestModuleEntrypoint:
    """``python -m installation render`` is the documented entry point."""

    def test_python_m_installation_renders_an_example(self, examples_dir):
        result = subprocess.run(
            [sys.executable, "-m", "installation", "render", str(examples_dir / "aws.yaml")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "victim_allowed_cidrs = []" in result.stdout

    def test_python_m_installation_render_fails_on_missing_file(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "installation", "render", str(tmp_path / "nope.yaml")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "nope.yaml" in result.stderr
