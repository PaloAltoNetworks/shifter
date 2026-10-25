"""Exercise the guest helper over real TLS and concurrent rotating credentials."""

import json
import os
import ssl
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from shifter_adapter_sdk.model_access import ModelAccessError, access_token, enroll

pytestmark = pytest.mark.integration

ENROLLMENT = "11111111-1111-4111-8111-111111111111." + "e" * 43
ACCESS = "11111111-1111-4111-8111-111111111111." + "a" * 43
REFRESH = "11111111-1111-4111-8111-111111111111." + "r" * 43


@pytest.fixture
def broker(tmp_path):
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    calls = []
    hard = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = {"fault": "", "expires": 5}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, payload))
            if response["fault"] == "redirect":
                self.send_response(307)
                self.send_header("Location", "https://localhost:1/stolen")
                self.end_headers()
                return
            if response["fault"] == "reject":
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"upstream diagnostic must stay private")
                return
            expected = ENROLLMENT if self.path.endswith("exchange") else REFRESH
            assert payload == {"token": expected}
            pair = {
                "access_token": ACCESS,
                "refresh_token": REFRESH,
                "access_expires_at": (datetime.now(UTC) + timedelta(minutes=response["expires"])).isoformat(),
                "hard_expires_at": hard,
            }
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(pair).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            {
                "broker_url": f"https://localhost:{server.server_port}",
                "ca_pem": cert.read_text(),
                "enrollment_token": ENROLLMENT,
            },
            calls,
            response,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "state"
    path.mkdir(mode=0o700)
    return path / "session.json"


def test_real_tls_enrollment_stores_only_broker_pair_and_reuses_valid_access(broker, state, monkeypatch):
    payload, calls, _ = broker
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    enroll(state, json.dumps(payload).encode())
    assert access_token(state) == ACCESS
    assert len(calls) == 1
    assert ENROLLMENT not in state.read_text()
    assert state.stat().st_mode & 0o777 == 0o600
    assert not list(state.parent.glob(".session-*"))


def test_refresh_is_serialized_across_clients(broker, state):
    payload, calls, _ = broker
    enroll(state, json.dumps(payload).encode())
    value = json.loads(state.read_text())
    value["access_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    state.write_text(json.dumps(value))
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert list(executor.map(lambda _: access_token(state), range(8))) == [ACCESS] * 8
    assert [path for path, _ in calls] == ["/v1/access/exchange", "/v1/access/refresh"]


@pytest.mark.parametrize("fault", ["redirect", "reject", "untrusted", "hostname", "plaintext"])
def test_enrollment_fails_without_storing_credentials_on_bad_transport(broker, state, fault):
    payload, calls, response = broker
    if fault in {"redirect", "reject"}:
        response["fault"] = fault
    elif fault == "untrusted":
        payload["ca_pem"] = "invalid CA"
    elif fault == "hostname":
        payload["broker_url"] = payload["broker_url"].replace("localhost", "127.0.0.1")
    else:
        payload["broker_url"] = payload["broker_url"].replace("https:", "http:")
    with pytest.raises(ModelAccessError, match="^Model enrollment unavailable$"):
        enroll(state, json.dumps(payload).encode())
    assert not state.exists()
    assert len(calls) <= 1


@pytest.mark.parametrize("fault", ["permissions", "symlink", "hardlink", "expired", "malformed"])
def test_untrusted_or_expired_state_never_returns_a_token(broker, state, fault, tmp_path):
    payload, _, _ = broker
    enroll(state, json.dumps(payload).encode())
    if fault == "permissions":
        state.chmod(0o644)
    elif fault == "hardlink":
        os.link(state, tmp_path / "linked")
    elif fault == "symlink":
        target = tmp_path / "target"
        state.rename(target)
        state.symlink_to(target)
    else:
        value = json.loads(state.read_text())
        value["hard_expires_at" if fault == "expired" else "access_token"] = (
            (datetime.now(UTC) - timedelta(seconds=1)).isoformat() if fault == "expired" else "bad"
        )
        state.write_text(json.dumps(value))
    with pytest.raises(ModelAccessError, match="^Model access unavailable$"):
        access_token(state)


def test_standalone_script_has_no_package_dependency_and_redacts_failure(state):
    import shifter_adapter_sdk.model_access as helper

    result = subprocess.run(
        [os.sys.executable, "-I", str(Path(helper.__file__)), "enroll", "--state", str(state)],
        input=json.dumps({"enrollment_token": ENROLLMENT}),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Model enrollment unavailable\n"
    assert ENROLLMENT not in result.stderr
