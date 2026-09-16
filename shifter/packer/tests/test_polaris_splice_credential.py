"""Behavioral regression tests for the Polaris splice credential helper."""

from __future__ import annotations

import base64
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).parents[1] / "files" / "polaris_splice_credential.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("polaris_splice_credential_helper", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def private_key(tmp_path: Path) -> bytes:
    key = tmp_path / "source-key"
    subprocess.run(  # noqa: S603 - fixed test executable and pytest temp path
        ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    return key.read_bytes()


@pytest.fixture
def helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_helper()
    home = tmp_path / "home" / "kali"
    monkeypatch.setattr(module, "KALI_HOME", home)
    monkeypatch.setattr(module, "KALI_UID", os.getuid())
    monkeypatch.setattr(module, "KALI_GID", os.getgid())
    return module


def _set_key(monkeypatch: pytest.MonkeyPatch, private_key: bytes) -> None:
    monkeypatch.setenv("KALI_SPLICE_PRIVATE_KEY_B64", base64.b64encode(private_key).decode("ascii"))


def test_repair_is_idempotent_and_preserves_unrelated_ssh_config(
    helper, private_key: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_key(monkeypatch, private_key)
    ssh_dir = helper.KALI_HOME / ".ssh"
    ssh_dir.mkdir(parents=True)
    config = ssh_dir / "config"
    config.write_text(
        "CanonicalizeHostname yes\n\nHost keep-me\n  User alice\n\nHost splice-relay\n  HostName wrong\n",
        encoding="utf-8",
    )

    helper.repair()
    first = config.read_text(encoding="utf-8")
    helper.repair()

    assert config.read_text(encoding="utf-8") == first
    assert first.count("Host splice-relay\n") == 1
    assert first.startswith("CanonicalizeHostname yes\n\nHost splice-relay\n")
    assert "Host keep-me\n  User alice" in first
    assert "HostName a9-splice" in first
    assert (ssh_dir / "splice_relay").read_bytes() == private_key
    assert (ssh_dir.stat().st_mode & 0o777) == 0o700
    assert ((ssh_dir / "splice_relay").stat().st_mode & 0o777) == 0o600
    assert (config.stat().st_mode & 0o777) == 0o600
    helper.check()


def test_invalid_environment_leaves_last_valid_key_untouched(
    helper, private_key: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_key(monkeypatch, private_key)
    helper.repair()
    target = helper.KALI_HOME / ".ssh" / "splice_relay"
    before = target.read_bytes()

    monkeypatch.setenv("KALI_SPLICE_PRIVATE_KEY_B64", "not-valid-base64")
    with pytest.raises(helper.CredentialContractError, match="invalid credential environment"):
        helper.repair()

    assert target.read_bytes() == before


def test_repair_rejects_symlink_target(
    helper, private_key: bytes, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_key(monkeypatch, private_key)
    ssh_dir = helper.KALI_HOME / ".ssh"
    ssh_dir.mkdir(parents=True)
    target = ssh_dir / "splice_relay"
    target.symlink_to(tmp_path / "redirected")

    with pytest.raises(helper.CredentialContractError, match="regular file"):
        helper.repair()


def test_cli_never_emits_secret_material(
    helper, private_key: bytes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_key(monkeypatch, private_key)
    encoded = os.environ["KALI_SPLICE_PRIVATE_KEY_B64"]

    assert helper.main(["repair"]) == 0

    output = capsys.readouterr()
    assert encoded not in output.out
    assert encoded not in output.err
    assert private_key.decode("ascii") not in output.out
    assert private_key.decode("ascii") not in output.err
    assert output.out.strip() == "splice-credential: repaired"


def test_entrypoint_repairs_before_exact_image_handoff(
    helper, private_key: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_key(monkeypatch, private_key)
    calls: list[tuple[str, list[str]]] = []

    class ExecIntercept(RuntimeError):
        pass

    def fake_execv(path: str, argv: list[str]) -> None:
        ssh_dir = helper.KALI_HOME / ".ssh"
        assert (ssh_dir / "splice_relay").read_bytes() == private_key
        assert "Host splice-relay\n" in (ssh_dir / "config").read_text(encoding="utf-8")
        calls.append((path, argv))
        raise ExecIntercept

    monkeypatch.setattr(helper.os, "execv", fake_execv)

    with pytest.raises(ExecIntercept):
        helper.main(["entrypoint"])

    assert calls == [(helper.ORIGINAL_ENTRYPOINT, [helper.ORIGINAL_ENTRYPOINT])]
    # Pin the literal path: the authoritative polaris a14-kali image installs its
    # entrypoint at /usr/local/bin/entrypoint.sh; execv of a nonexistent path
    # kills PID 1 and crash-loops the container. Guard against a silent revert.
    assert helper.ORIGINAL_ENTRYPOINT == "/usr/local/bin/entrypoint.sh"


def test_entrypoint_does_not_handoff_when_repair_fails(helper, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fail_repair() -> None:
        raise helper.CredentialContractError("repair refused")

    monkeypatch.setattr(helper, "repair", fail_repair)
    monkeypatch.setattr(helper.os, "execv", lambda path, argv: calls.append((path, argv)))

    assert helper.main(["entrypoint"]) == 1
    assert calls == []


def test_host_repair_stages_helper_checks_pair_and_never_restarts(helper, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    helper_installed = False

    def fake_docker(args: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal helper_installed
        calls.append(args)
        if args[:4] == ["exec", "a14-kali", "test", "-x"]:
            return subprocess.CompletedProcess(args, 0 if helper_installed else 1, "", "")
        if args[:3] == ["exec", "a14-kali", "install"]:
            helper_installed = True
        if "ssh-keygen" in args:
            return subprocess.CompletedProcess(args, 0, "ssh-ed25519 AAAATEST\n", "")
        if args[:2] == ["exec", "a9-splice"] and any("authorized_keys" in item for item in args):
            return subprocess.CompletedProcess(args, 0, "ssh-ed25519 AAAATEST comment\n", "")
        if args and args[0] == "inspect":
            return subprocess.CompletedProcess(args, 0, '{"build_splice-link":{}}', "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(helper, "_docker", fake_docker)

    helper.host_repair("a14-kali")

    assert any(
        args[0] == "cp" and args[-1].startswith("a14-kali:/usr/local/libexec/.polaris-splice-credential-")
        for args in calls
    )
    assert all("a14-kali:/tmp/" not in item for args in calls for item in args)
    assert any(args[-2:] == [helper.CONTAINER_HELPER, "repair"] for args in calls)
    assert any("root@splice-relay" in args for args in calls)
    assert all("restart" not in args for args in calls)


def test_host_check_fails_closed_on_a14_a9_pair_mismatch(helper, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_docker(args: list[str]) -> subprocess.CompletedProcess[str]:
        if "ssh-keygen" in args:
            return subprocess.CompletedProcess(args, 0, "ssh-ed25519 A14KEY\n", "")
        if args[:2] == ["exec", "a9-splice"] and any("authorized_keys" in item for item in args):
            return subprocess.CompletedProcess(args, 0, "ssh-ed25519 A9KEY\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(helper, "_docker", fake_docker)

    with pytest.raises(helper.CredentialContractError, match="key pair mismatch"):
        helper.host_check("a14-kali")


def test_host_check_does_not_stage_or_mutate_a_legacy_container(helper, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_docker(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, "", "")

    monkeypatch.setattr(helper, "_docker", fake_docker)

    with pytest.raises(helper.CredentialContractError, match="helper is missing"):
        helper.host_check("a14-kali")

    assert calls == [["exec", "a14-kali", "test", "-x", helper.CONTAINER_HELPER]]


def test_tracked_raes_helper_is_byte_identical() -> None:
    mirror = (
        Path(__file__).parents[3]
        / "scenario-dev"
        / "polaris"
        / "containers"
        / "boreas-kali"
        / "polaris_splice_credential.py"
    )
    assert mirror.read_bytes() == HELPER.read_bytes()
