"""Tests for CI/local Terraform backend config rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

import render_aws_backend_configs as renderer


def test_validate_env_rejects_unknown_environment():
    with pytest.raises(ValueError, match="unsupported environment"):
        renderer.validate_env("staging")


def test_validate_bucket_rejects_shell_metacharacters():
    with pytest.raises(ValueError, match="invalid TF_INFRA_STATE_BUCKET"):
        renderer.validate_bucket("bucket-$(whoami)")


def test_append_github_env_writes_simple_assignment(tmp_path: Path):
    env_file = tmp_path / "github_env"
    renderer.append_github_env(env_file, "SHIFTER_BACKEND_CONFIG_PATH", "/tmp/backend/dev.s3.tfbackend")
    assert env_file.read_text() == "SHIFTER_BACKEND_CONFIG_PATH=/tmp/backend/dev.s3.tfbackend\n"


def test_render_outputs_writes_backend_files(tmp_path: Path):
    instance_dir = tmp_path / "instance"
    outputs = renderer.render_outputs(
        env="dev",
        bucket="shifter-dev-infra-test",
        region="us-east-2",
        instance_dir=instance_dir,
        stack="core",
    )
    backend_path = Path(outputs["SHIFTER_BACKEND_CONFIG_PATH"])
    assert backend_path.exists()
    assert "shifter-dev-infra-test" in backend_path.read_text()


def test_main_github_env_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    github_env = tmp_path / "github_env"
    instance_dir = tmp_path / "instance"
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.setenv("TF_INFRA_STATE_BUCKET", "shifter-dev-infra-test")
    monkeypatch.setenv("SHIFTER_INSTANCE_DIR", str(instance_dir))
    monkeypatch.setattr(
        "sys.argv",
        [
            "render_aws_backend_configs.py",
            "--env",
            "dev",
            "--stack",
            "core",
            "--github-env",
        ],
    )

    assert renderer.main() == 0
    content = github_env.read_text()
    assert "SHIFTER_BACKEND_CONFIG_PATH=" in content
    assert "SHIFTER_INSTANCE_DIR=" in content
