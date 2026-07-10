"""
Tests for the GCP (Compute Engine) Packer image build configuration.

These cover the GCE `googlecompute` builders that live in `shifter/packer/gcp/`,
parallel to the AWS `amazon-ebs` builders one directory up. They are a SEPARATE
template set so the AWS `packer build .` / `-only='*.<type>'` flow never sees a
`googlecompute` source (issue #505, PLAT-001.10).

Run with: pytest shifter/packer/tests/test_packer_gcp.py -v
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PACKER_DIR = Path(__file__).parent.parent
GCP_DIR = PACKER_DIR / "gcp"
GCP_SCRIPTS_DIR = GCP_DIR / "scripts"

# Image types that ship a GCE builder in this iteration.
GCE_IMAGE_TYPES = ["ubuntu", "brokenbk", "kali", "windows", "dc", "polaris-vm", "dc-prebaked"]


class TestGcpTemplateStructure:
    """The GCE templates exist and are provider-scoped."""

    def test_gcp_dir_exists(self):
        assert GCP_DIR.is_dir(), "shifter/packer/gcp/ should exist"

    @pytest.mark.parametrize("image_type", GCE_IMAGE_TYPES)
    def test_template_exists(self, image_type):
        assert (GCP_DIR / f"{image_type}.pkr.hcl").exists(), f"Missing GCE template: gcp/{image_type}.pkr.hcl"

    def test_variables_file_exists(self):
        assert (GCP_DIR / "variables.pkr.hcl").exists()

    @pytest.mark.parametrize("var_file", ["dev.pkrvars.hcl", "proof.pkrvars.hcl"])
    def test_var_files_exist(self, var_file):
        assert (GCP_DIR / var_file).exists(), f"Missing GCP var-file: gcp/{var_file}"


class TestGcpBuilderType:
    """Every GCE template uses the googlecompute builder, never amazon-ebs."""

    @pytest.fixture(params=GCE_IMAGE_TYPES)
    def template_content(self, request):
        return (GCP_DIR / f"{request.param}.pkr.hcl").read_text()

    def test_uses_googlecompute_source(self, template_content):
        assert "googlecompute" in template_content, "GCE template must declare a googlecompute source"

    def test_no_amazon_ebs_source(self, template_content):
        assert "amazon-ebs" not in template_content, "GCE template must not reference the AWS amazon-ebs builder"

    def test_no_aws_region_variable(self, template_content):
        # GCP builders are scoped on project/zone, never aws_region (preflight:
        # do not reuse AWS Packer variables for GCP).
        assert "aws_region" not in template_content
        assert "var.vpc_id" not in template_content
        assert "var.subnet_id" not in template_content

    def test_publishes_image_family(self, template_content):
        # image_family is the GCP-idiomatic version pointer (the analog of the
        # AWS /shifter/ami/* SSM parameter). Consumers resolve newest-in-family.
        # Require the OUTPUT image_family attribute specifically — a bare
        # substring check would also match source_image_family, so a template
        # that dropped the output attribute (breaking family publishing) would
        # still pass.
        assert re.search(r"(?<!source_)image_family\s*=", template_content), (
            "GCE template must set the output image_family attribute, not just source_image_family"
        )

    def test_no_ssm_parameter_ref(self, template_content):
        # Preflight anti-pattern: do not store GCE image refs in AWS SSM.
        assert "/shifter/ami/" not in template_content


class TestGcpProviderRequirement:
    """Templates pin the googlecompute Packer plugin."""

    @pytest.fixture(params=GCE_IMAGE_TYPES)
    def template_content(self, request):
        return (GCP_DIR / f"{request.param}.pkr.hcl").read_text()

    def test_googlecompute_plugin_pinned_somewhere(self):
        # The plugin must be declared once for the directory (all *.pkr.hcl in
        # the dir are one Packer config) so `packer init` installs it.
        joined = "\n".join(p.read_text() for p in GCP_DIR.glob("*.pkr.hcl"))
        assert "github.com/hashicorp/googlecompute" in joined


class TestGcpWindowsSysprep:
    """Windows/DC must use GCESysprep, not the AWS EC2Launch sysprep."""

    def test_gcp_sysprep_script_exists(self):
        assert (GCP_SCRIPTS_DIR / "windows" / "sysprep.ps1").exists(), (
            "GCE Windows builders need a GCP-specific sysprep script"
        )

    def test_sysprep_uses_gcesysprep(self):
        content = (GCP_SCRIPTS_DIR / "windows" / "sysprep.ps1").read_text()
        assert "GCESysprep" in content or "gcesysprep" in content.lower()

    def test_sysprep_does_not_use_ec2launch(self):
        content = (GCP_SCRIPTS_DIR / "windows" / "sysprep.ps1").read_text()
        assert "EC2Launch" not in content

    @pytest.mark.parametrize("image_type", ["windows", "dc"])
    def test_windows_template_references_gcp_sysprep(self, image_type):
        content = (GCP_DIR / f"{image_type}.pkr.hcl").read_text()
        assert "scripts/windows/sysprep.ps1" in content


class TestGcpDcPrebaked:
    """dc-prebaked bakes many pre-promoted DC images from one parameterized template."""

    def test_template_is_parameterized_by_domain_and_content(self):
        content = (GCP_DIR / "dc-prebaked.pkr.hcl").read_text()
        # Domain / NetBIOS / content / purpose are variables, not hardcoded.
        for var in ("var.dc_domain_name", "var.dc_netbios_name", "var.dc_content_script", "var.dc_image_purpose"):
            assert var in content, f"dc-prebaked template must use {var}"
        # The image family is purpose-driven, not a fixed polaris name.
        assert 'image_family      = "${var.image_prefix}-${var.dc_image_purpose}-dc"' in content

    def test_promote_bake_reads_domain_from_env(self):
        content = (GCP_SCRIPTS_DIR / "dc-prebaked" / "promote-bake.ps1").read_text()
        assert "DC_DOMAIN_NAME" in content and "DC_NETBIOS_NAME" in content
        assert "-DomainName $DomainName" in content

    def test_variables_declare_dc_prebaked_knobs(self):
        content = (GCP_DIR / "variables.pkr.hcl").read_text()
        for var in ("dc_image_purpose", "dc_domain_name", "dc_netbios_name", "dc_content_script"):
            assert f'variable "{var}"' in content, f"variables.pkr.hcl must declare {var}"

    @pytest.mark.parametrize("profile", ["polaris", "example"])
    def test_profile_var_file_exists_and_sets_purpose(self, profile):
        path = GCP_DIR / "dc-profiles" / f"{profile}.pkrvars.hcl"
        assert path.exists(), f"Missing DC profile: dc-profiles/{profile}.pkrvars.hcl"
        content = path.read_text()
        for key in ("dc_image_purpose", "dc_domain_name", "dc_netbios_name", "dc_content_script"):
            assert key in content, f"profile {profile} must set {key}"

    def test_polaris_profile_reproduces_boreas_local(self):
        content = (GCP_DIR / "dc-profiles" / "polaris.pkrvars.hcl").read_text()
        assert '"boreas.local"' in content
        assert '"polaris"' in content
        assert "a2_setup.ps1" in content


class TestGcpKaliSourceImage:
    """Kali has no public GCP image; the builder converts the debian-12 base."""

    def test_kali_builds_on_debian_base_and_converts(self):
        content = (GCP_DIR / "kali.pkr.hcl").read_text()
        # No public Kali family on GCP, and the official genericcloud disk is not
        # GCE-bootable, so the kali builder starts from the GCE-native debian-12
        # base and converts it to Kali in its first provisioning script.
        assert 'source_image_family     = "debian-12"' in content
        assert "../scripts/kali/gce-debian-to-kali.sh" in content
        # The imported-base path (and its variable) is fully retired.
        assert "kali_source_image" not in content

    def test_kali_conversion_script_preserves_guest_agent(self):
        script = (PACKER_DIR / "scripts" / "kali" / "gce-debian-to-kali.sh").read_text()
        # The Kali repos omit google-guest-agent; the conversion must re-assert
        # it or the captured image loses metadata SSH + networking on GCE.
        assert "google-guest-agent" in script
        assert "--force-overwrite" in script


class TestGcpPackerValidate:
    """`packer validate` passes against the GCE templates (when packer is present)."""

    @pytest.mark.skipif(
        shutil.which("packer") is None,
        reason="Packer not installed",
    )
    def test_packer_validate(self):
        packer_path = shutil.which("packer")

        # Pass cwd= rather than os.chdir() so the validate runs in GCP_DIR
        # without mutating the process-global working directory for the rest
        # of the pytest session.
        # Security context: packer_path from shutil.which() in controlled test env
        subprocess.run([packer_path, "init", "."], capture_output=True, cwd=GCP_DIR)  # noqa: S603

        result = subprocess.run(  # noqa: S603
            [packer_path, "validate", "-var-file=dev.pkrvars.hcl", "."],
            capture_output=True,
            text=True,
            cwd=GCP_DIR,
        )
        assert result.returncode == 0, f"Packer validate failed: {result.stderr}"


class TestAwsTemplatesUnaffected:
    """AC3 guard: the GCE templates must not leak into the AWS template set."""

    def test_aws_dir_has_no_googlecompute(self):
        for template in PACKER_DIR.glob("*.pkr.hcl"):
            content = template.read_text()
            assert "googlecompute" not in content, (
                f"AWS template {template.name} must not contain a googlecompute source — GCE builders live in gcp/"
            )
