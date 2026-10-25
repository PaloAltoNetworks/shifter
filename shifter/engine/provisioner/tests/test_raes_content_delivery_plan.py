"""Tests for source-backed RAES content-delivery setup plans (#1564, ADR-032-R9).

Two layers:

- Unit tests on ``RaesContentDeliveryPlan`` itself: construction validation,
  step/verify_step shape, and that ``get_context``/stdin-building renders every
  runtime value (target, digest, size, sensitivity) the exact way each
  dialect's script expects it -- Linux via ``{{ }}`` template substitution
  into the static script text, Windows via stdin header lines -- and that the
  payload itself only ever travels as the streamed ``stdin_path`` file.
- Real ``bash`` execution of the rendered Linux scripts through the real
  ``GuestSSHExecutor`` streaming and command paths, with only the ssh hop
  replaced by a local shell (``_LocalShellExecutor``): asserts genuine on-disk
  behavior -- atomic install, correct mode, size/digest mismatch and missing
  free space fail closed before anything is published, and unsafe tar entries
  (symlink / absolute / traversal) are rejected before extraction. Windows
  (PowerShell) scripts cannot run in this Linux test environment and are
  covered by structural/string assertions only, matching this repo's existing
  convention for other Windows setup-plan tests.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from executors.base import CommandResult
from executors.guest_ssh_executor import GuestSSHExecutor
from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.raes_content_delivery import RaesContentDeliveryPlan, RaesContentInstallOptions, RaesContentPayload

_PAYLOAD_PATH = "/staging/payload"


def _b64(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return base64.b64encode(raw).decode("ascii")


def _plan(**kwargs) -> RaesContentDeliveryPlan:
    """Build a plan from flat test inputs, folding the payload fields into ``RaesContentPayload``."""
    payload = RaesContentPayload(
        path=kwargs.pop("payload_path"),
        byte_count=kwargs.pop("byte_count"),
        sha256=kwargs.pop("sha256"),
        installed_tree_sha256=kwargs.pop("installed_tree_sha256", None),
    )
    return RaesContentDeliveryPlan(payload=payload, **kwargs)


def _payload_file(directory: Path, payload: bytes) -> str:
    """Stage ``payload`` as the provisioner would: a local file outside the guest tree."""
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".payload-", delete=False) as handle:
        handle.write(payload)
    return handle.name


class TestConstruction:
    def test_rejects_unsupported_content_type(self):
        with pytest.raises(ValueError, match="content_type"):
            _plan(
                content_type="dataset",
                platform="linux",
                target="/x",
                sha256="a" * 64,
                payload_path=_PAYLOAD_PATH,
                byte_count=2,
            )

    def test_rejects_unknown_platform(self):
        with pytest.raises(ValueError, match="platform"):
            _plan(
                content_type="file",
                platform="solaris",
                target="/x",
                sha256="a" * 64,
                payload_path=_PAYLOAD_PATH,
                byte_count=2,
            )

    def test_rejects_empty_target(self):
        with pytest.raises(ValueError, match="target"):
            _plan(
                content_type="file",
                platform="linux",
                target="",
                sha256="a" * 64,
                payload_path=_PAYLOAD_PATH,
                byte_count=2,
            )

    def test_allows_an_empty_payload_for_a_zero_byte_file(self):
        # The producer materializer and DeliveryBinding contract both permit
        # byte_count == 0 for a genuine zero-byte source-backed `file`.
        plan = _plan(
            content_type="file",
            platform="linux",
            target="/x",
            sha256=hashlib.sha256(b"").hexdigest(),
            payload_path=_PAYLOAD_PATH,
            byte_count=0,
        )
        assert plan.get_context({})["raes_byte_count"] == "0"

    def test_rejects_empty_payload_for_directory(self):
        # Unlike `file`, a directory's tar payload is never legitimately
        # empty (even a zero-entry tar carries non-zero trailer bytes).
        with pytest.raises(ValueError, match="payload"):
            _plan(
                content_type="directory",
                platform="linux",
                target="/x",
                sha256="a" * 64,
                payload_path=_PAYLOAD_PATH,
                byte_count=0,
                installed_tree_sha256="b" * 64,
            )

    @pytest.mark.parametrize(("payload_path", "byte_count"), [("", 2), (_PAYLOAD_PATH, -1), (_PAYLOAD_PATH, True)])
    def test_rejects_a_missing_payload_file_or_invalid_size(self, payload_path, byte_count):
        with pytest.raises(ValueError, match=r"payload file|byte_count"):
            _plan(
                content_type="file",
                platform="linux",
                target="/x",
                sha256="a" * 64,
                payload_path=payload_path,
                byte_count=byte_count,
            )

    @pytest.mark.parametrize("bad_sha256", ["", "not-hex", "A" * 64, "a" * 63, "a" * 65])
    def test_rejects_non_hex_sha256(self, bad_sha256):
        with pytest.raises(ValueError, match="sha256"):
            _plan(
                content_type="file",
                platform="linux",
                target="/x",
                sha256=bad_sha256,
                payload_path=_PAYLOAD_PATH,
                byte_count=2,
            )

    @pytest.mark.parametrize("bad_tree_sha256", [None, "", "not-hex", "a" * 63])
    def test_rejects_missing_or_non_hex_installed_tree_sha256_for_directory(self, bad_tree_sha256):
        with pytest.raises(ValueError, match="installed_tree_sha256"):
            _plan(
                content_type="directory",
                platform="linux",
                target="/srv/data",
                sha256="a" * 64,
                payload_path=_PAYLOAD_PATH,
                byte_count=2,
                installed_tree_sha256=bad_tree_sha256,
            )


class TestLinuxStepShape:
    def test_script_carries_no_value_and_streams_the_payload_file(self):
        plan = _plan(
            content_type="file",
            platform="linux",
            target="/srv/x.bin",
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
        )
        step = plan.steps[0]
        # No authored/derived value is baked verbatim into the un-rendered script
        # template (it appears only as a {{ }} placeholder resolved by get_context),
        # and the payload is never part of the script: it streams from the file.
        assert "/srv/x.bin" not in step.script
        assert "{{ raes_target_quoted }}" in step.script
        assert "{{ raes_byte_count }}" in step.script
        assert "raes_payload" not in step.script
        assert step.stdin_input == ""
        assert step.stdin_path == _PAYLOAD_PATH
        assert step.name == "raes_deliver_content_file_linux"
        assert plan.verify_step.stdin_path == ""

    def test_deliver_budget_scales_with_payload_size(self):
        small = _plan(
            content_type="file",
            platform="linux",
            target="/x",
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
        )
        large = _plan(
            content_type="file",
            platform="linux",
            target="/x",
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=4_000_000_000,
        )
        assert small.steps[0].timeout_seconds == 600
        assert large.steps[0].timeout_seconds == 4600

    def test_get_context_shell_quotes_target_and_carries_size(self):
        plan = _plan(
            content_type="file",
            platform="linux",
            target="/srv/needs quoting.bin",
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=5,
            install_options=RaesContentInstallOptions(sensitive=True),
        )
        context = plan.get_context({})
        # shlex.quote only adds quotes when the value needs them (a space here);
        # a hex digest and octal mode carry no shell-special characters, so
        # shlex.quote returns them unquoted.
        assert context["raes_target_quoted"] == "'/srv/needs quoting.bin'"
        assert context["raes_sha256_quoted"] == "a" * 64
        assert context["raes_mode_quoted"] == "600"
        assert context["raes_byte_count"] == "5"

    def test_non_sensitive_file_uses_mode_644(self):
        plan = _plan(
            content_type="file",
            platform="linux",
            target="/srv/x.bin",
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
        )
        assert plan.get_context({})["raes_mode_quoted"] == "644"

    def test_directory_context_has_no_meaningful_mode(self):
        plan = _plan(
            content_type="directory",
            platform="linux",
            target="/srv/data",
            sha256="c" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
            installed_tree_sha256="d" * 64,
        )
        context = plan.get_context({})
        assert context["raes_target_quoted"] == "/srv/data"
        assert "{{ raes_mode_quoted }}" not in plan.steps[0].script

    def test_directory_verify_context_carries_installed_tree_digest(self):
        plan = _plan(
            content_type="directory",
            platform="linux",
            target="/srv/data",
            sha256="c" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
            installed_tree_sha256="d" * 64,
        )
        context = plan.get_context({})
        assert context["raes_tree_sha256_quoted"] == "d" * 64
        assert "{{ raes_tree_sha256_quoted }}" in plan.verify_step.script
        assert "{{ raes_tree_sha256_quoted }}" not in plan.steps[0].script


class TestWindowsStepShape:
    def test_script_carries_no_authored_value(self):
        plan = _plan(
            content_type="directory",
            platform="windows",
            target="C:\\data",
            sha256="b" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
            installed_tree_sha256="d" * 64,
        )
        step = plan.steps[0]
        assert "C:\\data" not in step.script
        assert step.stdin_path == _PAYLOAD_PATH
        assert "{{" not in step.script  # windows carries no template vars at all
        assert plan.get_context({}) == {}
        assert step.name == "raes_deliver_content_directory_windows"
        assert plan.verify_step.name == "raes_verify_content_directory_windows"

    def test_deliver_stdin_orders_target_digest_sensitivity_size_headers(self):
        plan = _plan(
            content_type="file",
            platform="windows",
            target="C:\\x.bin",
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=5,
            install_options=RaesContentInstallOptions(sensitive=True),
        )
        lines = plan.steps[0].stdin_input.splitlines()
        # The raw payload follows these header lines, streamed from stdin_path.
        assert lines == [_b64("C:\\x.bin"), _b64("a" * 64), _b64("1"), _b64("5")]

    def test_deliver_stdin_marks_non_sensitive_file(self):
        plan = _plan(
            content_type="file",
            platform="windows",
            target="C:\\x.bin",
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
        )
        lines = plan.steps[0].stdin_input.splitlines()
        assert lines[2] == _b64("0")

    def test_directory_stdin_includes_sensitivity_line(self):
        """Sensitivity now reaches the directory dialect too (#1564 security
        review): the Windows directory deliver script applies it as a
        protected ACL on the private extraction tree before publishing."""
        plan = _plan(
            content_type="directory",
            platform="windows",
            target="C:\\data",
            sha256="c" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
            install_options=RaesContentInstallOptions(sensitive=True),
            installed_tree_sha256="d" * 64,
        )
        lines = plan.steps[0].stdin_input.splitlines()
        assert lines == [_b64("C:\\data"), _b64("c" * 64), _b64("1"), _b64("2")]

    def test_verify_stdin_carries_only_target_and_digest(self):
        plan = _plan(
            content_type="file",
            platform="windows",
            target="C:\\x.bin",
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
        )
        lines = plan.verify_step.stdin_input.splitlines()
        assert lines == [_b64("C:\\x.bin"), _b64("a" * 64)]

    def test_directory_verify_stdin_carries_installed_tree_digest_not_tar_digest(self):
        plan = _plan(
            content_type="directory",
            platform="windows",
            target="C:\\data",
            sha256="c" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
            installed_tree_sha256="d" * 64,
        )
        lines = plan.verify_step.stdin_input.splitlines()
        assert lines == [_b64("C:\\data"), _b64("d" * 64)]

    @pytest.mark.parametrize(
        "unsafe_target",
        [
            "\\\\attacker\\share\\file.bin",  # UNC
            "\\\\?\\C:\\data.bin",  # device-namespace / extended-length prefix
            "\\\\.\\PhysicalDrive0",  # device path
            "relative\\path.bin",  # not rooted at all
            "C:\\data.bin:hidden",  # alternate data stream
            "C:\\data*.bin",  # wildcard
            "C:\\..\\Windows\\evil.dll",  # traversal segment
        ],
    )
    def test_windows_script_source_carries_the_target_path_validator(self, unsafe_target):
        """The plan itself is platform-generic (it does not know Windows path
        semantics), so rejection of a UNC/device/wildcard/traversal target is
        enforced by the guest-side ``Assert-RaesTargetPath`` this asserts is
        wired into every Windows deliver/verify script -- real PowerShell
        execution is out of reach in this Linux test environment (see the
        module docstring), so this is a structural, not behavioral, check."""
        plan = _plan(
            content_type="file",
            platform="windows",
            target=unsafe_target,
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
        )
        assert "Assert-RaesTargetPath" in plan.steps[0].script
        assert "Assert-RaesTargetPath -Target $TargetPath" in plan.steps[0].script

        dir_plan = _plan(
            content_type="directory",
            platform="windows",
            target=unsafe_target,
            sha256="a" * 64,
            payload_path=_PAYLOAD_PATH,
            byte_count=2,
            installed_tree_sha256="b" * 64,
        )
        assert "Assert-RaesTargetPath -Target $Destination" in dir_plan.steps[0].script


# ---------------------------------------------------------------------------
# Real bash execution of the Linux dialect through the real GuestSSHExecutor
# command/streaming paths; only the ssh hop is replaced by a local shell.
# ---------------------------------------------------------------------------

_BASH = shutil.which("bash")


class _LocalShellExecutor(GuestSSHExecutor):
    """GuestSSHExecutor whose remote command runs in a local shell instead of over ssh.

    sshd joins the remote command's arguments with spaces and hands the result
    to the login shell; this does the same locally, minus the ``sudo -n``
    privilege hop the test runner cannot take.
    """

    def __init__(self) -> None:
        super().__init__(private_key="unused", username="tester")

    def _build_ssh_args(self, host: str, remote_command: list[str]) -> list[str]:
        command = remote_command[2:] if remote_command[:2] == ["sudo", "-n"] else remote_command
        return [_BASH or "bash", "-c", " ".join(command)]


def _run_bash(plan: RaesContentDeliveryPlan, *, step) -> CommandResult:
    context = plan.get_context({})
    rendered_script = SetupOrchestrator._render_script(step.script, context, step.name)
    rendered_stdin = SetupOrchestrator._render_script(step.stdin_input or "", context, step.name)
    with _LocalShellExecutor() as executor:
        if step.stdin_path:
            return executor.run_command_streaming(
                "guest", rendered_script, stdin_path=step.stdin_path, stdin_prefix=rendered_stdin, timeout_seconds=30
            )
        return executor.run_command("guest", rendered_script, timeout_seconds=30, stdin_input=rendered_stdin or None)


def _file_plan(tmp_path: Path, target: Path, payload: bytes, **overrides) -> RaesContentDeliveryPlan:
    kwargs = {
        "content_type": "file",
        "platform": "linux",
        "target": str(target),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "payload_path": _payload_file(tmp_path, payload),
        "byte_count": len(payload),
    }
    kwargs.update(overrides)
    return _plan(**kwargs)


def _install_fake_df(tmp_path: Path, monkeypatch, available_kib: int) -> None:
    """Shadow ``df`` so the destination reports ``available_kib`` free."""
    bin_dir = tmp_path / ".fakebin"
    bin_dir.mkdir()
    fake = bin_dir / "df"
    fake.write_text(
        "#!/bin/sh\n"
        "echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
        f"echo 'fake 999999 0 {available_kib} 0% /'\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@pytest.mark.skipif(_BASH is None, reason="bash not available")
class TestLinuxFileExecution:
    def test_happy_path_installs_atomically_with_expected_mode_and_digest_readback(self, tmp_path):
        target = tmp_path / "nested" / "data.bin"
        payload = b"hello raes content delivery\x00\x01\xff\n\r"
        plan = _file_plan(tmp_path, target, payload, install_options=RaesContentInstallOptions(sensitive=True))
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr
        assert "RAES_CONTENT_FILE_INSTALLED" in deliver.stdout
        assert target.read_bytes() == payload
        assert oct(target.stat().st_mode)[-3:] == "600"
        # No staging artifact left behind.
        assert list(target.parent.iterdir()) == [target]

        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.success, verify.stderr
        assert "RAES_CONTENT_FILE_VERIFIED" in verify.stdout

    def test_a_multi_chunk_binary_payload_streams_byte_exact(self, tmp_path):
        target = tmp_path / "bin" / "tool"
        payload = os.urandom(3 * 1024 * 1024 + 17)  # spans several stream chunks
        plan = _file_plan(tmp_path, target, payload, install_options=RaesContentInstallOptions(file_mode="755"))
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr
        assert target.read_bytes() == payload
        assert oct(target.stat().st_mode)[-3:] == "755"

    def test_a_zero_byte_file_installs(self, tmp_path):
        target = tmp_path / "empty"
        plan = _file_plan(tmp_path, target, b"")
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr
        assert target.read_bytes() == b""

    def test_non_sensitive_file_gets_mode_644(self, tmp_path):
        target = tmp_path / "data.txt"
        plan = _file_plan(tmp_path, target, b"plain content")
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr
        assert oct(target.stat().st_mode)[-3:] == "644"

    def test_digest_mismatch_fails_closed_before_any_install(self, tmp_path):
        target = tmp_path / "out" / "data.bin"
        plan = _file_plan(tmp_path, target, b"real bytes", sha256="0" * 64)
        deliver = _run_bash(plan, step=plan.steps[0])
        assert not deliver.success
        assert "digest mismatch" in deliver.stderr
        assert not target.exists()
        # No leftover staging file in the parent directory either.
        assert list(target.parent.iterdir()) == []

    def test_size_mismatch_fails_closed_before_any_install(self, tmp_path):
        target = tmp_path / "out" / "data.bin"
        plan = _file_plan(tmp_path, target, b"real bytes", byte_count=4)
        deliver = _run_bash(plan, step=plan.steps[0])
        assert not deliver.success
        assert "size mismatch" in deliver.stderr
        assert list(target.parent.iterdir()) == []

    def test_insufficient_free_space_fails_closed_before_writing(self, tmp_path, monkeypatch):
        target = tmp_path / "out" / "data.bin"
        plan = _file_plan(tmp_path, target, b"x" * 4096)
        _install_fake_df(tmp_path, monkeypatch, available_kib=3)
        deliver = _run_bash(plan, step=plan.steps[0])
        assert not deliver.success
        assert "lacks free space" in deliver.stderr
        assert list(target.parent.iterdir()) == []

    def test_verify_fails_closed_when_installed_digest_no_longer_matches(self, tmp_path):
        target = tmp_path / "data.bin"
        target.write_bytes(b"tampered after install")
        plan = _file_plan(tmp_path, target, b"original bytes")
        verify = _run_bash(plan, step=plan.verify_step)
        assert not verify.success
        assert "readback digest mismatch" in verify.stderr

    def test_verify_fails_closed_when_target_is_a_symlink(self, tmp_path):
        real = tmp_path / "real.bin"
        real.write_bytes(b"data")
        link = tmp_path / "link.bin"
        link.symlink_to(real)
        plan = _file_plan(tmp_path, link, b"data")
        verify = _run_bash(plan, step=plan.verify_step)
        assert not verify.success
        assert "target is missing" in verify.stderr


def _deterministic_tar(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
    return buffer.getvalue()


def _expected_tree_sha256(entries: dict[str, bytes]) -> str:
    """Compute the same installed-tree manifest digest the guest verify script
    (and ``raes_content_payload.installed_tree_sha256``) computes, directly
    from the file entries -- sorted-relpath order, one "<sha256>  <relpath>\\n"
    line each -- so real-bash execution tests can assert a genuine happy-path
    readback match without duplicating tar-parsing plumbing here."""
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(entries.items()))
    return hashlib.sha256(manifest.encode()).hexdigest()


def _directory_plan(destination: Path, entries: dict[str, bytes], **overrides) -> RaesContentDeliveryPlan:
    payload = _deterministic_tar(entries)
    kwargs = {
        "content_type": "directory",
        "platform": "linux",
        "target": str(destination),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "payload_path": _payload_file(destination.parent.parent, payload),
        "byte_count": len(payload),
        "installed_tree_sha256": _expected_tree_sha256(entries),
    }
    kwargs.update(overrides)
    return _plan(**kwargs)


@pytest.mark.skipif(_BASH is None, reason="bash not available")
class TestLinuxDirectoryExecution:
    def test_happy_path_extracts_and_readback_verifies(self, tmp_path):
        destination = tmp_path / "app" / "data"
        entries = {"a.txt": b"alpha", "sub/b.txt": b"beta"}
        plan = _directory_plan(destination, entries)

        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr
        assert "RAES_CONTENT_DIRECTORY_INSTALLED" in deliver.stdout
        assert (destination / "a.txt").read_bytes() == b"alpha"
        assert (destination / "sub" / "b.txt").read_bytes() == b"beta"
        # No staging artifact left behind in the parent directory -- unlike
        # the old fixed-sibling-name design, nothing is retained across the
        # deliver/verify round trip at all.
        assert [p.name for p in destination.parent.iterdir()] == ["data"]

        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.success, verify.stderr
        assert "RAES_CONTENT_DIRECTORY_VERIFIED" in verify.stdout

    def test_reconcile_replaces_an_existing_destination(self, tmp_path):
        destination = tmp_path / "data"
        destination.mkdir()
        (destination / "stale.txt").write_bytes(b"old")
        plan = _directory_plan(destination, {"fresh.txt": b"new"})

        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr
        assert not (destination / "stale.txt").exists()
        assert (destination / "fresh.txt").read_bytes() == b"new"

    def test_digest_mismatch_fails_closed_before_extraction(self, tmp_path):
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"}, sha256="f" * 64)

        deliver = _run_bash(plan, step=plan.steps[0])
        assert not deliver.success
        assert "digest mismatch" in deliver.stderr
        assert not destination.exists()

    def test_rejects_symlink_entry_before_extraction(self, tmp_path):
        destination = tmp_path / "data"
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo(name="evil-link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        payload = buffer.getvalue()
        plan = _plan(
            content_type="directory",
            platform="linux",
            target=str(destination),
            sha256=hashlib.sha256(payload).hexdigest(),
            payload_path=_payload_file(tmp_path.parent, payload),
            byte_count=len(payload),
            installed_tree_sha256="a" * 64,
        )
        deliver = _run_bash(plan, step=plan.steps[0])
        assert not deliver.success
        assert "symlink entry" in deliver.stderr
        assert not destination.exists()

    @pytest.mark.parametrize("unsafe_name", ["/etc/passwd", "../../etc/passwd", "a/../../b"])
    def test_rejects_absolute_and_traversal_entries_before_extraction(self, tmp_path, unsafe_name):
        destination = tmp_path / "data"
        payload = _deterministic_tar({unsafe_name: b"x"})
        plan = _plan(
            content_type="directory",
            platform="linux",
            target=str(destination),
            sha256=hashlib.sha256(payload).hexdigest(),
            payload_path=_payload_file(tmp_path.parent, payload),
            byte_count=len(payload),
            installed_tree_sha256="a" * 64,
        )
        deliver = _run_bash(plan, step=plan.steps[0])
        assert not deliver.success
        assert "unsafe path" in deliver.stderr
        assert not destination.exists()

    def test_verify_fails_closed_when_destination_is_missing(self, tmp_path):
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"})
        verify = _run_bash(plan, step=plan.verify_step)
        assert not verify.success
        assert "destination is missing" in verify.stderr

    def test_verify_fails_closed_when_destination_is_a_symlink(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        plan = _directory_plan(link, {"a.txt": b"alpha"})
        verify = _run_bash(plan, step=plan.verify_step)
        assert not verify.success
        assert "destination is missing" in verify.stderr

    def test_verify_proves_the_installed_tree_not_a_retained_archive(self, tmp_path):
        """The security-critical regression this closes: verify must fail when
        the *installed* content diverges from what was delivered, even though
        nothing about the (now nonexistent) retained staging archive changed."""
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"})
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr

        (destination / "a.txt").write_bytes(b"tampered after install")
        verify = _run_bash(plan, step=plan.verify_step)
        assert not verify.success
        assert "readback digest mismatch" in verify.stderr

    def test_verify_fails_closed_when_an_extra_file_is_added_after_install(self, tmp_path):
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"})
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr

        (destination / "unexpected.txt").write_bytes(b"planted")
        verify = _run_bash(plan, step=plan.verify_step)
        assert not verify.success
        assert "readback digest mismatch" in verify.stderr

    def test_verify_fails_closed_when_a_file_is_missing_after_install(self, tmp_path):
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha", "b.txt": b"beta"})
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr

        (destination / "b.txt").unlink()
        verify = _run_bash(plan, step=plan.verify_step)
        assert not verify.success
        assert "readback digest mismatch" in verify.stderr

    def test_no_staging_archive_exists_at_any_point_the_guest_could_race(self, tmp_path):
        """Regression guard for the symlink-follow TOCTOU: the tar is staged
        under an exclusively-created (mktemp), unpredictable name -- an
        unprivileged process cannot know it in advance to pre-plant a symlink
        there, unlike the old fixed ``<destination>.raes-content-staging.tar``
        sibling name."""
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"})
        # The old vulnerable construction wrote a fixed, guessable sibling
        # filename; the tar staging path must now come from mktemp instead.
        assert '"${destination}.raes-content-staging.tar"' not in plan.steps[0].script
        assert "staging=$(mktemp" in plan.steps[0].script
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.success, deliver.stderr
        assert [p.name for p in tmp_path.iterdir()] == ["data"]
