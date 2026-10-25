"""
Tests for the GCP (Compute Engine) Packer image build configuration.

These cover the GCE `googlecompute` builders that live in `shifter/packer/gcp/`,
parallel to the AWS `amazon-ebs` builders one directory up. They are a SEPARATE
template set so the AWS `packer build .` / `-only='*.<type>'` flow never sees a
`googlecompute` source (issue #505, PLAT-001.10).

Run with: pytest shifter/packer/tests/test_packer_gcp.py -v
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PACKER_DIR = Path(__file__).parent.parent
GCP_DIR = PACKER_DIR / "gcp"
GCP_SCRIPTS_DIR = GCP_DIR / "scripts"

# Image types that ship a GCE builder in this iteration.
GCE_IMAGE_TYPES = ["ubuntu", "brokenbk", "kali", "windows", "dc", "dc-prebaked"]


class TestGcpTemplateStructure:
    """The GCE templates exist and are provider-scoped."""

    def test_gcp_dir_exists(self):
        assert GCP_DIR.is_dir(), "shifter/packer/gcp/ should exist"

    @pytest.mark.parametrize("image_type", GCE_IMAGE_TYPES)
    def test_template_exists(self, image_type):
        assert (GCP_DIR / f"{image_type}.pkr.hcl").exists(), f"Missing GCE template: gcp/{image_type}.pkr.hcl"

    def test_variables_file_exists(self):
        assert (GCP_DIR / "variables.pkr.hcl").exists()

    @pytest.mark.parametrize("var_file", ["dev.pkrvars.hcl"])
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
        # The image family is purpose-driven, not a fixed example name.
        assert 'image_family      = "${var.image_prefix}-${var.dc_image_purpose}-dc"' in content

    def test_promote_bake_reads_domain_from_env(self):
        content = (GCP_SCRIPTS_DIR / "dc-prebaked" / "promote-bake.ps1").read_text()
        assert "DC_DOMAIN_NAME" in content
        assert "DC_NETBIOS_NAME" in content
        assert "-DomainName $DomainName" in content

    def test_variables_declare_dc_prebaked_knobs(self):
        content = (GCP_DIR / "variables.pkr.hcl").read_text()
        for var in ("dc_image_purpose", "dc_domain_name", "dc_netbios_name", "dc_content_script"):
            assert f'variable "{var}"' in content, f"variables.pkr.hcl must declare {var}"

    @pytest.mark.parametrize("profile", ["example"])
    def test_profile_var_file_exists_and_sets_purpose(self, profile):
        path = GCP_DIR / "dc-profiles" / f"{profile}.pkrvars.hcl"
        assert path.exists(), f"Missing DC profile: dc-profiles/{profile}.pkrvars.hcl"
        content = path.read_text()
        for key in ("dc_image_purpose", "dc_domain_name", "dc_netbios_name", "dc_content_script"):
            assert key in content, f"profile {profile} must set {key}"


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

    def test_kali_conversion_script_regenerates_ssh_host_keys(self):
        script = (PACKER_DIR / "scripts" / "kali" / "gce-debian-to-kali.sh").read_text()
        # cleanup.sh strips host keys; Kali (unlike Ubuntu) does not regenerate
        # them on first boot, so sshd never binds :22 and the range provisioner's
        # SSH-wait times out (#1745). The conversion must install a first-boot
        # oneshot that runs `ssh-keygen -A` before sshd.
        assert "regenerate-ssh-host-keys.service" in script
        assert "ssh-keygen -A" in script
        assert "systemctl enable regenerate-ssh-host-keys.service" in script


@pytest.mark.integration
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


REPO_ROOT = PACKER_DIR.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


class TestGcpBuildEvidenceBinding:
    """Validation accepts only immutable evidence from the candidate's build."""

    def _run_verifier(self, tmp_path, *, evidence_updates=None, env_updates=None):
        evidence = {
            "schema_version": 1,
            "repository": "Brad-Edwards/shifter",
            "workflow": ".github/workflows/packer-gcp.yml",
            "source_ref": "refs/heads/dev",
            "source_revision": "a" * 40,
            "image_name": "shifter-example-stack-123",
            "image_id": 987654321,
            "image_family": "shifter-example-stack",
            "image_type": "example-stack",
            "environment": "dev",
            "build_run": 12345,
            "build_run_attempt": 2,
        }
        evidence.update(evidence_updates or {})
        evidence_file = tmp_path / "build-evidence.json"
        evidence_file.write_text(json.dumps(evidence))
        env = dict(os.environ)
        env.update(
            {
                "BUILD_EVIDENCE_FILE": str(evidence_file),
                "EXPECTED_REPOSITORY": "Brad-Edwards/shifter",
                "EXPECTED_SOURCE_REF": "refs/heads/dev",
                "EXPECTED_SOURCE_REVISION": "a" * 40,
                "EXPECTED_IMAGE_NAME": "shifter-example-stack-123",
                "EXPECTED_IMAGE_ID": "987654321",
                "EXPECTED_IMAGE_FAMILY": "shifter-example-stack",
                "EXPECTED_IMAGE_TYPE": "example-stack",
                "EXPECTED_ENVIRONMENT": "dev",
            }
        )
        env.update(env_updates or {})
        bash_path = shutil.which("bash")
        assert bash_path is not None
        return subprocess.run(  # noqa: S603
            [bash_path, str(GCP_SCRIPTS_DIR / "validate" / "verify-build-evidence.sh")],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_exact_candidate_build_evidence_is_accepted(self, tmp_path):
        result = self._run_verifier(tmp_path)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        "evidence_updates",
        [
            {"source_revision": "b" * 40},
            {"image_id": 123},
            {"image_name": "other-image"},
            {"source_ref": "refs/heads/main"},
            {"workflow": ".github/workflows/other.yml"},
            {"build_run": "not-numeric"},
        ],
    )
    def test_mismatched_candidate_build_evidence_is_rejected(self, tmp_path, evidence_updates):
        result = self._run_verifier(tmp_path, evidence_updates=evidence_updates)
        assert result.returncode != 0


class TestGcpPromotionEvidenceBinding:
    """Promotion verifies trusted run evidence instead of trusting a mutable label."""

    @pytest.fixture
    def promote(self):
        return (WORKFLOWS_DIR / "packer-gcp-promote.yml").read_text()

    def test_workflow_reads_validation_run_and_revision_labels(self, promote):
        assert "labels.validated-run" in promote
        assert "labels.validated-revision" in promote
        assert "labels.validated-verdict-id" in promote

    def test_workflow_downloads_and_verifies_validation_evidence(self, promote):
        assert "actions: read" in promote
        assert '"${SRC_PROJECT}-release-evidence"' in promote
        assert "gcloud storage cp --quiet" in promote
        assert "actions/artifacts/${VALIDATED_VERDICT_ID}" in promote
        assert "ARTIFACT_FILE" in promote
        assert "VERDICT_FILE" in promote
        assert "gh run download" not in promote
        assert "verify-promotion-evidence.sh" in promote

    def test_validation_publishes_versioned_image_id_and_private_evidence_digest(self):
        validate = (WORKFLOWS_DIR / "packer-gcp-validate.yml").read_text()
        assert '"schema_version": 3' in validate
        assert "candidate_image_id:" in validate
        assert "validation_run_attempt:" in validate
        assert "validated-evidence-sha" in validate
        assert "validated-verdict-id" in validate
        assert "validated-image-id" in validate
        assert "Store raw validation evidence privately" in validate
        assert "validation-verdict.json" in validate
        assert "candidate_binding_sha256" in validate
        artifact_block = validate.split("Upload redacted validation verdict", 1)[1].split(
            "Publish the authoritative", 1
        )[0]
        assert "guest-sbom.spdx.json" not in artifact_block

    def test_validation_collects_and_binds_exact_guest_sbom(self):
        validate = (WORKFLOWS_DIR / "packer-gcp-validate.yml").read_text()
        scanner = (GCP_SCRIPTS_DIR / "validate" / "scan-attached-disk.sh").read_text()
        assert "Install independently pinned Syft" in validate
        assert "SYFT_ARCHIVE_SHA256" in validate
        assert "Collect SBOM outside the candidate trust domain" in validate
        assert "--mode=ro" in validate
        assert "DISK_SOURCE_IMAGE_ID" in validate
        assert "scan-attached-disk.sh" in validate
        assert 'blockdev --getro "${device}"' in scanner
        assert "ro,nosuid,nodev,noexec" in scanner
        assert "external-read-only-disk" in validate
        assert "validator@${VALIDATION_VM}:/tmp/syft" not in validate
        assert "guest-sbom.spdx.json" in validate
        assert "guest_sbom_sha256:" in validate
        assert "guest_sbom_format:" in validate
        assert "guest_sbom_tool:" in validate
        assert "VALIDATOR_SSH_KEY=${RUNNER_TEMP}" in validate
        assert "/tmp/validator_key" not in validate  # noqa: S108
        assert "Remove validation credentials and evidence" in validate

    @staticmethod
    def _run_attached_disk_scanner(
        tmp_path,
        *,
        device_read_only="1",
        filesystem_read_only="1",
        mount_options="rw,nosuid,nodev,noexec",
    ):
        stub_dir = tmp_path / "scanner-bin"
        stub_dir.mkdir()
        device = tmp_path / "candidate-device"
        filesystem = tmp_path / "candidate-filesystem"
        device.touch()
        filesystem.touch()

        (stub_dir / "blockdev").write_text(
            "#!/bin/bash\n"
            'if [ "$2" = "$SCANNER_DEVICE" ]; then printf "%s\\n" "$SCANNER_DEVICE_RO"; exit 0; fi\n'
            'if [ "$2" = "$SCANNER_FILESYSTEM" ]; then printf "%s\\n" "$SCANNER_FILESYSTEM_RO"; exit 0; fi\n'
            "exit 2\n"
        )
        (stub_dir / "lsblk").write_text(
            "#!/bin/bash\n"
            'printf \'{"blockdevices":[{"path":"%s","type":"part","size":1048576,'
            '"fstype":"ext4","ro":true}]}\\n\' "$SCANNER_FILESYSTEM"\n'
        )
        (stub_dir / "mount").write_text("#!/bin/bash\nexit 0\n")
        (stub_dir / "findmnt").write_text('#!/bin/bash\nprintf "%s\\n" "$SCANNER_MOUNT_OPTIONS"\n')
        (stub_dir / "mountpoint").write_text("#!/bin/bash\nexit 1\n")
        for command in ("blockdev", "lsblk", "mount", "findmnt", "mountpoint"):
            (stub_dir / command).chmod(0o755)

        syft = tmp_path / "syft"
        syft.write_text(
            "#!/bin/bash\n"
            'for arg in "$@"; do\n'
            '  case "$arg" in spdx-json=*) output="${arg#spdx-json=}" ;; esac\n'
            "done\n"
            'printf "{\\"spdxVersion\\":\\"SPDX-2.3\\"}\\n" > "$output"\n'
        )
        syft.chmod(0o755)
        output = tmp_path / "guest-sbom.spdx.json"
        mount_root = tmp_path / "candidate-mount"
        run_env = dict(os.environ)
        run_env.update(
            {
                "PATH": f"{stub_dir}:{run_env['PATH']}",
                "DEVICE_LINK": str(device),
                "SCANNER_DEVICE": str(device),
                "SCANNER_DEVICE_RO": device_read_only,
                "SCANNER_FILESYSTEM": str(filesystem),
                "SCANNER_FILESYSTEM_RO": filesystem_read_only,
                "SCANNER_MOUNT_OPTIONS": mount_options,
                "SYFT_PATH": str(syft),
                "OUTPUT_PATH": str(output),
                "MOUNT_ROOT": str(mount_root),
            }
        )
        bash = shutil.which("bash")
        assert bash is not None
        result = subprocess.run(  # noqa: S603
            [bash, str(GCP_SCRIPTS_DIR / "validate" / "scan-attached-disk.sh")],
            capture_output=True,
            text=True,
            env=run_env,
        )
        return result, output

    def test_attached_disk_scanner_accepts_only_read_only_noexec_mount(self, tmp_path):
        result, output = self._run_attached_disk_scanner(
            tmp_path,
            mount_options="ro,nosuid,nodev,noexec,relatime",
        )

        assert result.returncode == 0, result.stderr
        assert output.is_file()
        assert output.stat().st_mode & 0o777 == 0o600

    @pytest.mark.parametrize(
        ("kwargs", "error"),
        [
            ({"device_read_only": "0"}, "candidate disk is not attached read-only"),
            ({"mount_options": "ro,nosuid,nodev,exec"}, "candidate mount is missing noexec"),
        ],
    )
    def test_attached_disk_scanner_rejects_unsafe_disk_or_mount(self, tmp_path, kwargs, error):
        result, output = self._run_attached_disk_scanner(tmp_path, **kwargs)

        assert result.returncode != 0
        assert error in result.stderr
        assert not output.exists()

    def test_sbom_collection_adds_no_candidate_guest_agent(self):
        shared_services = (PACKER_DIR / "scripts" / "windows" / "services.ps1").read_text()
        assert "google-compute-engine-ssh" not in shared_services
        for image_type in ("windows", "dc", "dc-prebaked"):
            template = (GCP_DIR / f"{image_type}.pkr.hcl").read_text()
            assert "install-gce-ssh.ps1" not in template
        assert not (GCP_SCRIPTS_DIR / "windows" / "install-gce-ssh.ps1").exists()
        assert not (GCP_SCRIPTS_DIR / "validate" / "collect-windows-sbom.ps1").exists()

    def test_build_source_revision_is_immutably_bound_before_validation(self):
        build = (WORKFLOWS_DIR / "packer-gcp.yml").read_text()
        validate = (WORKFLOWS_DIR / "packer-gcp-validate.yml").read_text()
        assert "PKR_VAR_source_revision=${GITHUB_SHA}" in build
        assert "Store immutable build-source evidence" in build
        assert "packer-builds/${BUILT_IMAGE_ID}/build-evidence.json" in build
        assert "packer-builds/${CANDIDATE_IMAGE_ID}/build-evidence.json" in validate
        assert "verify-build-evidence.sh" in validate
        assert 'EXPECTED_SOURCE_REVISION="${GITHUB_SHA}"' in validate
        assert "CANDIDATE_SOURCE_LABEL" in validate
        for image_type in GCE_IMAGE_TYPES:
            template = (GCP_DIR / f"{image_type}.pkr.hcl").read_text()
            assert "source-revision = var.source_revision" in template

    def test_evidence_timestamp_is_not_published_as_an_invalid_gcp_label(self):
        validate = (WORKFLOWS_DIR / "packer-gcp-validate.yml").read_text()
        assert "validated_at_utc: $validated_at_utc" in validate
        assert "validated-at=${VALIDATED_AT}" not in validate

    def test_promotion_commits_family_only_after_source_and_ready_checks(self, promote):
        create = promote.index('gcloud compute images create "${NEW_PROD_IMAGE}"')
        ready = promote.index('NEW_STATUS="$(gcloud compute images describe')
        source = promote.index("value(sourceImageId)")
        family = promote.index('gcloud compute images update "${NEW_PROD_IMAGE}"')
        assert "--family=" not in promote[create:ready]
        assert create < ready < source < family

    def test_promotion_serializes_channel_updates_and_validates_image_name(self, promote):
        assert "group: gcp-image-promotion-prod" in promote
        assert "cancel-in-progress: false" in promote
        assert "Source image name must be a valid GCE image resource name" in promote

    def test_verifier_script_exists(self):
        assert (GCP_SCRIPTS_DIR / "validate" / "verify-promotion-evidence.sh").exists()

    def _run_verifier(
        self,
        tmp_path,
        *,
        evidence_updates=None,
        run_updates=None,
        verdict_updates=None,
        artifact_updates=None,
        omit_file=None,
        unset_env=None,
        env_updates=None,
    ):
        guest_sbom_file = tmp_path / "guest-sbom.spdx.json"
        guest_sbom_file.write_text('{"spdxVersion":"SPDX-2.3","packages":[{"name":"base"}]}')
        guest_sbom_sha256 = hashlib.sha256(guest_sbom_file.read_bytes()).hexdigest()
        evidence = {
            "schema_version": 3,
            "repository": "Brad-Edwards/shifter",
            "workflow": ".github/workflows/packer-gcp-validate.yml",
            "source_ref": "refs/heads/dev",
            "candidate_image": "shifter-example-stack-123",
            "candidate_image_id": "987654321",
            "project": "dev-project",
            "environment": "dev",
            "image_family": "shifter-example-stack",
            "image_type": "example-stack",
            "source_revision": "a" * 40,
            "validation_run": "12345",
            "validation_run_attempt": 2,
            "validated_at_utc": "20260906T120000",
            "phases": ["first_boot_health", "reboot_health"],
            "guest_sbom_file": "guest-sbom.spdx.json",
            "guest_sbom_sha256": guest_sbom_sha256,
            "guest_sbom_format": "spdx-json",
            "guest_sbom_tool": "syft/1.51.1",
            "guest_sbom_collection": "external-read-only-disk",
            "guest_sbom_source_image_id": "987654321",
            "guest_sbom_scanner_image": "ubuntu-2204-jammy-v20260901",
            "guest_sbom_scanner_image_id": "1122334455",
            "result": "passed",
        }
        run = {
            "id": 12345,
            "run_attempt": 2,
            "name": "Packer GCE Image Validate",
            "path": ".github/workflows/packer-gcp-validate.yml",
            "event": "workflow_dispatch",
            "head_branch": "dev",
            "head_sha": "a" * 40,
            "conclusion": "success",
            "repository": {"full_name": "Brad-Edwards/shifter"},
        }
        evidence.update(evidence_updates or {})
        run.update(run_updates or {})
        evidence_file = tmp_path / "validation-evidence.json"
        run_file = tmp_path / "validation-run.json"
        evidence_file.write_text(json.dumps(evidence))
        run_file.write_text(json.dumps(run))
        evidence_sha = hashlib.sha256(evidence_file.read_bytes()).hexdigest()
        evidence_prefix = "packer-validation/987654321/12345/2"
        binding = {
            "candidate_project": "dev-project",
            "candidate_image": "shifter-example-stack-123",
            "candidate_image_id": "987654321",
            "image_family": "shifter-example-stack",
            "image_type": "example-stack",
            "source_revision": "a" * 40,
            "evidence_sha256": evidence_sha,
        }
        binding_bytes = (json.dumps(binding, sort_keys=True, separators=(",", ":")) + "\n").encode()
        verdict = {
            "schema_version": 2,
            "source_sha": "a" * 40,
            "image_type": "example-stack",
            "result": "passed",
            "evidence_locator": hashlib.sha256(evidence_prefix.encode()).hexdigest(),
            "evidence_sha256": evidence_sha,
            "candidate_binding_sha256": hashlib.sha256(binding_bytes).hexdigest(),
        }
        artifact = {
            "id": 67890,
            "name": "example-stack-gce-validation-verdict",
            "expired": False,
            "workflow_run": {"id": 12345},
        }
        verdict.update(verdict_updates or {})
        artifact.update(artifact_updates or {})
        verdict_file = tmp_path / "validation-verdict.json"
        artifact_file = tmp_path / "validation-verdict-artifact.json"
        verdict_file.write_text(json.dumps(verdict))
        artifact_file.write_text(json.dumps(artifact))
        files = {
            "evidence": evidence_file,
            "guest_sbom": guest_sbom_file,
            "run": run_file,
            "verdict": verdict_file,
            "artifact": artifact_file,
        }
        if omit_file is not None:
            files[omit_file].unlink()
        env = dict(os.environ)
        env.update(
            {
                "SRC_IMAGE": "shifter-example-stack-123",
                "SRC_PROJECT": "dev-project",
                "IMAGE_FAMILY": "shifter-example-stack",
                "IMAGE_TYPE": "example-stack",
                "SRC_IMAGE_ID": "987654321",
                "VALIDATED_RUN": "12345",
                "VALIDATED_RUN_ATTEMPT": "2",
                "VALIDATED_VERDICT_ID": "67890",
                "VALIDATED_EVIDENCE_SHA": evidence_sha[:63],
                "VALIDATED_REVISION": "a" * 40,
                "EXPECTED_REPOSITORY": "Brad-Edwards/shifter",
                "EVIDENCE_FILE": str(evidence_file),
                "GUEST_SBOM_FILE": str(guest_sbom_file),
                "VERDICT_FILE": str(verdict_file),
                "RUN_FILE": str(run_file),
                "ARTIFACT_FILE": str(artifact_file),
            }
        )
        env.update(env_updates or {})
        if unset_env is not None:
            env.pop(unset_env, None)
        bash_path = shutil.which("bash")
        assert bash_path is not None
        return subprocess.run(  # noqa: S603
            [bash_path, str(GCP_SCRIPTS_DIR / "validate" / "verify-promotion-evidence.sh")],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_verifier_accepts_exact_successful_protected_run_evidence(self, tmp_path):
        result = self._run_verifier(tmp_path)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        ("evidence_updates", "run_updates"),
        [
            ({"candidate_image": "other-image"}, None),
            ({"project": "other-project"}, None),
            ({"result": "failed"}, None),
            ({"schema_version": 2}, None),
            ({"candidate_image_id": "123"}, None),
            ({"validation_run_attempt": 1}, None),
            ({"source_ref": "refs/heads/feature"}, None),
            ({"environment": "proof"}, None),
            ({"image_family": "other-family"}, None),
            ({"image_type": "other-type"}, None),
            ({"phases": ["first_boot_health"]}, None),
            ({"guest_sbom_sha256": "0" * 64}, None),
            ({"guest_sbom_format": "unknown"}, None),
            ({"guest_sbom_collection": "in-guest"}, None),
            ({"guest_sbom_source_image_id": "123"}, None),
            ({"guest_sbom_scanner_image_id": "not-numeric"}, None),
            ({"validated_at_utc": "2026-09-06T12:00:00Z"}, None),
            ({"workflow": ".github/workflows/other.yml"}, None),
            ({"repository": "other/repository"}, None),
            (None, {"id": 99999}),
            (None, {"run_attempt": 3}),
            (None, {"name": "Other workflow"}),
            (None, {"head_branch": "feature"}),
            (None, {"head_sha": "b" * 40}),
            (None, {"conclusion": "failure"}),
            (None, {"path": ".github/workflows/other.yml"}),
        ],
    )
    def test_verifier_rejects_mismatched_or_untrusted_evidence(self, tmp_path, evidence_updates, run_updates):
        result = self._run_verifier(tmp_path, evidence_updates=evidence_updates, run_updates=run_updates)
        assert result.returncode != 0

    def test_verifier_rejects_wrong_private_evidence_digest(self, tmp_path):
        result = self._run_verifier(tmp_path, env_updates={"VALIDATED_EVIDENCE_SHA": "0" * 63})
        assert result.returncode != 0

    @pytest.mark.parametrize(
        "verdict_updates",
        [
            {"schema_version": 1},
            {"source_sha": "b" * 40},
            {"image_type": "other-type"},
            {"result": "failed"},
            {"evidence_locator": "0" * 64},
            {"evidence_sha256": "0" * 64},
            {"candidate_binding_sha256": "0" * 64},
        ],
    )
    def test_verifier_rejects_forged_or_reused_verdict(self, tmp_path, verdict_updates):
        result = self._run_verifier(tmp_path, verdict_updates=verdict_updates)
        assert result.returncode != 0

    @pytest.mark.parametrize(
        "artifact_updates",
        [
            {"id": 99999},
            {"name": "other-artifact"},
            {"expired": True},
            {"workflow_run": {"id": 99999}},
        ],
    )
    def test_verifier_rejects_untrusted_verdict_artifact(self, tmp_path, artifact_updates):
        result = self._run_verifier(tmp_path, artifact_updates=artifact_updates)
        assert result.returncode != 0

    @pytest.mark.parametrize("omit_file", ["evidence", "guest_sbom", "run", "verdict", "artifact"])
    def test_verifier_rejects_missing_input_files(self, tmp_path, omit_file):
        result = self._run_verifier(tmp_path, omit_file=omit_file)
        assert result.returncode != 0

    def test_verifier_rejects_unset_required_environment_value(self, tmp_path):
        result = self._run_verifier(tmp_path, unset_env="SRC_IMAGE")
        assert result.returncode != 0
        assert "SRC_IMAGE is required" in result.stderr

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("SRC_IMAGE_ID", "not-numeric"),
            ("VALIDATED_RUN", "run-123"),
            ("VALIDATED_RUN_ATTEMPT", "attempt-2"),
            ("VALIDATED_VERDICT_ID", "artifact-67890"),
            ("VALIDATED_EVIDENCE_SHA", "not-a-digest"),
            ("VALIDATED_REVISION", "ABC123"),
        ],
    )
    def test_verifier_rejects_malformed_required_identifiers(self, tmp_path, name, value):
        result = self._run_verifier(tmp_path, env_updates={name: value})
        assert result.returncode != 0


class TestGcpPurposeIdentityWorkflows:
    """Every credentialed GCP caller selects one literal purpose identity."""

    @pytest.mark.parametrize(
        ("workflow_name", "environment_marker", "secret_name"),
        [
            ("packer-gcp.yml", "gcp-build-", "GCP_PACKER_BUILD_SERVICE_ACCOUNT"),
            ("packer-gcp-validate.yml", "gcp-validate-", "GCP_PACKER_VALIDATE_SERVICE_ACCOUNT"),
            ("packer-gcp-promote.yml", "gcp-promote-prod", "GCP_PACKER_PROMOTE_SERVICE_ACCOUNT"),
            # The destroy workflow is parameterized over the tenant, so its
            # purpose Environment is the per-tenant `<environment>-destroy`
            # (resolved from the dispatch input), not a single literal.
            ("gcp-dev-destroy.yml", "${{ inputs.environment }}-destroy", "GCP_DESTROY_SERVICE_ACCOUNT"),
        ],
    )
    def test_direct_workflow_uses_purpose_environment_and_secret(self, workflow_name, environment_marker, secret_name):
        workflow = (WORKFLOWS_DIR / workflow_name).read_text()
        assert environment_marker in workflow
        assert secret_name in workflow
        assert "secrets.GCP_SERVICE_ACCOUNT" not in workflow

    def test_reusable_deploy_and_caller_use_deploy_identity(self):
        reusable = (WORKFLOWS_DIR / "_gcp-dev.yml").read_text()
        caller = (WORKFLOWS_DIR / "deploy.yml").read_text()
        for workflow in (reusable, caller):
            assert "GCP_DEPLOY_SERVICE_ACCOUNT" in workflow
            assert "secrets.GCP_SERVICE_ACCOUNT" not in workflow
        assert "vars.GCP_SERVICE_ACCOUNT" in reusable
        assert "vars.GCP_WIF_PROVIDER" in reusable

    def test_reusable_release_scan_uses_its_narrow_identity(self):
        reusable = (WORKFLOWS_DIR / "_gcp-dev.yml").read_text()
        caller = (WORKFLOWS_DIR / "deploy.yml").read_text()
        for workflow in (reusable, caller):
            assert "GCP_RELEASE_SCAN_SERVICE_ACCOUNT" in workflow
        assert "environment: ${{ inputs.release_scan_github_environment }}" in reusable
        assert (
            "release_scan_github_environment: "
            "${{ needs.changes.outputs.gcp_release_scan_github_environment }}" in caller
        )
        assert "vars.GCP_SERVICE_ACCOUNT" in reusable
        assert "vars.GCP_WIF_PROVIDER" in reusable
        assert "needs: [validate, prepare, release_scan]" in reusable
        assert "TRIVY_ARCHIVE_SHA256" in reusable

    def test_builder_has_no_selectable_guest_identity_fallback(self):
        build = (WORKFLOWS_DIR / "packer-gcp.yml").read_text()
        assert "GCP_PACKER_SERVICE_ACCOUNT" not in build
        assert "GCP_SERVICE_ACCOUNT" not in build

    def test_destroy_rejects_unprotected_ref_before_auth(self):
        destroy = (WORKFLOWS_DIR / "gcp-dev-destroy.yml").read_text()
        guard = destroy.index("Reject non-protected dispatch refs")
        auth = destroy.index("google-github-actions/auth@")
        assert "refs/heads/dev|refs/heads/main" in destroy
        assert guard < auth

    def test_identity_split_preserves_existing_state_addresses(self):
        module = (REPO_ROOT / "platform/terraform/gcp/modules/cicd-oidc-identity/main.tf").read_text()
        assert 'resource "google_iam_workload_identity_pool_provider" "github"' in module
        assert 'resource "google_service_account" "packer_build"' in module
        packer_block = module.split('resource "google_service_account" "packer_build"', 1)[1].split("}\n", 1)[0]
        assert re.search(r"^\s*count\s*=", packer_block, re.MULTILINE) is None
        assert "github_gcp_dev" not in module

    def test_no_sa_validator_has_dedicated_iap_firewall_target(self):
        workflow = (WORKFLOWS_DIR / "packer-gcp-validate.yml").read_text()
        infrastructure = (REPO_ROOT / "platform/terraform/gcp/modules/packer-build-infra/main.tf").read_text()
        assert "--no-service-account --no-scopes" in workflow
        assert "--tags=shifter-validation" in workflow
        assert 'resource "google_compute_firewall" "validation_iap_ingress"' in infrastructure
        assert "target_tags   = [var.validation_network_tag]" in infrastructure
        assert 'source_ranges = ["35.235.240.0/20"]' in infrastructure

    def test_bucket_access_is_terraform_owned(self):
        identity = (REPO_ROOT / "platform/terraform/gcp/modules/cicd-oidc-identity/main.tf").read_text()
        deploy = (WORKFLOWS_DIR / "_gcp-dev.yml").read_text()
        assert 'resource "google_storage_bucket_iam_member" "packer_build_reader"' in identity
        assert 'resource "google_storage_bucket_iam_member" "deploy_state_object_admin"' in identity
        assert 'resource "google_storage_bucket_iam_member" "destroy_state_object_admin"' in identity
        assert '--member="serviceAccount:${GCP_DEPLOY_SERVICE_ACCOUNT}"' not in deploy

    def test_validator_checks_free_form_image_name_before_candidate_lookup(self):
        validate = (WORKFLOWS_DIR / "packer-gcp-validate.yml").read_text()
        syntax_check = validate.index("Candidate image name must be a valid GCE image resource name")
        describe = validate.index('gcloud compute images describe "${CANDIDATE}"')
        assert syntax_check < describe


class TestGcpValidationWorkflow:
    """A candidate-boot validation gate exists and boots an isolated VM (#1343 gap 2)."""

    @pytest.fixture
    def workflow(self):
        return (WORKFLOWS_DIR / "packer-gcp-validate.yml").read_text()

    def test_validate_workflow_exists(self):
        assert (WORKFLOWS_DIR / "packer-gcp-validate.yml").exists()

    def test_validation_scripts_exist(self):
        assert (GCP_SCRIPTS_DIR / "validate" / "linux.sh").exists()
        assert (GCP_SCRIPTS_DIR / "validate" / "dc-probe.sh").exists()
        assert (GCP_SCRIPTS_DIR / "validate" / "gather-evidence.sh").exists()
        # The guest self-report script is removed; evidence is runner-gathered.
        assert not (GCP_SCRIPTS_DIR / "validate" / "dc.ps1").exists()

    def test_validation_vm_has_no_external_ip(self, workflow):
        assert "--no-address" in workflow

    def test_validation_vm_is_shielded(self, workflow):
        assert "--shielded-secure-boot" in workflow
        assert "--shielded-vtpm" in workflow
        assert "--shielded-integrity-monitoring" in workflow

    def test_validation_vm_blocks_project_ssh_keys(self, workflow):
        assert "block-project-ssh-keys=TRUE" in workflow

    def test_validation_reboots_and_rechecks(self, workflow):
        assert "instances reset" in workflow

    def test_validation_labels_the_candidate(self, workflow):
        assert "validated=passed" in workflow

    def test_validation_pins_exact_candidate(self, workflow):
        # The candidate is resolved once and pinned; downstream uses the exact
        # name, and an explicit source_image input skips family resolution.
        assert "source_image" in workflow

    def test_binds_candidate_family_to_selected_profile(self, workflow):
        # The candidate's own family must equal the family for the requested
        # image_type, so a weak profile cannot validate a sensitive-family image.
        assert '"${IMG_FAMILY}" != "${FAMILY}"' in workflow

    def test_matrix_excludes_first_boot_dc_and_sysprepped_windows(self, workflow):
        # Only image types with a matching validator are selectable; the
        # sysprepped `windows` and first-boot-promotion `dc` images are excluded.
        assert "\n          - windows\n" not in workflow
        assert "\n          - dc\n" not in workflow
        assert "\n          - dc-prebaked\n" in workflow

    def test_validation_vm_has_no_guest_service_account(self, workflow):
        # The VM boots candidate code, so it must have no cloud identity — guest
        # code cannot read a token and mutate its own image label.
        assert "--no-service-account --no-scopes" in workflow
        assert '--service-account="${BUILD_SA}"' not in workflow

    def test_dc_validation_binds_domain_from_checked_in_profile(self, workflow):
        # The expected forest domain is resolved from the checked-in profile
        # (the allowlist); an unknown profile / empty domain is rejected, and the
        # profile is a strict slug (no path traversal).
        assert "dc-profiles/${DC_PROFILE}.pkrvars.hcl" in workflow
        assert "dc_domain_name" in workflow
        assert "^[a-z0-9][a-z0-9-]*$" in workflow

    def test_validation_cleans_up_the_vm(self, workflow):
        assert "instances delete" in workflow
        assert "if: always()" in workflow

    def test_evidence_gathered_by_runner_not_guest(self, workflow):
        # The runner executes the checks over IAP and gates on the result; there
        # is no guest-emitted serial sentinel trusted as the pass signal.
        assert "gather-evidence.sh" in workflow
        assert "SHIFTER_VALIDATION_RESULT" not in workflow
        assert "get-serial-port-output" not in workflow
        linux = (GCP_SCRIPTS_DIR / "validate" / "linux.sh").read_text()
        assert "SHIFTER_VALIDATION_RESULT" not in linux

    def test_gather_evidence_uses_iap_tunnel_and_exit_code(self):
        g = (GCP_SCRIPTS_DIR / "validate" / "gather-evidence.sh").read_text()
        assert "start-iap-tunnel" in g
        # Linux is SSH-exec'd; the DC is probed over LDAP; both gate on exit code.
        assert "ssh " in g
        assert "dc-probe.sh" in g

    def test_linux_validation_checks_guest_health_by_exit_code(self):
        linux = (GCP_SCRIPTS_DIR / "validate" / "linux.sh").read_text()
        assert "google-guest-agent" in linux
        # Exits non-zero on failure so the runner gates on the exit code.
        assert "exit 1" in linux
        assert "exit 0" in linux

    def test_dc_probe_reads_ad_without_promoting(self):
        probe = (GCP_SCRIPTS_DIR / "validate" / "dc-probe.sh").read_text()
        # Runner-side AD probe: an anonymous rootDSE query proves a serving
        # forest; it must never promote one, and it must require a specific
        # expected domain (no unbound "any DC" pass).
        assert "ldapsearch" in probe
        assert "defaultNamingContext" in probe
        assert "Install-ADDSForest" not in probe
        assert 'EXPECTED_DOMAIN}" ]] || fail' in probe

    def test_dc_evidence_loop_has_no_false_pass(self):
        # In the DC branch, rc must default non-zero and be set 0 ONLY on a real
        # probe success — never read $? after the if-compound (bash returns 0 when
        # no branch runs, which would turn an all-failed loop into a false pass).
        g = (GCP_SCRIPTS_DIR / "validate" / "gather-evidence.sh").read_text()
        dc_section = g.split("# Linux: SSH-execute", 1)[0]
        assert "rc=$?" not in dc_section
        assert "rc=1" in dc_section


class TestGcpPromoteEvidenceDriven:
    """Promotion copies the exact validated candidate, not newest-in-family (#1343 gaps 3/4)."""

    @pytest.fixture
    def promote(self):
        return (WORKFLOWS_DIR / "packer-gcp-promote.yml").read_text()

    def test_requires_exact_source_image_input(self, promote):
        assert "source_image:" in promote
        assert "SRC_IMAGE: ${{ inputs.source_image }}" in promote

    def test_verifies_validation_label_before_promotion(self, promote):
        assert "labels.validated" in promote
        assert '"${VALIDATED}" != "passed"' in promote

    def test_copies_the_exact_candidate(self, promote):
        assert '--source-image="${SRC_IMAGE}"' in promote

    def test_does_not_resolve_source_from_family(self, promote):
        # The dev-side source must be the pinned candidate, never re-resolved to
        # newest-in-family at promotion time (the TOCTOU gap).
        assert "SRC_IMAGE=$(gcloud compute images describe-from-family" not in promote
        assert 'SRC_IMAGE="$(gcloud compute images describe-from-family' not in promote
        # describe-from-family survives ONLY to read the prod head for deprecation.
        assert 'PREV_PROD_IMAGE="$(gcloud compute images describe-from-family' in promote

    def test_verifies_new_prod_image_before_deprecating_old_head(self, promote):
        assert "NEW_STATUS" in promote
        assert "deprecate" in promote

    def test_derives_family_from_image_for_example_and_dc(self, promote):
        # Family comes from the image's own family attribute, so example-stack and
        # purpose-scoped <purpose>-dc families need no per-name logic.
        assert "value(family)" in promote


class TestGcpDcPrebakedCredentialHygiene:
    """The pre-promoted DC ships no baked credential/transcript (#1343 gaps 5/6)."""

    def test_promote_bake_has_no_committed_dsrm_default(self):
        content = (GCP_SCRIPTS_DIR / "dc-prebaked" / "promote-bake.ps1").read_text()
        assert "DsrmR3store" not in content
        assert 'DsrmPassword = "' not in content
        assert "DC_DSRM_PASSWORD" in content

    def test_variables_declare_sensitive_dsrm(self):
        content = (GCP_DIR / "variables.pkr.hcl").read_text()
        assert 'variable "dc_dsrm_password"' in content
        # Must be marked sensitive so packer never prints it.
        block = content.split('variable "dc_dsrm_password"', 1)[1].split("}", 1)[0]
        assert "sensitive   = true" in block

    def test_finalize_strips_transcripts_and_seed_in_session(self):
        # Cleanup runs inside finalize.ps1's still-authenticated session (the
        # content seed resets the Administrator password, so a later provisioner
        # could not reconnect). Verify finalize strips the secret-bearing seed +
        # transcripts, and there is no separate cleanup provisioner to re-auth.
        content = (GCP_SCRIPTS_DIR / "dc-prebaked" / "finalize.ps1").read_text()
        assert "dc-prebaked-promote-bake.log" in content
        assert "dc-prebaked-finalize.log" in content
        assert 'Remove-Item -Path "C:\\shifter-build\\content-seed.ps1"' in content
        assert not (GCP_SCRIPTS_DIR / "dc-prebaked" / "cleanup.ps1").exists()

    def test_dc_prebaked_finalize_is_last_and_injects_dsrm(self):
        content = (GCP_DIR / "dc-prebaked.pkr.hcl").read_text()
        assert "DC_DSRM_PASSWORD=${var.dc_dsrm_password}" in content
        # finalize (which now also cleans up) is the last provisioner before the
        # manifest post-processor; no separate cleanup provisioner follows it.
        assert "scripts/dc-prebaked/cleanup.ps1" not in content
        assert content.index("finalize.ps1") < content.index("post-processor")

    def test_finalize_does_not_mutate_firewall_across_its_winrm_session(self):
        content = (GCP_SCRIPTS_DIR / "dc-prebaked" / "finalize.ps1").read_text()
        assert "Set-NetFirewallProfile" not in content
        assert "Get-NetFirewallProfile" in content
        assert "enabledFirewallProfiles.Count -ne 0" in content

    def test_finalize_accepts_password_rotation_task_status(self):
        content = (GCP_DIR / "dc-prebaked.pkr.hcl").read_text()
        finalize_block = content.split('"scripts/dc-prebaked/finalize.ps1"', 1)[0].rsplit(
            'provisioner "powershell"', 1
        )[1]
        assert "valid_exit_codes = [0, 16001]" in finalize_block


class TestAwsTemplatesUnaffected:
    """AC3 guard: the GCE templates must not leak into the AWS template set."""

    def test_aws_dir_has_no_googlecompute(self):
        for template in PACKER_DIR.glob("*.pkr.hcl"):
            content = template.read_text()
            assert "googlecompute" not in content, (
                f"AWS template {template.name} must not contain a googlecompute source — GCE builders live in gcp/"
            )


class TestLinuxCandidateValidation:
    @pytest.mark.parametrize(
        ("image_type", "agent_active", "accepted"),
        [
            ("ubuntu", True, True),
            ("kali", True, True),
            ("brokenbk", True, True),
            ("ubuntu", False, False),
            ("", True, False),
            ("unknown", True, False),
        ],
    )
    def test_candidate_health(self, tmp_path, image_type, agent_active, accepted):
        systemctl = tmp_path / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit " + ("0" if agent_active else "1") + "\n")
        systemctl.chmod(0o755)
        result = subprocess.run(  # noqa: S603
            ["/bin/bash", str(GCP_SCRIPTS_DIR / "validate" / "linux.sh")],
            env={**os.environ, "PATH": str(tmp_path), "VALIDATE_IMAGE_TYPE": image_type},
            capture_output=True,
            text=True,
            check=False,
        )
        assert (result.returncode == 0) is accepted
        assert ("PASS" in result.stdout) is accepted
