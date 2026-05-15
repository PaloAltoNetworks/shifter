"""Tests for provider-aware Terraform backend helpers."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestBackendResolution:
    """Tests for Terraform backend selection and state key layout."""

    @patch.dict("os.environ", {}, clear=True)
    def test_get_backend_type_defaults_to_s3(self):
        from terraform_base import get_backend_type

        assert get_backend_type() == "s3"

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=True)
    def test_get_backend_type_uses_gcs_for_gcp(self):
        from terraform_base import get_backend_type

        assert get_backend_type() == "gcs"

    @patch.dict("os.environ", {"STATE_BUCKET_URL": "gs://shifter-gcp-dev-terraform-state"}, clear=True)
    def test_get_state_bucket_parses_gcs_backend_url(self):
        from terraform_base import get_state_bucket

        assert get_state_bucket() == "shifter-gcp-dev-terraform-state"

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=True)
    def test_get_state_key_uses_gcs_state_filename(self):
        from terraform_base import get_state_key

        assert get_state_key("gcp/gdc-ranges", "req-123") == "gcp/gdc-ranges/req-123/default.tfstate"


class TestWorkspaceInitialization:
    """Tests for backend-specific terraform init arguments.

    `apply()` runs init as its first step inside the staged workspace; these tests
    drive `apply()` and inspect the first run_terraform call (the init invocation).
    There is intentionally no public ``init_workspace`` entrypoint — its staged
    workspace is per-call and torn down before return, so initialization on its
    own has no usable post-condition for an external caller.
    """

    @patch.dict("os.environ", {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"}, clear=True)
    @patch("terraform_base.run_terraform")
    def test_init_uses_s3_backend_config(self, mock_run, tmp_path, monkeypatch):
        from terraform_base import apply

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(tmp_path / "workspace"))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        # First run_terraform call is `terraform init`; subsequent calls return empty
        # output JSON so apply() can finish without raising on the output parse.
        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        apply("ranges", "req-123", {}, source, "Range")

        init_args = mock_run.call_args_list[0].args[0]
        assert init_args[0] == "init"
        assert "-backend-config=bucket=shifter-dev-pulumi-state" in init_args
        assert "-backend-config=key=ranges/req-123/terraform.tfstate" in init_args
        assert "-backend-config=dynamodb_table=shifter-dev-pulumi-locks" in init_args
        assert not any(arg.startswith("-backend-config=prefix=") for arg in init_args)

    @patch.dict(
        "os.environ",
        {"TF_STATE_BUCKET": "dev-range-pulumi-state-788327019743"},
        clear=True,
    )
    @patch("terraform_base.run_terraform")
    def test_init_handles_account_id_suffixed_bucket(self, mock_run, tmp_path, monkeypatch):
        # Buckets created by the engine-state module post-3.95.6 carry an
        # account-id suffix to dodge the global S3 namespace collision.
        # The lock table name still strips at "-pulumi-state" → "-pulumi-locks".
        from terraform_base import apply

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(tmp_path / "workspace"))
        monkeypatch.setenv("TF_STATE_BUCKET", "dev-range-pulumi-state-788327019743")

        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        apply("ranges", "req-456", {}, source, "Range")

        init_args = mock_run.call_args_list[0].args[0]
        assert init_args[0] == "init"
        assert "-backend-config=bucket=dev-range-pulumi-state-788327019743" in init_args
        assert "-backend-config=dynamodb_table=dev-range-pulumi-locks" in init_args

    @patch.dict(
        "os.environ",
        {"CLOUD_PROVIDER": "gcp", "TF_STATE_BUCKET": "shifter-gcp-dev-terraform-state"},
        clear=True,
    )
    @patch("terraform_base.run_terraform")
    def test_init_uses_gcs_backend_config(self, mock_run, tmp_path, monkeypatch):
        from terraform_base import apply

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(tmp_path / "workspace"))
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-gcp-dev-terraform-state")

        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        apply("gcp/gdc-ranges", "req-123", {}, source, "Range")

        init_args = mock_run.call_args_list[0].args[0]
        assert init_args[0] == "init"
        assert "-backend-config=bucket=shifter-gcp-dev-terraform-state" in init_args
        assert "-backend-config=prefix=gcp/gdc-ranges/req-123" in init_args
        assert not any(arg.startswith("-backend-config=key=") for arg in init_args)
        assert not any("dynamodb_table=" in arg for arg in init_args)


class TestStateCleanup:
    """Tests for provider-aware cleanup behavior."""

    @patch.dict(
        "os.environ",
        {"CLOUD_PROVIDER": "gcp", "TF_STATE_BUCKET": "shifter-gcp-dev-terraform-state"},
        clear=True,
    )
    @patch("terraform_base.get_object_storage")
    def test_cleanup_state_skips_lock_cleanup_for_gcs(self, mock_get_storage):
        from terraform_base import cleanup_state

        storage = MagicMock()
        mock_get_storage.return_value = storage

        cleanup_state("gcp/gdc-ranges", "req-123", "Range")

        storage.delete_object.assert_called_once_with(
            bucket="shifter-gcp-dev-terraform-state",
            key="gcp/gdc-ranges/req-123/default.tfstate",
        )


class TestWorkspaceStaging:
    """Workspace staging keeps /app immutable while Terraform writes go to a dedicated, writable path.

    Issue #1103: when the provisioner container runs with readOnlyRootFilesystem=true the
    Terraform module path under /app/terraform/modules/<name> cannot be the working directory
    (terraform init writes .terraform/, .terraform.lock.hcl, terraform.tfvars.json there).
    terraform_base copies the module source tree to ${TERRAFORM_WORKSPACE_DIR}/<request_uuid>/<name>/
    before running terraform, runs terraform from the staged path, and removes the staged tree
    afterwards.
    """

    def test_stage_workspace_copies_module_into_workspace_dir(self, tmp_path):
        from terraform_base import _stage_workspace

        source = tmp_path / "module-src"
        (source / "templates").mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        (source / "variables.tf").write_text("# variables\n")
        (source / "templates" / "kali.sh.tpl").write_text("#!/bin/sh\n")

        workspace_root = tmp_path / "workspace"

        with patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(workspace_root)}, clear=False):
            staged = _stage_workspace(source, "req-abc", "Range")

        assert staged.is_dir()
        assert staged.parent == workspace_root / "req-abc"
        assert (staged / "main.tf").read_text() == "# main\n"
        assert (staged / "variables.tf").read_text() == "# variables\n"
        assert (staged / "templates" / "kali.sh.tpl").read_text() == "#!/bin/sh\n"

    def test_stage_workspace_default_dir_is_writable_for_local_dev(self, tmp_path, monkeypatch):
        """The Python default for TERRAFORM_WORKSPACE_DIR must be a path local dev /
        CI users can actually create. Inside the container the Dockerfile sets
        TERRAFORM_WORKSPACE_DIR=/var/run/provisioner/workspace explicitly; the
        Python fallback applies only when the env var is unset (local runs).
        Defaulting to /var/run/* there would fail PermissionError under non-root
        local users, so the fallback resolves under the per-user temp directory."""
        from terraform_base import (
            _CONTAINER_TERRAFORM_WORKSPACE_DIR,
            _DEFAULT_TERRAFORM_WORKSPACE_DIR,
            _stage_workspace,
        )

        # The container env var declares this exact path; tests assert against the
        # constant rather than hardcoding the literal.
        assert _CONTAINER_TERRAFORM_WORKSPACE_DIR == "/var/run/provisioner/workspace"
        # The Python fallback resolves under tempfile.gettempdir() — writable for
        # local dev / CI without root.
        import tempfile

        assert _DEFAULT_TERRAFORM_WORKSPACE_DIR.startswith(tempfile.gettempdir())

        # Redirect the default to a fresh tmp path so the test does not touch the
        # shared system temp dir.
        monkeypatch.setattr("terraform_base._DEFAULT_TERRAFORM_WORKSPACE_DIR", str(tmp_path / "default-workspace"))
        monkeypatch.delenv("TERRAFORM_WORKSPACE_DIR", raising=False)

        source = tmp_path / "module"
        source.mkdir()
        (source / "main.tf").write_text("# main\n")

        staged = _stage_workspace(source, "req-xyz", "NGFW")

        assert str(staged).startswith(str(tmp_path / "default-workspace" / "req-xyz"))
        assert (staged / "main.tf").read_text() == "# main\n"

    def test_cleanup_workspace_removes_staged_tree(self, tmp_path):
        from terraform_base import _cleanup_workspace

        workspace_root = tmp_path / "workspace"
        staged = workspace_root / "req-abc" / "module"
        staged.mkdir(parents=True)
        (staged / "main.tf").write_text("# main\n")

        with patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(workspace_root)}, clear=False):
            _cleanup_workspace(staged)

        # The whole per-request directory under workspace_root is removed.
        assert not staged.exists()
        assert not (workspace_root / "req-abc").exists()

    def test_cleanup_workspace_swallows_missing_path(self, tmp_path):
        from terraform_base import _cleanup_workspace

        # Calling cleanup on a non-existent path must not raise.
        with patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(tmp_path / "workspace")}, clear=False):
            _cleanup_workspace(tmp_path / "workspace" / "does-not-exist")

    def test_stage_workspace_drops_stale_tree_before_copy(self, tmp_path):
        """If a previous request_uuid's staged tree was left behind (cleanup failed,
        container restarted mid-run), the next stage must start clean — not merge into
        the stale tree, which could leak `terraform.tfvars.json` or stale `.terraform/`."""
        from terraform_base import _stage_workspace

        source = tmp_path / "module"
        source.mkdir()
        (source / "main.tf").write_text("# new\n")

        workspace_root = tmp_path / "workspace"
        # Pre-populate a stale staged tree that imitates a partial copy.
        stale = workspace_root / "req-abc" / "module"
        stale.mkdir(parents=True)
        (stale / "leftover.tfvars.json").write_text('{"old": "secret"}')
        (stale / "main.tf").write_text("# stale\n")

        with patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(workspace_root)}, clear=False):
            staged = _stage_workspace(source, "req-abc", "Range")

        assert (staged / "main.tf").read_text() == "# new\n"
        assert not (staged / "leftover.tfvars.json").exists(), (
            "stale terraform.tfvars.json must not survive into a fresh stage"
        )

    def test_stage_workspace_stages_terraform_tree_for_modules_layout(self, tmp_path):
        """When the source follows the conventional `…/terraform/modules/<name>/`
        layout, the whole `terraform/` parent must be staged so cross-module relative
        references (e.g. `source = "../shared"`) resolve in the staged tree."""
        from terraform_base import _stage_workspace

        terraform_root = tmp_path / "src" / "terraform"
        modules_dir = terraform_root / "modules"
        range_module = modules_dir / "range"
        range_module.mkdir(parents=True)
        (range_module / "main.tf").write_text("# range\n")
        # Sibling shared/ that the module could one day reference via `../shared`.
        shared_dir = terraform_root / "shared"
        shared_dir.mkdir()
        (shared_dir / "common.tf").write_text("# shared\n")
        # An adjacent NGFW module to confirm we copy it too.
        ngfw_module = modules_dir / "ngfw"
        ngfw_module.mkdir()
        (ngfw_module / "main.tf").write_text("# ngfw\n")

        workspace_root = tmp_path / "workspace"
        with patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(workspace_root)}, clear=False):
            staged = _stage_workspace(range_module, "req-shared", "Range")

        # staged points at the staged equivalent of the module under modules/<name>/
        assert staged.name == "range"
        assert (staged / "main.tf").read_text() == "# range\n"
        # The whole terraform/ tree was staged — sibling modules + shared/ are present.
        request_root = workspace_root / "req-shared"
        assert (request_root / "modules" / "ngfw" / "main.tf").read_text() == "# ngfw\n"
        assert (request_root / "shared" / "common.tf").read_text() == "# shared\n"

    def test_stage_workspace_excludes_runtime_artifacts(self, tmp_path):
        """`COPY . .` in the Dockerfile would copy a `.terraform/`, `*.tfstate`, or stray
        `terraform.tfvars.json` if any leaked into the build context. The stager must
        exclude those so they never propagate into a fresh per-request workspace.

        ``.terraform.lock.hcl`` is intentionally NOT excluded: it is a trusted
        repo-reviewed lockfile pinning provider checksums, and excluding it would
        force every ``terraform init`` to dynamically resolve providers under the
        privileged Job's cloud credentials (supply-chain risk). It is treated as
        source input — this test asserts that contract."""
        from terraform_base import _stage_workspace

        terraform_root = tmp_path / "src" / "terraform"
        range_module = terraform_root / "modules" / "range"
        range_module.mkdir(parents=True)
        (range_module / "main.tf").write_text("# main\n")
        # Runtime artifacts that should NOT be copied into the staged tree.
        (range_module / ".terraform").mkdir()
        (range_module / ".terraform" / "providers.json").write_text("{}")
        (range_module / "terraform.tfvars.json").write_text('{"old_secret": "x"}')
        (range_module / "old.tfstate").write_text("{}")
        (range_module / "old.tfstate.backup").write_text("{}")
        (range_module / ".terraform.tflock").write_text("")
        (range_module / "crash.log").write_text("oops")
        # Trusted source input that MUST survive into the staged tree.
        (range_module / ".terraform.lock.hcl").write_text("# pinned providers\n")

        workspace_root = tmp_path / "workspace"
        with patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(workspace_root)}, clear=False):
            staged = _stage_workspace(range_module, "req-clean", "Range")

        assert (staged / "main.tf").read_text() == "# main\n"
        assert not (staged / ".terraform").exists()
        assert not (staged / "terraform.tfvars.json").exists()
        assert not (staged / "old.tfstate").exists()
        assert not (staged / "old.tfstate.backup").exists()
        assert not (staged / ".terraform.tflock").exists()
        assert not (staged / "crash.log").exists()
        # Trusted lock file is preserved.
        assert (staged / ".terraform.lock.hcl").read_text() == "# pinned providers\n"

    def test_purge_tfvars_raises_on_failure(self, tmp_path, monkeypatch):
        """The whole point of staging is that secret-bearing terraform.tfvars.json
        does not survive a request. If the unlink fails, that secret is still on the
        workspace volume — the apply/destroy outcome must surface that, not silently
        report success while disk hygiene quietly broke."""
        from terraform_base import _purge_tfvars

        request_root = tmp_path / "req-x"
        module_dir = request_root / "modules" / "range"
        module_dir.mkdir(parents=True)
        tfvars = module_dir / "terraform.tfvars.json"
        tfvars.write_text('{"secret": "x"}')

        # Patch Path.unlink to raise as if the volume rejected the delete.
        original_unlink = Path.unlink

        def _failing_unlink(self, *args, **kwargs):
            if self.name == "terraform.tfvars.json":
                raise OSError("simulated permission error")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _failing_unlink)

        with pytest.raises(RuntimeError, match=r"terraform\.tfvars\.json"):
            _purge_tfvars(request_root)

    @pytest.mark.parametrize(
        "bad_uuid",
        [
            "..",
            "../escape",
            "req/abc",
            "req\\abc",
            "",
            ".req",  # leading dot would let an attacker hide the dir
            "x" * 200,  # too long
        ],
    )
    def test_stage_workspace_rejects_unsafe_request_uuid(self, tmp_path, bad_uuid):
        """request_uuid is concatenated into a filesystem path and then deleted with
        shutil.rmtree(). A `..`, `/`, or other path-bearing value would let cleanup
        walk outside the workspace root. Internal callers always pass real UUIDs,
        but the helper enforces the contract locally so a future careless caller
        cannot turn this into a path-traversal sink."""
        from terraform_base import _stage_workspace

        source = tmp_path / "module"
        source.mkdir()
        (source / "main.tf").write_text("# main\n")

        with (
            patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(tmp_path / "workspace")}, clear=False),
            pytest.raises(ValueError, match="path-safe"),
        ):
            _stage_workspace(source, bad_uuid, "Range")

    def test_destroy_uses_write_tfvars_helper(self, tmp_path, monkeypatch):
        """`destroy()` writes terraform.tfvars.json the same way `apply()` does — via
        `_write_tfvars` (0o600 perms, owner-only). Without this, the destroy path
        would write tfvars with default 0o644 and bypass the secret-file protection."""
        from terraform_base import destroy

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        observed_modes: list[int] = []

        def _fake_run(args, working_dir, env=None, capture_output=True):
            tfvars_path = Path(working_dir) / "terraform.tfvars.json"
            if tfvars_path.is_file():
                observed_modes.append(tfvars_path.stat().st_mode & 0o777)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with patch("terraform_base.run_terraform", side_effect=_fake_run):
            destroy("ranges", "req-destroy-secure", source, "Range", variables={"secret": "x"})

        assert observed_modes, "terraform.tfvars.json must have been written and visible to terraform"
        for mode in observed_modes:
            assert mode == 0o600, f"destroy() tfvars mode is {oct(mode)}, expected 0o600"

    def test_stage_workspace_creates_request_root_with_private_mode(self, tmp_path):
        """Local-dev / CI fallback workspace lives under /tmp and is shared with
        other users on the host. The per-request directory MUST be 0o700 so other
        users cannot enumerate or read staged secrets while the request runs."""
        from terraform_base import _stage_workspace

        source = tmp_path / "module"
        source.mkdir()
        (source / "main.tf").write_text("# main\n")

        workspace_root = tmp_path / "workspace"
        with patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(workspace_root)}, clear=False):
            _stage_workspace(source, "req-private", "Range")

        request_root = workspace_root / "req-private"
        # Lower 9 bits of mode == 0o700 (rwx for owner, none for group/others).
        assert (request_root.stat().st_mode & 0o777) == 0o700, (
            f"request_root mode is {oct(request_root.stat().st_mode & 0o777)}, expected 0o700"
        )

    def test_write_tfvars_has_owner_only_permissions(self, tmp_path):
        """terraform.tfvars.json carries Terraform inputs that may include cloud
        credentials. Other local users on a multi-tenant CI host MUST NOT be able
        to read it; the file is created with 0o600."""
        from terraform_base import _write_tfvars

        staged = tmp_path / "staged"
        staged.mkdir()
        path = _write_tfvars(staged, {"secret": "x"})

        assert (path.stat().st_mode & 0o777) == 0o600, (
            f"tfvars mode is {oct(path.stat().st_mode & 0o777)}, expected 0o600"
        )
        assert path.read_text().strip().startswith("{")

    def test_apply_secrets_purge_failure_is_not_silenced(self, tmp_path, monkeypatch):
        """End-to-end: if tfvars cleanup fails on the apply path, apply() must
        surface that (RuntimeError) rather than reporting success and leaving
        secret material on the workspace volume."""
        from terraform_base import apply

        source = tmp_path / "src" / "terraform" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        # Mock terraform shell-outs to no-ops returning empty output.
        with patch("terraform_base.run_terraform") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")

            original_unlink = Path.unlink

            def _failing_unlink(self, *args, **kwargs):
                if self.name == "terraform.tfvars.json":
                    raise OSError("simulated permission error")
                return original_unlink(self, *args, **kwargs)

            monkeypatch.setattr(Path, "unlink", _failing_unlink)

            with pytest.raises(RuntimeError, match=r"terraform\.tfvars\.json"):
                apply("ranges", "req-bad", {"secret": "x"}, source, "Range")

    def test_cleanup_workspace_removes_per_request_root_for_tree_staging(self, tmp_path):
        """When the stager copies the whole `terraform/` tree (modules layout),
        cleanup must walk back to the per-request root and remove the entire tree —
        not just the leaf module — so sibling modules and the shared/ dir do not
        survive."""
        from terraform_base import _cleanup_workspace, _stage_workspace

        terraform_root = tmp_path / "src" / "terraform"
        range_module = terraform_root / "modules" / "range"
        range_module.mkdir(parents=True)
        (range_module / "main.tf").write_text("# range\n")
        (terraform_root / "shared").mkdir()
        (terraform_root / "shared" / "common.tf").write_text("# shared\n")

        workspace_root = tmp_path / "workspace"
        with patch.dict("os.environ", {"TERRAFORM_WORKSPACE_DIR": str(workspace_root)}, clear=False):
            staged = _stage_workspace(range_module, "req-cleanup", "Range")
            _cleanup_workspace(staged)

        # The whole per-request directory under workspace_root is gone, including
        # the staged shared/ and modules/ngfw siblings.
        assert not (workspace_root / "req-cleanup").exists()

    @patch.dict(
        "os.environ",
        {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"},
        clear=True,
    )
    @patch("terraform_base.run_terraform")
    def test_apply_runs_from_staged_path_and_cleans_up(self, mock_run, tmp_path, monkeypatch):
        """apply() must stage the module, run terraform from the staged path, and clean up the
        staged tree on exit (success path) so successive runs do not pile up in the workspace."""
        from terraform_base import apply

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")

        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        # Capture cwd at each terraform call AND that the staged tree exists during the call.
        observed = []

        def _fake_run(args, working_dir, env=None, capture_output=True):
            observed.append(
                {
                    "args": list(args),
                    "working_dir": Path(working_dir),
                    "exists": Path(working_dir).is_dir(),
                }
            )
            result = MagicMock()
            result.returncode = 0
            result.stdout = "{}" if args[0] == "output" else "apply ok"
            result.stderr = ""
            return result

        mock_run.side_effect = _fake_run

        apply("ranges", "req-clean", {"foo": "bar"}, source, "Range")

        # init + apply + output → at least 3 invocations
        assert len(observed) >= 3
        for entry in observed:
            assert entry["working_dir"] != source
            assert str(entry["working_dir"]).startswith(str(workspace_root))
            assert entry["exists"] is True

        # Staged tree is gone after apply returns.
        staged_root = workspace_root / "req-clean"
        assert not staged_root.exists(), "apply() must remove the staged workspace on success"

    @patch.dict(
        "os.environ",
        {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"},
        clear=True,
    )
    @patch("terraform_base.run_terraform")
    def test_apply_cleans_up_workspace_on_failure(self, mock_run, tmp_path, monkeypatch):
        """If terraform itself fails partway through, the staged workspace still has to be torn
        down — otherwise leftover credentials in terraform.tfvars.json could persist on disk."""
        from terraform_base import apply

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")

        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        def _fake_run(args, working_dir, env=None, capture_output=True):
            if args[0] == "init":
                result = MagicMock()
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
                return result
            raise RuntimeError("simulated terraform apply failure")

        mock_run.side_effect = _fake_run

        with contextlib.suppress(RuntimeError):
            apply("ranges", "req-fail", {"foo": "bar"}, source, "Range")

        staged_root = workspace_root / "req-fail"
        assert not staged_root.exists(), "apply() must clean up the staged workspace even on failure"

    @patch.dict(
        "os.environ",
        {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"},
        clear=True,
    )
    @patch("terraform_base.run_terraform")
    def test_destroy_runs_from_staged_path_and_cleans_up(self, mock_run, tmp_path, monkeypatch):
        from terraform_base import destroy

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")

        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        observed_dirs = []

        def _fake_run(args, working_dir, env=None, capture_output=True):
            observed_dirs.append(Path(working_dir))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = _fake_run

        destroy("ranges", "req-destroy", source, "Range", variables={"foo": "bar"})

        for working_dir in observed_dirs:
            assert working_dir != source
            assert str(working_dir).startswith(str(workspace_root))

        staged_root = workspace_root / "req-destroy"
        assert not staged_root.exists()

    @patch.dict(
        "os.environ",
        {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"},
        clear=True,
    )
    @patch("terraform_base.run_terraform")
    def test_apply_writes_tfvars_under_staged_path(self, mock_run, tmp_path, monkeypatch):
        """terraform.tfvars.json must land in the staged workspace, not the source module path —
        otherwise apply() would try to write under /app and fail when /app is read-only."""
        from terraform_base import apply

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")

        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        observed_tfvars = []

        def _fake_run(args, working_dir, env=None, capture_output=True):
            tfvars_path = Path(working_dir) / "terraform.tfvars.json"
            if tfvars_path.is_file():
                observed_tfvars.append(
                    {
                        "working_dir": Path(working_dir),
                        "contents": json.loads(tfvars_path.read_text()),
                    }
                )
            result = MagicMock()
            result.returncode = 0
            result.stdout = "{}" if args[0] == "output" else ""
            result.stderr = ""
            return result

        mock_run.side_effect = _fake_run

        apply("ranges", "req-tfvars", {"foo": "bar"}, source, "Range")

        # The tfvars file must have been visible to terraform (apply step) under the staged path.
        assert any(
            str(observed["working_dir"]).startswith(str(workspace_root)) and observed["contents"] == {"foo": "bar"}
            for observed in observed_tfvars
        ), "terraform.tfvars.json should be staged under the writable workspace dir, not under the source module path"

        # And it must NOT have been written next to the source module (read-only /app surface).
        assert not (source / "terraform.tfvars.json").exists()
