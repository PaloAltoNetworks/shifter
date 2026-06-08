"""Structural and runtime tests for the provisioner Dockerfile.

The structural tests are the fast feedback loop: they parse the Dockerfile
text and guard against the issue #950 regression (running as root).

The runtime smoke test (`TestDockerfileRuntimeSmoke`) opts in via the
`RUN_DOCKER_TESTS=1` environment variable. It builds the image and verifies
the actual UID/HOME/cache directories — closing the gap between "Dockerfile
declares non-root" and "the running container is non-root". Default pytest
runs (and pre-commit) skip it; CI's `_gcp-dev.yml` build step is the
canonical production gate that exercises the real build.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

DOCKERFILE_PATH = Path(__file__).resolve().parent.parent / "Dockerfile"
PROVISIONER_DIR = DOCKERFILE_PATH.parent
TERRAFORM_RC_PATH = PROVISIONER_DIR / "terraform.tfrc"


def _read_dockerfile() -> str:
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


class TestDockerfileNonRootUser:
    def test_dockerfile_exists(self):
        assert DOCKERFILE_PATH.is_file(), f"Dockerfile not found at {DOCKERFILE_PATH}"

    def test_creates_appgroup_with_gid_1000(self):
        content = _read_dockerfile()
        assert re.search(
            r"groupadd[^\n]*--gid\s+1000[^\n]*appgroup",
            content,
        ), "Dockerfile must create appgroup with --gid 1000"

    def test_creates_appuser_with_uid_1000(self):
        content = _read_dockerfile()
        assert re.search(
            r"useradd[^\n]*--uid\s+1000[^\n]*appuser",
            content,
        ), "Dockerfile must create appuser with --uid 1000"

    def test_switches_to_non_root_user_before_entrypoint(self):
        # Numeric UID:GID is required so Kubernetes admission with
        # `runAsNonRoot: true` can verify the runtime user is non-root
        # without resolving names from /etc/passwd.
        content = _read_dockerfile()
        lines = content.splitlines()

        user_line_indices = [i for i, line in enumerate(lines) if re.match(r"\s*USER\s+1000:1000\b", line)]
        assert user_line_indices, "Dockerfile must include `USER 1000:1000` directive"

        entrypoint_indices = [i for i, line in enumerate(lines) if re.match(r"\s*ENTRYPOINT\b", line)]
        assert entrypoint_indices, "Dockerfile must declare an ENTRYPOINT"

        last_user_index = user_line_indices[-1]
        first_entrypoint_index = entrypoint_indices[0]
        assert last_user_index < first_entrypoint_index, (
            "USER 1000:1000 must appear before ENTRYPOINT so the runtime process drops privileges"
        )

    def test_last_user_directive_is_numeric_non_root(self):
        # The LAST USER directive is what the runtime sees. It must be the
        # numeric `1000:1000` form so Kubernetes `runAsNonRoot: true`
        # admission can verify it without resolving names. A later
        # `USER appuser` (let alone `USER root`) would silently break the
        # admission-controller guarantee even though the image runs as
        # non-root in spirit.
        content = _read_dockerfile()
        lines = content.splitlines()
        user_directives = [(i, line.strip()) for i, line in enumerate(lines) if re.match(r"\s*USER\s+\S+", line)]
        assert user_directives, "Dockerfile must contain a USER directive"
        last_index, last_directive = user_directives[-1]
        token = last_directive.split()[1]
        assert token == "1000:1000", (
            f"Last USER directive must be `USER 1000:1000` (numeric form for "
            f"k8s runAsNonRoot admission); got `{last_directive}` at line {last_index + 1}"
        )

    def test_app_stays_immutable_image_content(self):
        # Issue #1103: /app must NOT be writable by the runtime user. The
        # provisioner Job mounts the runtime root read-only, and Terraform
        # writes go to a dedicated workspace volume (TERRAFORM_WORKSPACE_DIR)
        # — not into /app. Chowning /app to appuser or copying source with
        # --chown=appuser would re-introduce the writable-application-code
        # surface that #950's review (cycle 2) flagged.
        content = _read_dockerfile()
        assert not re.search(
            r"chown\s+(-R\s+)?appuser:appgroup\s+/app\b",
            content,
        ), "Dockerfile MUST NOT chown /app to appuser:appgroup (issue #1103 — /app stays root-owned + immutable)"
        assert not re.search(
            r"COPY\s+--chown=appuser:appgroup",
            content,
        ), (
            "Dockerfile MUST NOT use COPY --chown=appuser:appgroup (issue #1103 — application code under "
            "/app stays root-owned so a compromised runtime cannot tamper with it)"
        )

    def test_declares_default_terraform_workspace_dir(self):
        # The runtime resolves the writable Terraform workspace path from
        # TERRAFORM_WORKSPACE_DIR (terraform_base._stage_workspace). Setting
        # the env var in the image documents the mount contract: any deployer
        # mounting an emptyDir / Fargate ephemeral volume must put it at this
        # path. The default matches terraform_base._DEFAULT_TERRAFORM_WORKSPACE_DIR.
        content = _read_dockerfile()
        assert re.search(
            r"\bTERRAFORM_WORKSPACE_DIR=/var/run/provisioner/workspace\b",
            content,
        ), "Dockerfile must set TERRAFORM_WORKSPACE_DIR=/var/run/provisioner/workspace"

    def test_creates_writable_workspace_mount_point(self):
        # The image must pre-create the workspace mount point and chown it to
        # appuser. When the runtime mounts an emptyDir there, the mount keeps
        # parent-directory ownership unless overridden — pre-chowning means
        # the runtime user can write the staging tree the moment the mount
        # is in place, even before the first Terraform run.
        content = _read_dockerfile()
        assert re.search(
            r"mkdir[^\n]*/var/run/provisioner/workspace\b",
            content,
        ), "Dockerfile must pre-create /var/run/provisioner/workspace"
        assert re.search(
            r"chown\s+(-R\s+)?appuser:appgroup\s+/var/run/provisioner\b",
            content,
        ), "Dockerfile must chown /var/run/provisioner to appuser:appgroup"

    def test_sets_home_for_non_root_user(self):
        # Docker's USER directive does NOT change HOME; Terraform/Pulumi
        # write plugin caches and config to $HOME, so HOME must be set
        # explicitly to a directory writable by appuser.
        content = _read_dockerfile()
        assert re.search(
            r"ENV\s+([A-Z_]+=\S+\s+)*HOME=/home/appuser\b",
            content,
        ) or re.search(
            r"ENV\s+HOME\s+/home/appuser\b",
            content,
        ), "Dockerfile must set HOME=/home/appuser so Terraform/Pulumi find a writable home"

    def test_creates_writable_tool_caches(self):
        # The runtime user needs writable Terraform/Pulumi cache directories
        # under HOME; they must exist and be appuser-owned at image build time.
        content = _read_dockerfile()
        assert re.search(
            r"mkdir[^\n]*/home/appuser/\.terraform\.d",
            content,
        ), "Dockerfile must pre-create /home/appuser/.terraform.d for Terraform plugin cache"
        assert re.search(
            r"mkdir[^\n]*/home/appuser/\.pulumi\b",
            content,
        ), "Dockerfile must pre-create /home/appuser/.pulumi for Pulumi state/config"
        assert re.search(
            r"chown\s+-R\s+appuser:appgroup\s+/home/appuser\b",
            content,
        ), "Dockerfile must chown /home/appuser recursively to appuser:appgroup"

    def test_sets_tool_home_env_vars(self):
        # TF_PLUGIN_CACHE_DIR and PULUMI_HOME must point at the pre-created
        # writable directories under /home/appuser. Without these env vars,
        # Terraform/Pulumi may default to paths outside HOME (or the wrong
        # subdir under HOME) and fail to write under the non-root identity.
        content = _read_dockerfile()
        assert re.search(
            r"\bTF_PLUGIN_CACHE_DIR=/home/appuser/\.terraform\.d/plugin-cache\b",
            content,
        ), "Dockerfile must set TF_PLUGIN_CACHE_DIR=/home/appuser/.terraform.d/plugin-cache"
        assert re.search(
            r"\bPULUMI_HOME=/home/appuser/\.pulumi\b",
            content,
        ), "Dockerfile must set PULUMI_HOME=/home/appuser/.pulumi"

    def test_tool_downloads_retry_transient_failures(self):
        content = _read_dockerfile()
        assert content.count("--retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20") >= 2

    def test_bakes_terraform_provider_mirror(self):
        content = _read_dockerfile()
        assert "terraform -chdir=terraform/modules/range providers mirror /opt/terraform-providers" in content
        assert "terraform -chdir=terraform/modules/ngfw providers mirror /opt/terraform-providers" in content

    def test_sets_terraform_cli_config_file(self):
        content = _read_dockerfile()
        assert "TF_CLI_CONFIG_FILE=/app/terraform.tfrc" in content

    def test_terraform_cli_config_uses_only_filesystem_mirror_for_hashicorp(self):
        content = TERRAFORM_RC_PATH.read_text(encoding="utf-8")
        assert 'path    = "/opt/terraform-providers"' in content
        assert 'include = ["registry.terraform.io/hashicorp/*"]' in content
        assert 'exclude = ["registry.terraform.io/hashicorp/*"]' in content


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_TESTS") != "1",
    reason="Set RUN_DOCKER_TESTS=1 to opt into Docker build smoke tests",
)
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
class TestDockerfileRuntimeSmoke:
    """Build the provisioner image and verify the runtime contract.

    These tests close the gap between "Dockerfile text says non-root" and
    "the running container is actually non-root with writable HOME and tool
    caches." They are slow (full image build, ~3-5 minutes) so they're
    opt-in via `RUN_DOCKER_TESTS=1`.
    """

    IMAGE_TAG = "shifter-provisioner-test:dockerfile-smoke"

    @staticmethod
    def _docker_bin() -> str:
        # Resolving via shutil.which avoids ruff S607 (partial-path) and lets
        # the skipif marker on the class catch the docker-not-installed case.
        path = shutil.which("docker")
        assert path is not None, "docker CLI must be present (skipif should have caught this)"
        return path

    @pytest.fixture(scope="class")
    def built_image(self):
        docker = self._docker_bin()
        result = subprocess.run(  # noqa: S603 — absolute docker path, list args, no shell
            [docker, "build", "-t", self.IMAGE_TAG, "."],
            cwd=PROVISIONER_DIR,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if result.returncode != 0:
            pytest.fail(f"docker build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        yield self.IMAGE_TAG
        subprocess.run(  # noqa: S603 — absolute docker path, list args, no shell
            [docker, "rmi", "-f", self.IMAGE_TAG],
            capture_output=True,
            check=False,
        )

    def _docker_run(self, image: str, command: list[str]) -> str:
        docker = self._docker_bin()
        result = subprocess.run(  # noqa: S603 — absolute docker path, list args, no shell
            [docker, "run", "--rm", "--entrypoint", command[0], image, *command[1:]],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, (
            f"docker run {command} failed (exit {result.returncode}): stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        return result.stdout

    @pytest.mark.parametrize(
        ("flag", "expected"),
        [("-u", "1000"), ("-g", "1000")],
    )
    def test_runs_with_correct_id(self, built_image, flag, expected):
        # Both UID and GID must be 1000 so Kubernetes runAsNonRoot admission
        # accepts the pod and the runtime can chown into appuser-owned dirs.
        assert self._docker_run(built_image, ["id", flag]).strip() == expected

    def test_home_is_writable(self, built_image):
        # Ensure $HOME is set to /home/appuser AND is writable under the
        # runtime user (Terraform/Pulumi caches depend on this).
        home = self._docker_run(built_image, ["sh", "-c", "echo $HOME"]).strip()
        assert home == "/home/appuser"
        # If this fails, the runtime user cannot write to its own HOME.
        self._docker_run(built_image, ["sh", "-c", "touch $HOME/.write-probe && rm $HOME/.write-probe"])

    @pytest.mark.parametrize(
        "path",
        [
            "/home/appuser/.terraform.d/plugin-cache",
            "/home/appuser/.pulumi",
            "/var/run/provisioner/workspace",
        ],
        ids=["terraform_plugin_cache", "pulumi_home", "terraform_workspace"],
    )
    def test_runtime_path_writable(self, built_image, path):
        # Each path must be writable by the non-root runtime user:
        # - terraform plugin cache: Terraform downloads providers here
        # - pulumi home: Pulumi state/config
        # - terraform workspace: terraform_base._stage_workspace copies the
        #   read-only module source from /app/terraform/modules/<name> here
        #   per request, then runs terraform init/apply/destroy from the
        #   staged path so /app stays read-only (issue #1103).
        # The helper's internal assert raises if the touch/rm fails.
        self._docker_run(
            built_image,
            ["sh", "-c", f"touch {path}/.write-probe && rm {path}/.write-probe"],
        )

    def test_app_is_not_writable_when_root_filesystem_is_readonly(self, built_image):
        # Simulates the production runtime contract: --read-only on the
        # container root, with explicit tmpfs volumes for the workspace,
        # /tmp, and the tool caches under HOME. Under that contract /app
        # MUST refuse writes (it is image content) while the workspace
        # path MUST accept them. This is the live counterpart of the
        # structural test_app_stays_immutable_image_content gate.
        docker = self._docker_bin()
        workspace_path = "/var/run/provisioner/workspace"
        tmp_path = "/tmp"  # noqa: S108 — Docker tmpfs mount target, not a tempfile API call
        tf_cache_path = "/home/appuser/.terraform.d/plugin-cache"
        pulumi_path = "/home/appuser/.pulumi"
        tmpfs_args = [
            "--tmpfs",
            f"{workspace_path}:rw,uid=1000,gid=1000",
            "--tmpfs",
            f"{tmp_path}:rw,uid=1000,gid=1000",
            "--tmpfs",
            f"{tf_cache_path}:rw,uid=1000,gid=1000",
            "--tmpfs",
            f"{pulumi_path}:rw,uid=1000,gid=1000",
        ]

        # 1) Writes to /app fail under --read-only (expected non-zero exit).
        result = subprocess.run(  # noqa: S603 — absolute docker path, list args, no shell
            [
                docker,
                "run",
                "--rm",
                "--read-only",
                *tmpfs_args,
                "--entrypoint",
                "sh",
                built_image,
                "-c",
                "touch /app/.write-probe",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode != 0, (
            f"/app should be read-only under --read-only, but write succeeded: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        # 2) Writes to the workspace path succeed under the same contract.
        probe_cmd = f"touch {workspace_path}/.write-probe && rm {workspace_path}/.write-probe"
        result = subprocess.run(  # noqa: S603 — absolute docker path, list args, no shell
            [docker, "run", "--rm", "--read-only", *tmpfs_args, "--entrypoint", "sh", built_image, "-c", probe_cmd],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, (
            f"workspace path must be writable under --read-only with tmpfs mount: "
            f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_tool_env_vars_set(self, built_image):
        env_dump = self._docker_run(built_image, ["env"])
        assert "TF_PLUGIN_CACHE_DIR=/home/appuser/.terraform.d/plugin-cache" in env_dump
        assert "PULUMI_HOME=/home/appuser/.pulumi" in env_dump
        assert "TF_CLI_CONFIG_FILE=/app/terraform.tfrc" in env_dump
        assert "TERRAFORM_WORKSPACE_DIR=/var/run/provisioner/workspace" in env_dump
