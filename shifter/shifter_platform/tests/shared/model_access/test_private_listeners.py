"""Exercise deployment listener binding without opening sockets or provider calls."""

import pytest
import uvicorn

from engine.model_access_control import __main__ as control
from model_broker import __main__ as broker


@pytest.fixture(params=["broker", "control"])
def listener(request, monkeypatch, settings):
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: calls.append(vars(self.config)))
    monkeypatch.setattr(broker, "application_from_environment", lambda: object())
    settings.MODEL_ACCESS_ENABLED = True
    settings.MODEL_ACCESS_CATALOG = object()
    monkeypatch.setenv("MODEL_CONTROL_PROVIDER", "gcp")
    monkeypatch.setenv("MODEL_CONTROL_AUDIENCE", "synthetic-control")
    monkeypatch.setenv("MODEL_CONTROL_BROKER_SUBJECT", "synthetic-broker")
    monkeypatch.setenv("MODEL_CONTROL_PROVISIONER_SUBJECT", "synthetic-provisioner")
    monkeypatch.setenv("MODEL_CONTROL_BROKER_SUBJECT_ID", "123456789012345678901")
    monkeypatch.setenv("MODEL_CONTROL_PROVISIONER_SUBJECT_ID", "123456789012345678902")
    prefix = "MODEL_BROKER" if request.param == "broker" else "MODEL_CONTROL"
    monkeypatch.setenv(f"{prefix}_TLS_CERT", "/synthetic/tls.crt")
    monkeypatch.setenv(f"{prefix}_TLS_KEY", "/synthetic/tls.key")
    return broker.main if request.param == "broker" else control.main, prefix, calls


def test_listener_uses_explicit_private_interface(listener, monkeypatch):
    main, prefix, calls = listener
    monkeypatch.setenv(f"{prefix}_BIND_ADDRESS", "10.42.1.25")
    main()
    assert len(calls) == 1
    assert calls[0]["host"] == "10.42.1.25"
    assert calls[0]["proxy_headers"] is False
    assert calls[0]["ssl_certfile"] == "/synthetic/tls.crt"
    assert calls[0]["ssl_keyfile"] == "/synthetic/tls.key"


@pytest.mark.parametrize(
    "address",
    [None, "", "0.0.0.0", "::", "127.0.0.1", "169.254.169.254", "203.0.113.7"],  # noqa: S104 - rejected input
)
def test_listener_rejects_missing_or_nonprivate_binding(listener, monkeypatch, address):
    main, prefix, calls = listener
    if address is None:
        monkeypatch.delenv(f"{prefix}_BIND_ADDRESS", raising=False)
    else:
        monkeypatch.setenv(f"{prefix}_BIND_ADDRESS", address)
    with pytest.raises(SystemExit):
        main()
    assert not calls
