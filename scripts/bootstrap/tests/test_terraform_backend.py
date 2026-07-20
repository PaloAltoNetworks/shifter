"""Tests for per-instance Terraform S3 backend config rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

import terraform_backend as tb


@pytest.fixture
def instance_dir(tmp_path: Path) -> Path:
    return tmp_path / "instance"


class TestRenderS3Tfbackend:
    def test_renders_required_fields(self):
        content = tb.render_s3_tfbackend(
            bucket="shifter-dev-infra-abc",
            key="shifter/dev/terraform.tfstate",
            region="us-west-2",
        )
        assert 'bucket       = "shifter-dev-infra-abc"' in content
        assert 'key          = "shifter/dev/terraform.tfstate"' in content
        assert 'region       = "us-west-2"' in content
        assert "use_lockfile = true" in content
        assert "encrypt      = true" in content

    def test_rejects_empty_bucket(self):
        with pytest.raises(ValueError, match="bucket"):
            tb.render_s3_tfbackend(bucket="", key="k", region="us-east-2")


class TestInstanceBackendDir:
    def test_default_dir_is_outside_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        resolved = tb.resolve_instance_backend_dir(env="dev", bucket="shifter-dev-infra-abc")
        assert resolved.is_absolute()
        assert "shifter-dev-infra-abc" in str(resolved)
        assert resolved.name == "terraform-backend"

    def test_explicit_instance_dir_wins(self, instance_dir: Path):
        resolved = tb.resolve_instance_backend_dir(
            env="dev",
            bucket="shifter-dev-infra-abc",
            instance_dir=instance_dir,
        )
        assert resolved == instance_dir / "terraform-backend"


class TestWriteInstanceBackendConfigs:
    def test_writes_all_env_and_global_stacks(self, instance_dir: Path):
        backend_dir = tb.resolve_instance_backend_dir(
            env="dev",
            bucket="my-bucket",
            instance_dir=instance_dir,
        )
        paths = tb.write_instance_backend_configs(
            backend_dir=backend_dir,
            env="dev",
            bucket="my-bucket",
            region="us-east-2",
        )

        assert (backend_dir / "environments/dev/dev.s3.tfbackend") in paths.values()
        assert (backend_dir / "environments/dev/portal/dev.s3.tfbackend") in paths.values()
        assert (backend_dir / "environments/dev/range/dev.s3.tfbackend") in paths.values()
        assert (backend_dir / "global/iam/dev.s3.tfbackend") in paths.values()

        portal_config = (backend_dir / "environments/dev/portal/dev.s3.tfbackend").read_text()
        assert 'bucket       = "my-bucket"' in portal_config
        assert 'key          = "dev/portal/terraform.tfstate"' in portal_config

    def test_does_not_write_into_repo_tree(self, instance_dir: Path, tmp_path: Path):
        fake_repo = tmp_path / "repo"
        fake_repo.mkdir()
        repo_backend = fake_repo / "platform/terraform/environments/dev/dev.s3.tfbackend"
        repo_backend.parent.mkdir(parents=True)
        repo_backend.write_text('bucket = "REPLACE_AT_BOOTSTRAP"\n')

        backend_dir = tb.resolve_instance_backend_dir(
            env="dev",
            bucket="my-bucket",
            instance_dir=instance_dir,
        )
        tb.write_instance_backend_configs(
            backend_dir=backend_dir,
            env="dev",
            bucket="my-bucket",
            region="us-east-2",
        )
        assert "my-bucket" not in repo_backend.read_text()


class TestPortalRemoteStateTfvars:
    def test_renders_bucket_and_region(self):
        content = tb.render_portal_remote_state_tfvars(
            bucket="my-bucket",
            region="us-east-2",
        )
        assert 'terraform_state_bucket = "my-bucket"' in content
        assert 'terraform_state_region = "us-east-2"' in content

    def test_write_portal_remote_state_tfvars(self, instance_dir: Path):
        path = tb.write_portal_remote_state_tfvars(
            instance_dir=instance_dir,
            env="dev",
            bucket="my-bucket",
            region="us-east-2",
        )
        assert path.exists()
        assert path.parent == instance_dir / "terraform-vars/dev/portal"
        assert "my-bucket" in path.read_text()
