"""Tests for the GCP range Terraform module."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "terraform" / "modules" / "gcp-range"


class TestGcpRangeModuleContract:
    """Static contract tests for the GCP range module."""

    def test_outputs_preserve_range_contract_shape(self):
        outputs_tf = (MODULE_PATH / "outputs.tf").read_text(encoding="utf-8")

        assert 'output "subnets"' in outputs_tf
        assert 'output "instances"' in outputs_tf
        assert 'output "dc_config_param_name"' in outputs_tf
        assert "subnet_id" in outputs_tf
        assert "subnet_cidr" in outputs_tf
        assert "instance_id" in outputs_tf
        assert "private_ip" in outputs_tf
        assert "ssh_key_secret_arn" in outputs_tf

    def test_windows_startup_templates_enable_sshd(self):
        victim_template = (MODULE_PATH / "templates" / "victim_windows.ps1.tpl").read_text(encoding="utf-8")
        dc_template = (MODULE_PATH / "templates" / "dc_windows.ps1.tpl").read_text(encoding="utf-8")

        assert "Get-WindowsCapability" in victim_template
        assert "Get-Service -Name sshd" in victim_template
        assert "Start-Service sshd" in victim_template
        assert "Get-WindowsCapability" in dc_template
        assert "Get-Service -Name sshd" in dc_template
        assert "Start-Service sshd" in dc_template

    def test_gcp_startup_templates_leave_hostname_to_setup_plans(self):
        kali_template = (MODULE_PATH / "templates" / "kali.sh.tpl").read_text(encoding="utf-8")
        linux_template = (MODULE_PATH / "templates" / "victim_linux.sh.tpl").read_text(encoding="utf-8")
        victim_windows = (MODULE_PATH / "templates" / "victim_windows.ps1.tpl").read_text(encoding="utf-8")
        dc_windows = (MODULE_PATH / "templates" / "dc_windows.ps1.tpl").read_text(encoding="utf-8")

        assert "hostnamectl set-hostname" not in kali_template
        assert "hostnamectl set-hostname" not in linux_template
        assert "Rename-Computer" not in victim_windows
        assert "Rename-Computer" not in dc_windows


class TestGcpRangeModuleValidation:
    """Validation tests for the Terraform module itself."""

    @pytest.mark.slow
    def test_module_validates_with_example_configuration(self, tmp_path: Path):
        terraform_bin = shutil.which("terraform")
        if terraform_bin is None:
            pytest.skip("terraform is not installed")

        main_tf = textwrap.dedent(
            f"""
            terraform {{
              required_version = ">= 1.0"

              required_providers {{
                google = {{
                  source  = "hashicorp/google"
                  version = ">= 6.0"
                }}
                tls = {{
                  source  = "hashicorp/tls"
                  version = ">= 4.0"
                }}
              }}
            }}

            provider "google" {{
              project = "shifter-gcp-dev"
              region  = "us-central1"
            }}

            module "range" {{
              source = "{MODULE_PATH.as_posix()}"

              range_id          = 42
              user_id           = 7
              request_uuid      = "550e8400-e29b-41d4-a716-446655440000"
              environment       = "gcp-dev"
              vpc_id            = "projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range"
              vpc_cidr          = "10.50.0.0/16"
              availability_zone = "us-central1-b"
              region            = "us-central1"
              portal_vpc_cidr   = "10.40.0.0/20"

              kali_ami_id    = "projects/test/global/images/family/kali"
              victim_ami_id  = "projects/debian-cloud/global/images/family/debian-12"
              windows_ami_id = "projects/windows-cloud/global/images/family/windows-2022"
              dc_ami_id      = "projects/windows-cloud/global/images/family/windows-2022"

              subnets = [
                {{
                  name         = "attack"
                  uuid         = "11111111-1111-1111-1111-111111111111"
                  cidr         = "10.50.1.0/28"
                  connected_to = ["victims"]
                  instances = [
                    {{
                      uuid                = "aaaaaaaa-1111-1111-1111-111111111111"
                      name                = "kali-01"
                      role                = "attacker"
                      os_type             = "kali"
                      instance_type       = "e2-standard-4"
                      agent_presigned_url = ""
                      join_domain         = false
                      ami_id              = ""
                    }}
                  ]
                }},
                {{
                  name         = "victims"
                  uuid         = "22222222-2222-2222-2222-222222222222"
                  cidr         = "10.50.1.16/28"
                  connected_to = ["attack"]
                  instances = [
                    {{
                      uuid                = "bbbbbbbb-2222-2222-2222-222222222222"
                      name                = "ubuntu-01"
                      role                = "victim"
                      os_type             = "ubuntu"
                      instance_type       = "e2-standard-2"
                      agent_presigned_url = "https://example.test/linux-agent"
                      join_domain         = false
                      ami_id              = ""
                    }},
                    {{
                      uuid                = "cccccccc-3333-3333-3333-333333333333"
                      name                = "win-01"
                      role                = "victim"
                      os_type             = "windows"
                      instance_type       = "e2-standard-4"
                      agent_presigned_url = "https://example.test/windows-agent"
                      join_domain         = true
                      ami_id              = ""
                    }},
                    {{
                      uuid                = "dddddddd-4444-4444-4444-444444444444"
                      name                = "dc-01"
                      role                = "dc"
                      os_type             = "windows"
                      instance_type       = "e2-standard-4"
                      agent_presigned_url = ""
                      join_domain         = false
                      ami_id              = ""
                    }}
                  ]
                }}
              ]
            }}
            """
        ).strip()

        (tmp_path / "main.tf").write_text(main_tf, encoding="utf-8")

        init_result = subprocess.run(  # noqa: S603
            [terraform_bin, "init", "-backend=false"],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert init_result.returncode == 0, init_result.stderr

        validate_result = subprocess.run(  # noqa: S603
            [terraform_bin, "validate"],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert validate_result.returncode == 0, validate_result.stderr
