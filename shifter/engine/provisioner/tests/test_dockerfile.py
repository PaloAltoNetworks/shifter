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

    def test_chowns_app_directory_to_appuser(self):
        # COPY --chown only sets ownership of files copied INTO /app — the
        # /app directory itself, created by WORKDIR, stays root-owned unless
        # we explicitly chown it. Both must be in place: the directory is
        # writable for the runtime user, AND copied content is owned by it.
        content = _read_dockerfile()
        assert re.search(
            r"chown\s+(-R\s+)?appuser:appgroup\s+/app\b",
            content,
        ), "Dockerfile must explicitly chown /app to appuser:appgroup (WORKDIR creates it root-owned)"
        assert re.search(
            r"COPY\s+--chown=appuser:appgroup",
            content,
        ), "Dockerfile must use COPY --chown=appuser:appgroup so copied files belong to the runtime user"

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
            "/app",
        ],
        ids=["terraform_plugin_cache", "pulumi_home", "app_workspace"],
    )
    def test_runtime_path_writable(self, built_image, path):
        # Each path must be writable by the non-root runtime user:
        # - terraform plugin cache: Terraform downloads providers here
        # - pulumi home: Pulumi state/config
        # - /app: Terraform writes terraform.tfvars.json + .terraform/ into
        #   module working dirs under /app (per terraform_base.apply).
        # The helper's internal assert raises if the touch/rm fails.
        self._docker_run(
            built_image,
            ["sh", "-c", f"touch {path}/.write-probe && rm {path}/.write-probe"],
        )

    def test_tool_env_vars_set(self, built_image):
        env_dump = self._docker_run(built_image, ["env"])
        assert "TF_PLUGIN_CACHE_DIR=/home/appuser/.terraform.d/plugin-cache" in env_dump
        assert "PULUMI_HOME=/home/appuser/.pulumi" in env_dump
