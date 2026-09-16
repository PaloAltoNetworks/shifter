"""The contained specimen installs real service bytes and detects offline drift."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

CONTEXT = Path(__file__).parents[1] / "preparation/contexts/http-smoke"


@pytest.fixture(autouse=True)
def immutable_context(monkeypatch):
    """Loading the verifier must not add bytecode to digest-covered material."""
    monkeypatch.setattr(sys, "dont_write_bytecode", True)


def load_verifier():
    spec = importlib.util.spec_from_file_location("preparation_specimen_verifier", CONTEXT / "verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installed_root(tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/os-release").write_text('ID=ubuntu\nVERSION_ID="22.04"\n')
    subprocess.run(  # noqa: S603 - execute the checked-in recipe against a private temporary root
        ["/bin/bash", str(CONTEXT / "build.sh"), str(tmp_path)], cwd=CONTEXT, check=True
    )
    return tmp_path


def test_installed_bytes_are_independently_verifiable(installed_root):
    verifier = load_verifier()
    assert verifier.verify_root(installed_root, CONTEXT) == {"operating-system": "ubuntu:22.04"}
    assert (installed_root / "etc/systemd/system/multi-user.target.wants/shifter-http-smoke.service").is_symlink()


def test_enablement_cannot_follow_a_candidate_controlled_parent_link(installed_root):
    enabled = installed_root / "etc/systemd/system/multi-user.target.wants"
    moved = installed_root / "misplaced-enablement"
    enabled.rename(moved)
    enabled.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError):
        load_verifier().verify_root(installed_root, CONTEXT)


@pytest.mark.parametrize("corruption", ["payload", "unit", "key", "stage", "symlink", "os"])
def test_offline_verification_refuses_changed_or_unsanitized_output(installed_root, corruption):
    root = installed_root
    if corruption == "payload":
        (root / "opt/shifter-http-smoke/server.py").write_text("unrelated payload")
    elif corruption == "unit":
        (root / "etc/systemd/system/shifter-http-smoke.service").write_text("different startup")
    elif corruption == "key":
        (root / "etc/ssh").mkdir()
        (root / "etc/ssh/ssh_host_rsa_key").write_text("fixture key")
    elif corruption == "stage":
        (root / "var/lib/shifter-preparation").mkdir(parents=True)
        (root / "var/lib/shifter-preparation/private").write_text("private input")
    elif corruption == "symlink":
        payload = root / "opt/shifter-http-smoke/server.py"
        payload.unlink()
        payload.symlink_to(CONTEXT / "server.py")
    else:
        (root / "etc/os-release").write_text('ID=debian\nVERSION_ID="12"\n')
    with pytest.raises(ValueError):
        load_verifier().verify_root(root, CONTEXT)


def test_service_answers_a_fresh_boot_probe(tmp_path):
    import http.client
    import json
    import time

    server = subprocess.Popen(  # noqa: S603 - checked-in specimen and test-owned loopback endpoint
        [
            sys.executable,
            str(CONTEXT / "server.py"),
            "--bind",
            "127.0.0.1",
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        text=True,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert server.stdout is not None
        deadline = time.monotonic() + 5
        port_line = ""
        while not port_line and time.monotonic() < deadline:
            port_line = server.stdout.readline().strip()
        port = int(port_line)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/health/qualification-nonce")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read(1024)) == {"service": "shifter-http-smoke/v1", "nonce": "qualification-nonce"}
        connection.close()
        spec = importlib.util.spec_from_file_location("specimen_boot_probe", CONTEXT / "verify_boot.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        assert verifier.probe_http("127.0.0.1", "qualification-nonce", port=port)
    finally:
        server.terminate()
        server.wait(timeout=5)
