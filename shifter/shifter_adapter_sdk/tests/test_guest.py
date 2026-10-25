"""The guest helper consumes bounded data, without application dependencies."""

import base64

import pytest
from shifter_adapter_sdk.guest import MAX_RUNTIME_VALUES_BYTES, RUNTIME_VALUES_ENV, read_runtime_values


def test_guest_values_are_data(monkeypatch):
    monkeypatch.setenv(RUNTIME_VALUES_ENV, base64.b64encode(b'{"address":"10.0.0.5"}').decode())
    assert read_runtime_values() == {"address": "10.0.0.5"}


@pytest.mark.parametrize("raw", [b"[]", b'{"key":5}', b"\xff", b" " * (MAX_RUNTIME_VALUES_BYTES + 1)])
def test_invalid_runtime_value_data_is_rejected(monkeypatch, raw):
    monkeypatch.setenv(RUNTIME_VALUES_ENV, base64.b64encode(raw).decode())
    with pytest.raises(ValueError, match="unavailable or invalid"):
        read_runtime_values()


def test_missing_and_invalid_encoding_is_rejected(monkeypatch):
    monkeypatch.delenv(RUNTIME_VALUES_ENV, raising=False)
    with pytest.raises(ValueError):
        read_runtime_values()
    monkeypatch.setenv(RUNTIME_VALUES_ENV, "!!!")
    with pytest.raises(ValueError):
        read_runtime_values()
