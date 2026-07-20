"""Tests for source-backed ACES content-delivery setup plans (#1564).

Two layers:

- Unit tests on ``AcesContentDeliveryPlan`` itself: construction validation,
  step/verify_step shape, and that ``get_context``/stdin-building renders every
  runtime value (target, digest, sensitivity, payload) the exact way each
  dialect's script expects it -- Linux via ``{{ }}`` template substitution
  into the static script text, Windows via the real stdin channel -- and never
  into Windows ``script`` (which becomes ``-EncodedCommand`` argv).
- Real ``bash`` execution of the rendered Linux scripts (the security-critical
  dialect, since the ACES-native backend is GCE-only today): pipes the exact
  concatenated script+stdin stream ``GuestSSHExecutor`` sends over SSH and
  asserts genuine on-disk behavior -- atomic install, correct mode, digest-
  mismatch fails closed before any file is written, and unsafe tar entries
  (symlink / absolute / traversal) are rejected before extraction. Windows
  (PowerShell) scripts cannot run in this Linux test environment and are
  covered by structural/string assertions only, matching this repo's existing
  convention for other Windows setup-plan tests.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.aces_content_delivery import AcesContentDeliveryPlan


def _b64(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return base64.b64encode(raw).decode("ascii")


class TestConstruction:
    def test_rejects_unsupported_content_type(self):
        with pytest.raises(ValueError, match="content_type"):
            AcesContentDeliveryPlan(
                content_type="dataset", platform="linux", target="/x", sha256="a" * 64, payload_b64="aGk="
            )

    def test_rejects_unknown_platform(self):
        with pytest.raises(ValueError, match="platform"):
            AcesContentDeliveryPlan(
                content_type="file", platform="solaris", target="/x", sha256="a" * 64, payload_b64="aGk="
            )

    def test_rejects_empty_target(self):
        with pytest.raises(ValueError, match="target"):
            AcesContentDeliveryPlan(
                content_type="file", platform="linux", target="", sha256="a" * 64, payload_b64="aGk="
            )

    def test_allows_empty_payload_for_a_zero_byte_file(self):
        # base64("") == "" is the correct encoding of a genuine zero-byte
        # source-backed file (#1564 core review): the producer materializer
        # and DeliveryBinding contract both permit byte_count == 0 for `file`.
        plan = AcesContentDeliveryPlan(
            content_type="file",
            platform="linux",
            target="/x",
            sha256=hashlib.sha256(b"").hexdigest(),
            payload_b64="",
        )
        assert plan.get_context({})["aces_payload_b64"] == ""

    def test_rejects_empty_payload_for_directory(self):
        # Unlike `file`, a directory's tar payload is never legitimately
        # empty (even a zero-entry tar carries non-zero trailer bytes).
        with pytest.raises(ValueError, match="payload"):
            AcesContentDeliveryPlan(
                content_type="directory",
                platform="linux",
                target="/x",
                sha256="a" * 64,
                payload_b64="",
                installed_tree_sha256="b" * 64,
            )

    @pytest.mark.parametrize("bad_sha256", ["", "not-hex", "A" * 64, "a" * 63, "a" * 65])
    def test_rejects_non_hex_sha256(self, bad_sha256):
        with pytest.raises(ValueError, match="sha256"):
            AcesContentDeliveryPlan(
                content_type="file", platform="linux", target="/x", sha256=bad_sha256, payload_b64="aGk="
            )

    @pytest.mark.parametrize("bad_tree_sha256", [None, "", "not-hex", "a" * 63])
    def test_rejects_missing_or_non_hex_installed_tree_sha256_for_directory(self, bad_tree_sha256):
        with pytest.raises(ValueError, match="installed_tree_sha256"):
            AcesContentDeliveryPlan(
                content_type="directory",
                platform="linux",
                target="/srv/data",
                sha256="a" * 64,
                payload_b64="aGk=",
                installed_tree_sha256=bad_tree_sha256,
            )


class TestLinuxStepShape:
    def test_script_carries_no_value_stdin_is_empty(self):
        plan = AcesContentDeliveryPlan(
            content_type="file", platform="linux", target="/srv/x.bin", sha256="a" * 64, payload_b64="aGk="
        )
        step = plan.steps[0]
        # No authored/derived value is baked verbatim into the un-rendered script
        # template (it appears only as a {{ }} placeholder resolved by get_context).
        assert "/srv/x.bin" not in step.script
        assert "aGk=" not in step.script
        assert "{{ aces_target_quoted }}" in step.script
        assert "{{ aces_payload_b64 }}" in step.script
        assert step.stdin_input == ""
        assert step.name == "aces_deliver_content_file_linux"

    def test_get_context_shell_quotes_target_and_embeds_payload(self):
        plan = AcesContentDeliveryPlan(
            content_type="file",
            platform="linux",
            target="/srv/needs quoting.bin",
            sha256="a" * 64,
            payload_b64="aGVsbG8=",
            sensitive=True,
        )
        context = plan.get_context({})
        # shlex.quote only adds quotes when the value needs them (a space here);
        # a hex digest and octal mode carry no shell-special characters, so
        # shlex.quote returns them unquoted.
        assert context["aces_target_quoted"] == "'/srv/needs quoting.bin'"
        assert context["aces_sha256_quoted"] == "a" * 64
        assert context["aces_mode_quoted"] == "600"
        assert context["aces_payload_b64"] == "aGVsbG8="

    def test_non_sensitive_file_uses_mode_644(self):
        plan = AcesContentDeliveryPlan(
            content_type="file", platform="linux", target="/srv/x.bin", sha256="a" * 64, payload_b64="aGk="
        )
        assert plan.get_context({})["aces_mode_quoted"] == "644"

    def test_directory_context_has_no_meaningful_mode(self):
        plan = AcesContentDeliveryPlan(
            content_type="directory",
            platform="linux",
            target="/srv/data",
            sha256="c" * 64,
            payload_b64="aGk=",
            installed_tree_sha256="d" * 64,
        )
        context = plan.get_context({})
        assert context["aces_target_quoted"] == "/srv/data"
        assert "{{ aces_mode_quoted }}" not in plan.steps[0].script

    def test_directory_verify_context_carries_installed_tree_digest(self):
        plan = AcesContentDeliveryPlan(
            content_type="directory",
            platform="linux",
            target="/srv/data",
            sha256="c" * 64,
            payload_b64="aGk=",
            installed_tree_sha256="d" * 64,
        )
        context = plan.get_context({})
        assert context["aces_tree_sha256_quoted"] == "d" * 64
        assert "{{ aces_tree_sha256_quoted }}" in plan.verify_step.script
        assert "{{ aces_tree_sha256_quoted }}" not in plan.steps[0].script


class TestWindowsStepShape:
    def test_script_carries_no_authored_value(self):
        plan = AcesContentDeliveryPlan(
            content_type="directory",
            platform="windows",
            target="C:\\data",
            sha256="b" * 64,
            payload_b64="aGk=",
            installed_tree_sha256="d" * 64,
        )
        step = plan.steps[0]
        assert "C:\\data" not in step.script
        assert "aGk=" not in step.script
        assert "{{" not in step.script  # windows carries no template vars at all
        assert plan.get_context({}) == {}
        assert step.name == "aces_deliver_content_directory_windows"
        assert plan.verify_step.name == "aces_verify_content_directory_windows"

    def test_deliver_stdin_orders_target_digest_sensitivity_payload(self):
        plan = AcesContentDeliveryPlan(
            content_type="file",
            platform="windows",
            target="C:\\x.bin",
            sha256="a" * 64,
            payload_b64="aGVsbG8=",
            sensitive=True,
        )
        lines = plan.steps[0].stdin_input.splitlines()
        assert lines == [_b64("C:\\x.bin"), _b64("a" * 64), _b64("1"), "aGVsbG8="]

    def test_deliver_stdin_marks_non_sensitive_file(self):
        plan = AcesContentDeliveryPlan(
            content_type="file", platform="windows", target="C:\\x.bin", sha256="a" * 64, payload_b64="aGk="
        )
        lines = plan.steps[0].stdin_input.splitlines()
        assert lines[2] == _b64("0")

    def test_directory_stdin_includes_sensitivity_line(self):
        """Sensitivity now reaches the directory dialect too (#1564 security
        review): the Windows directory deliver script applies it as a
        protected ACL on the private extraction tree before publishing."""
        plan = AcesContentDeliveryPlan(
            content_type="directory",
            platform="windows",
            target="C:\\data",
            sha256="c" * 64,
            payload_b64="aGk=",
            sensitive=True,
            installed_tree_sha256="d" * 64,
        )
        lines = plan.steps[0].stdin_input.splitlines()
        assert lines == [_b64("C:\\data"), _b64("c" * 64), _b64("1"), "aGk="]

    def test_verify_stdin_carries_only_target_and_digest(self):
        plan = AcesContentDeliveryPlan(
            content_type="file", platform="windows", target="C:\\x.bin", sha256="a" * 64, payload_b64="aGk="
        )
        lines = plan.verify_step.stdin_input.splitlines()
        assert lines == [_b64("C:\\x.bin"), _b64("a" * 64)]

    def test_directory_verify_stdin_carries_installed_tree_digest_not_tar_digest(self):
        plan = AcesContentDeliveryPlan(
            content_type="directory",
            platform="windows",
            target="C:\\data",
            sha256="c" * 64,
            payload_b64="aGk=",
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
        enforced by the guest-side ``Assert-AcesTargetPath`` this asserts is
        wired into every Windows deliver/verify script -- real PowerShell
        execution is out of reach in this Linux test environment (see the
        module docstring), so this is a structural, not behavioral, check."""
        plan = AcesContentDeliveryPlan(
            content_type="file", platform="windows", target=unsafe_target, sha256="a" * 64, payload_b64="aGk="
        )
        assert "Assert-AcesTargetPath" in plan.steps[0].script
        assert "Assert-AcesTargetPath -Target $TargetPath" in plan.steps[0].script

        dir_plan = AcesContentDeliveryPlan(
            content_type="directory",
            platform="windows",
            target=unsafe_target,
            sha256="a" * 64,
            payload_b64="aGk=",
            installed_tree_sha256="b" * 64,
        )
        assert "Assert-AcesTargetPath -Target $Destination" in dir_plan.steps[0].script


# ---------------------------------------------------------------------------
# Real bash execution of the Linux dialect (the ACES-native backend is GCE-only
# today, so this is the security-critical path). Mirrors exactly the
# concatenation GuestSSHExecutor._build_command_input performs for a
# non-PowerShell document: "set -euo pipefail\n" + script + "\n" + stdin.
# ---------------------------------------------------------------------------

_BASH = shutil.which("bash")


def _run_bash(plan: AcesContentDeliveryPlan, *, step) -> subprocess.CompletedProcess:
    context = plan.get_context({})
    rendered_script = SetupOrchestrator._render_script(step.script, context, step.name)
    rendered_stdin = SetupOrchestrator._render_script(step.stdin_input or "", context, step.name)
    parts = ["set -euo pipefail", rendered_script.rstrip("\n")]
    if rendered_stdin:
        parts.append(rendered_stdin.rstrip("\n"))
    command_input = "\n".join(parts) + "\n"
    return subprocess.run(  # noqa: S603 — absolute bash path, fixed args, no shell=True
        [_BASH, "-se"], input=command_input.encode(), capture_output=True, timeout=30, check=False
    )


@pytest.mark.skipif(_BASH is None, reason="bash not available")
class TestLinuxFileExecution:
    def test_happy_path_installs_atomically_with_expected_mode_and_digest_readback(self, tmp_path):
        target = tmp_path / "nested" / "data.bin"
        payload = b"hello aces content delivery\x00\x01\xff"
        digest = hashlib.sha256(payload).hexdigest()
        plan = AcesContentDeliveryPlan(
            content_type="file",
            platform="linux",
            target=str(target),
            sha256=digest,
            payload_b64=_b64(payload),
            sensitive=True,
        )
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode == 0, deliver.stderr.decode()
        assert "ACES_CONTENT_FILE_INSTALLED" in deliver.stdout.decode()
        assert target.read_bytes() == payload
        assert oct(target.stat().st_mode)[-3:] == "600"
        # No staging artifact left behind.
        assert list(target.parent.iterdir()) == [target]

        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode == 0, verify.stderr.decode()
        assert "ACES_CONTENT_FILE_VERIFIED" in verify.stdout.decode()

    def test_non_sensitive_file_gets_mode_644(self, tmp_path):
        target = tmp_path / "data.txt"
        payload = b"plain content"
        plan = AcesContentDeliveryPlan(
            content_type="file",
            platform="linux",
            target=str(target),
            sha256=hashlib.sha256(payload).hexdigest(),
            payload_b64=_b64(payload),
            sensitive=False,
        )
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode == 0, deliver.stderr.decode()
        assert oct(target.stat().st_mode)[-3:] == "644"

    def test_digest_mismatch_fails_closed_before_any_install(self, tmp_path):
        target = tmp_path / "data.bin"
        payload = b"real bytes"
        plan = AcesContentDeliveryPlan(
            content_type="file",
            platform="linux",
            target=str(target),
            sha256="0" * 64,  # wrong digest
            payload_b64=_b64(payload),
        )
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode != 0
        assert "digest mismatch" in deliver.stderr.decode()
        assert not target.exists()
        # No leftover staging file in the parent directory either.
        assert list(tmp_path.iterdir()) == []

    def test_verify_fails_closed_when_installed_digest_no_longer_matches(self, tmp_path):
        target = tmp_path / "data.bin"
        target.write_bytes(b"tampered after install")
        plan = AcesContentDeliveryPlan(
            content_type="file",
            platform="linux",
            target=str(target),
            sha256=hashlib.sha256(b"original bytes").hexdigest(),
            payload_b64=_b64(b"original bytes"),
        )
        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode != 0
        assert "readback digest mismatch" in verify.stderr.decode()

    def test_verify_fails_closed_when_target_is_a_symlink(self, tmp_path):
        real = tmp_path / "real.bin"
        real.write_bytes(b"data")
        link = tmp_path / "link.bin"
        link.symlink_to(real)
        plan = AcesContentDeliveryPlan(
            content_type="file",
            platform="linux",
            target=str(link),
            sha256=hashlib.sha256(b"data").hexdigest(),
            payload_b64=_b64(b"data"),
        )
        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode != 0
        assert "target is missing" in verify.stderr.decode()


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
    (and ``aces_content_delivery._installed_tree_sha256``) computes, directly
    from the file entries -- sorted-relpath order, one "<sha256>  <relpath>\\n"
    line each -- so real-bash execution tests can assert a genuine happy-path
    readback match without duplicating tar-parsing plumbing here."""
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(entries.items()))
    return hashlib.sha256(manifest.encode()).hexdigest()


def _directory_plan(destination: Path, entries: dict[str, bytes], **overrides) -> AcesContentDeliveryPlan:
    payload = _deterministic_tar(entries)
    kwargs = {
        "content_type": "directory",
        "platform": "linux",
        "target": str(destination),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "payload_b64": _b64(payload),
        "installed_tree_sha256": _expected_tree_sha256(entries),
    }
    kwargs.update(overrides)
    return AcesContentDeliveryPlan(**kwargs)


@pytest.mark.skipif(_BASH is None, reason="bash not available")
class TestLinuxDirectoryExecution:
    def test_happy_path_extracts_and_readback_verifies(self, tmp_path):
        destination = tmp_path / "app" / "data"
        entries = {"a.txt": b"alpha", "sub/b.txt": b"beta"}
        plan = _directory_plan(destination, entries)

        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode == 0, deliver.stderr.decode()
        assert "ACES_CONTENT_DIRECTORY_INSTALLED" in deliver.stdout.decode()
        assert (destination / "a.txt").read_bytes() == b"alpha"
        assert (destination / "sub" / "b.txt").read_bytes() == b"beta"
        # No staging artifact left behind in the parent directory -- unlike
        # the old fixed-sibling-name design, nothing is retained across the
        # deliver/verify round trip at all.
        assert [p.name for p in destination.parent.iterdir()] == ["data"]

        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode == 0, verify.stderr.decode()
        assert "ACES_CONTENT_DIRECTORY_VERIFIED" in verify.stdout.decode()

    def test_reconcile_replaces_an_existing_destination(self, tmp_path):
        destination = tmp_path / "data"
        destination.mkdir()
        (destination / "stale.txt").write_bytes(b"old")
        plan = _directory_plan(destination, {"fresh.txt": b"new"})

        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode == 0, deliver.stderr.decode()
        assert not (destination / "stale.txt").exists()
        assert (destination / "fresh.txt").read_bytes() == b"new"

    def test_digest_mismatch_fails_closed_before_extraction(self, tmp_path):
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"}, sha256="f" * 64)

        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode != 0
        assert "digest mismatch" in deliver.stderr.decode()
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
        plan = AcesContentDeliveryPlan(
            content_type="directory",
            platform="linux",
            target=str(destination),
            sha256=hashlib.sha256(payload).hexdigest(),
            payload_b64=_b64(payload),
            installed_tree_sha256="a" * 64,
        )
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode != 0
        assert "symlink entry" in deliver.stderr.decode()
        assert not destination.exists()

    @pytest.mark.parametrize("unsafe_name", ["/etc/passwd", "../../etc/passwd", "a/../../b"])
    def test_rejects_absolute_and_traversal_entries_before_extraction(self, tmp_path, unsafe_name):
        destination = tmp_path / "data"
        payload = _deterministic_tar({unsafe_name: b"x"})
        plan = AcesContentDeliveryPlan(
            content_type="directory",
            platform="linux",
            target=str(destination),
            sha256=hashlib.sha256(payload).hexdigest(),
            payload_b64=_b64(payload),
            installed_tree_sha256="a" * 64,
        )
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode != 0
        assert "unsafe path" in deliver.stderr.decode()
        assert not destination.exists()

    def test_verify_fails_closed_when_destination_is_missing(self, tmp_path):
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"})
        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode != 0
        assert "destination is missing" in verify.stderr.decode()

    def test_verify_fails_closed_when_destination_is_a_symlink(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        plan = _directory_plan(link, {"a.txt": b"alpha"})
        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode != 0
        assert "destination is missing" in verify.stderr.decode()

    def test_verify_proves_the_installed_tree_not_a_retained_archive(self, tmp_path):
        """The security-critical regression this closes: verify must fail when
        the *installed* content diverges from what was delivered, even though
        nothing about the (now nonexistent) retained staging archive changed."""
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"})
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode == 0, deliver.stderr.decode()

        (destination / "a.txt").write_bytes(b"tampered after install")
        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode != 0
        assert "readback digest mismatch" in verify.stderr.decode()

    def test_verify_fails_closed_when_an_extra_file_is_added_after_install(self, tmp_path):
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"})
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode == 0, deliver.stderr.decode()

        (destination / "unexpected.txt").write_bytes(b"planted")
        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode != 0
        assert "readback digest mismatch" in verify.stderr.decode()

    def test_verify_fails_closed_when_a_file_is_missing_after_install(self, tmp_path):
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha", "b.txt": b"beta"})
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode == 0, deliver.stderr.decode()

        (destination / "b.txt").unlink()
        verify = _run_bash(plan, step=plan.verify_step)
        assert verify.returncode != 0
        assert "readback digest mismatch" in verify.stderr.decode()

    def test_no_staging_archive_exists_at_any_point_the_guest_could_race(self, tmp_path):
        """Regression guard for the symlink-follow TOCTOU: the tar is staged
        under an exclusively-created (mktemp), unpredictable name -- an
        unprivileged process cannot know it in advance to pre-plant a symlink
        there, unlike the old fixed ``<destination>.aces-content-staging.tar``
        sibling name."""
        destination = tmp_path / "data"
        plan = _directory_plan(destination, {"a.txt": b"alpha"})
        # The old vulnerable construction wrote a fixed, guessable sibling
        # filename; the tar staging path must now come from mktemp instead.
        assert '"${destination}.aces-content-staging.tar"' not in plan.steps[0].script
        assert "tar_staging=$(mktemp" in plan.steps[0].script
        deliver = _run_bash(plan, step=plan.steps[0])
        assert deliver.returncode == 0, deliver.stderr.decode()
        assert [p.name for p in tmp_path.iterdir()] == ["data"]
