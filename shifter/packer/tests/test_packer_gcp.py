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

    def test_kali_conversion_script_regenerates_ssh_host_keys(self):
        script = (PACKER_DIR / "scripts" / "kali" / "gce-debian-to-kali.sh").read_text()
        # cleanup.sh strips host keys; Kali (unlike Ubuntu) does not regenerate
        # them on first boot, so sshd never binds :22 and the range provisioner's
        # SSH-wait times out (#1745). The conversion must install a first-boot
        # oneshot that runs `ssh-keygen -A` before sshd.
        assert "regenerate-ssh-host-keys.service" in script
        assert "ssh-keygen -A" in script
        assert "systemctl enable regenerate-ssh-host-keys.service" in script


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


class TestGcpPolarisVerifyStackWiring:
    """The polaris-vm stack verify is wired into the template + vars (#1343 gap 1)."""

    def test_variables_declare_checksum_and_generation(self):
        content = (GCP_DIR / "variables.pkr.hcl").read_text()
        assert 'variable "polaris_stack_sha256"' in content
        assert 'variable "polaris_stack_generation"' in content

    def test_polaris_vm_template_requires_stack(self):
        content = (GCP_DIR / "polaris-vm.pkr.hcl").read_text()
        assert "POLARIS_REQUIRE_STACK=1" in content
        assert "POLARIS_STACK_SHA256=${var.polaris_stack_sha256}" in content
        assert "POLARIS_STACK_GENERATION=${var.polaris_stack_generation}" in content
        # host-setup installs docker/sdk; verify-stack (fail-closed) runs next.
        assert "scripts/polaris/verify-stack.sh" in content
        assert content.index("host-setup.sh") < content.index("verify-stack.sh")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
class TestGcpPolarisVerifyStackBehavior:
    """verify-stack.sh actually fails the build on each fail-closed condition.

    Executes the script with stubbed gcloud/docker so the fail-closed BRANCHES
    are exercised (not just asserted present) — #1343 test-quality review.
    """

    VERIFY_STACK = GCP_SCRIPTS_DIR / "polaris" / "verify-stack.sh"

    def _run(self, tmp_path, env, *, with_stub_bin=True, docker_ok=True, images="img:latest"):
        import os

        stub = tmp_path / "bin"
        stub.mkdir(exist_ok=True)
        if with_stub_bin:
            # gcloud stub writes deterministic tarball bytes to the cp destination
            # (last argv). The test sets POLARIS_STACK_SHA256 to that content hash.
            (stub / "gcloud").write_text('#!/bin/bash\ndest="${@: -1}"\nprintf polaris-stack-bytes > "$dest"\n')
            docker_rc = "0" if docker_ok else "1"
            # docker stub: `compose config --images` prints the image list; every
            # other subcommand (config/build/pull/image inspect) exits docker_rc.
            (stub / "docker").write_text(
                "#!/bin/bash\n"
                'if [ "$1" = "compose" ] && [ "$2" = "config" ] && [ "$3" = "--images" ]; then\n'
                f'  printf "%s\\n" {images}; exit 0\nfi\n'
                f"exit {docker_rc}\n"
            )
            for f in ("gcloud", "docker"):
                (stub / f).chmod(0o755)
        run_env = dict(os.environ)
        run_env["PATH"] = f"{stub}:{run_env['PATH']}"
        run_env["POLARIS_ROOT"] = str(tmp_path / "polaris")
        run_env["COMPOSE_DIR"] = str(tmp_path / "polaris" / "build")
        run_env.update(env)
        bash_path = shutil.which("bash")
        return subprocess.run(  # noqa: S603
            [bash_path, str(self.VERIFY_STACK)],
            capture_output=True,
            text=True,
            env=run_env,
        )

    def test_missing_bucket_when_required_fails(self, tmp_path):
        r = self._run(tmp_path, {"POLARIS_REQUIRE_STACK": "1", "POLARIS_STACK_BUCKET": ""})
        assert r.returncode != 0, r.stderr

    def test_missing_checksum_when_required_fails(self, tmp_path):
        r = self._run(tmp_path, {"POLARIS_REQUIRE_STACK": "1", "POLARIS_STACK_BUCKET": "b", "POLARIS_STACK_SHA256": ""})
        assert r.returncode != 0, r.stderr

    def test_checksum_mismatch_fails(self, tmp_path):
        r = self._run(
            tmp_path,
            {
                "POLARIS_REQUIRE_STACK": "1",
                "POLARIS_STACK_BUCKET": "b",
                "POLARIS_STACK_SHA256": "0" * 64,  # deliberately wrong
            },
        )
        assert r.returncode != 0, r.stderr

    def test_missing_stack_when_not_required_succeeds(self, tmp_path):
        r = self._run(tmp_path, {"POLARIS_REQUIRE_STACK": "0", "POLARIS_STACK_BUCKET": ""})
        assert r.returncode == 0, r.stderr

    @staticmethod
    def _stub_tar(tmp_path):
        # verify-stack.sh runs `tar xzf <file> -C <dir>`; the gcloud stub writes
        # raw bytes (not a real tar), so stub tar to drop a compose file in -C.
        stub = tmp_path / "bin"
        stub.mkdir(exist_ok=True)
        (stub / "tar").write_text(
            "#!/bin/bash\n"
            'd="";prev="";for a in "$@";do [ "$prev" = "-C" ] && d="$a";prev="$a";done\n'
            'printf "services: {}\\n" > "$d/docker-compose.yml"\n'
        )
        (stub / "tar").chmod(0o755)

    def test_valid_stack_passes(self, tmp_path):
        import hashlib

        # The gcloud stub writes these exact bytes; declare their real sha256.
        sha = hashlib.sha256(b"polaris-stack-bytes").hexdigest()
        self._stub_tar(tmp_path)
        r = self._run(
            tmp_path,
            {"POLARIS_REQUIRE_STACK": "1", "POLARIS_STACK_BUCKET": "b", "POLARIS_STACK_SHA256": sha},
            docker_ok=True,
        )
        assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"

    def test_failed_docker_step_fails(self, tmp_path):
        import hashlib

        # Even with a valid, checksum-matching stack, a failing docker step
        # (config/build/pull) must fail the build — no `|| true`.
        sha = hashlib.sha256(b"polaris-stack-bytes").hexdigest()
        self._stub_tar(tmp_path)
        r = self._run(
            tmp_path,
            {"POLARIS_REQUIRE_STACK": "1", "POLARIS_STACK_BUCKET": "b", "POLARIS_STACK_SHA256": sha},
            docker_ok=False,
        )
        assert r.returncode != 0, r.stdout


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
        assert "\n          - polaris-vm\n" in workflow

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

    def test_linux_validation_checks_stack_health_by_exit_code(self):
        linux = (GCP_SCRIPTS_DIR / "validate" / "linux.sh").read_text()
        assert "google-guest-agent" in linux
        assert "docker compose config --images" in linux
        # Exits non-zero on failure so the runner gates on the exit code.
        assert "exit 1" in linux and "exit 0" in linux

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

    def test_derives_family_from_image_for_polaris_and_dc(self, promote):
        # Family comes from the image's own family attribute, so polaris-vm and
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
        assert 'Remove-Item -Path "C:\\polaris\\a2_setup.ps1"' in content
        assert not (GCP_SCRIPTS_DIR / "dc-prebaked" / "cleanup.ps1").exists()

    def test_dc_prebaked_finalize_is_last_and_injects_dsrm(self):
        content = (GCP_DIR / "dc-prebaked.pkr.hcl").read_text()
        assert "DC_DSRM_PASSWORD=${var.dc_dsrm_password}" in content
        # finalize (which now also cleans up) is the last provisioner before the
        # manifest post-processor; no separate cleanup provisioner follows it.
        assert "scripts/dc-prebaked/cleanup.ps1" not in content
        assert content.index("finalize.ps1") < content.index("post-processor")


class TestAwsTemplatesUnaffected:
    """AC3 guard: the GCE templates must not leak into the AWS template set."""

    def test_aws_dir_has_no_googlecompute(self):
        for template in PACKER_DIR.glob("*.pkr.hcl"):
            content = template.read_text()
            assert "googlecompute" not in content, (
                f"AWS template {template.name} must not contain a googlecompute source — GCE builders live in gcp/"
            )
