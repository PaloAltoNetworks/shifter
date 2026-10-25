"""Enrollment crosses the TLS control boundary and secret stdin guest boundary."""

import base64
import json
import ssl
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from shared.model_access.guest_binding import ModelGuestBinding

import model_enrollment
from executors.base import CommandResult


@pytest.fixture
def control(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(  # noqa: S603 - fixed local certificate tool and pytest temporary paths.
        [
            "/usr/bin/openssl",
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
    token = str(uuid4()) + "." + "e" * 43

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            calls.append(
                (
                    self.path,
                    self.headers["Authorization"],
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "grant_id": str(uuid4()),
                        "enrollment_token": token,
                        "expires_at": (datetime.now(UTC) + timedelta(seconds=90)).isoformat(),
                    }
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(
            url=f"https://localhost:{server.server_port}", ca=cert.read_text(), calls=calls, token=token
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def delivery(control, monkeypatch):
    # Cloud identity and guest transport are the two external adapter boundaries;
    # TLS, enrollment serialization and secret separation remain real.
    identity = MagicMock(return_value="Bearer workload-assertion")
    monkeypatch.setattr(model_enrollment, "workload_assertion", identity)
    guest = MagicMock()
    guest.transport_name = "ssh"
    guest.wait_for_ready.return_value = True
    guest.executor.run_command.return_value = CommandResult(True, 0, "", "")
    builder = MagicMock(return_value=guest)
    monkeypatch.setattr(model_enrollment, "build_guest_execution_context", builder)
    binding = ModelGuestBinding(allocation_id=uuid4(), workload_role="participant", target_address="node.client")
    run = SimpleNamespace(operation_id=str(uuid4()), input=SimpleNamespace(model_enrollments=(binding,)))
    monkeypatch.setenv("MODEL_ENROLLMENT_CA_PEM_B64", base64.b64encode(control.ca.encode()).decode())
    monkeypatch.setenv("MODEL_ENROLLMENT_CONTROL_URL", control.url)
    monkeypatch.setenv("MODEL_BROKER_GUEST_URL", "https://models.example.test")
    monkeypatch.setenv("MODEL_BROKER_GUEST_VIP", "10.20.0.9")
    monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
    return SimpleNamespace(
        run=run, value=model_enrollment.load_model_enrollment(run), guest=guest, builder=builder, identity=identity
    )


def test_enrollment_carries_only_the_applied_private_broker_destination(delivery):
    assert delivery.value.gce_egress_capability() == {
        "contract_version": "model-broker-egress/v1",
        "vip": "10.20.0.9",
        "port": 443,
    }


@pytest.mark.parametrize("vip", ["", "203.0.113.9", "127.0.0.1", "10.20.0.0/24"])
def test_gcp_enrollment_rejects_missing_or_nonprivate_broker_destination(delivery, monkeypatch, vip):
    monkeypatch.setenv("MODEL_BROKER_GUEST_VIP", vip)
    with pytest.raises(model_enrollment.ModelEnrollmentError):
        model_enrollment.load_model_enrollment(delivery.run)


def test_delivers_exact_operation_and_allocation_only_over_stdin(control, delivery, caplog):
    instance = {"uuid": "node.client#0", "private_ip": "10.5.0.7"}
    delivery.value.execute(None, [instance])
    assert control.calls == [
        (
            "/control/v1/enroll",
            "Bearer workload-assertion",
            {
                "allocation_id": str(delivery.run.input.model_enrollments[0].allocation_id),
                "operation_id": delivery.run.operation_id,
            },
        )
    ]
    assert delivery.identity.call_args.kwargs["audience"] == f"shifter-model-control:enroll:{delivery.run.operation_id}"
    assert delivery.builder.call_args.args == (instance,)
    call = delivery.guest.executor.run_command.call_args
    assert control.token not in str(call.args)
    assert json.loads(call.kwargs["stdin_input"])["enrollment_token"] == control.token
    assert "findmnt" in call.args[1]
    assert "session.json >/dev/null 2>&1" in call.args[1]
    assert control.token not in caplog.text
    delivery.guest.close.assert_called_once()


@pytest.mark.parametrize("fault", ["ssm", "missing_guest", "not_ready", "guest_error"])
def test_failed_delivery_is_closed_and_never_exposes_secret(control, delivery, fault, caplog):
    instances = [{"uuid": "node.client#0"}]
    if fault == "ssm":
        delivery.guest.transport_name = "ssm"
    elif fault == "missing_guest":
        instances = []
    elif fault == "not_ready":
        delivery.guest.wait_for_ready.return_value = False
    else:
        delivery.guest.executor.run_command.side_effect = RuntimeError(control.token)
    with pytest.raises(model_enrollment.ModelEnrollmentError, match=r"^Guest model enrollment failed$"):
        delivery.value.execute(None, instances)
    assert control.token not in caplog.text
    if fault != "guest_error":
        assert not control.calls


def test_absent_binding_needs_no_runtime_configuration():
    assert model_enrollment.load_model_enrollment(SimpleNamespace(input=SimpleNamespace(model_enrollments=()))) is None


def test_aws_enrollment_uses_native_deployment_region(delivery, monkeypatch):
    monkeypatch.setenv("CLOUD_PROVIDER", "aws")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.delenv("CLOUD_REGION", raising=False)
    value = model_enrollment.load_model_enrollment(delivery.run)
    assert value is not None
    value.execute(None, [{"uuid": "node.client#0"}])
    assert delivery.identity.call_args.kwargs["region"] == "us-east-2"
    assert delivery.identity.call_args.kwargs["provider"] == "aws"


@pytest.mark.parametrize("provider,region", [("unsupported", "us-east-2"), ("aws", ""), ("aws", "https://evil.test")])
def test_bad_provider_configuration_fails_before_guest_mutation(delivery, monkeypatch, provider, region):
    monkeypatch.setenv("CLOUD_PROVIDER", provider)
    monkeypatch.setenv("AWS_REGION", region)
    with pytest.raises(model_enrollment.ModelEnrollmentError):
        model_enrollment.load_model_enrollment(delivery.run)
    delivery.builder.assert_not_called()
