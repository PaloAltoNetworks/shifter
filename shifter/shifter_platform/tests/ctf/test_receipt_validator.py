"""Strict authenticated transport tests for receipt-v1 flag validation."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone

from ctf.validators import (
    HTTPValidatorConfigError,
    ReceiptProfileError,
    ReceiptVerifierProfile,
    normalize_http_validator_config,
    register_receipt_profile,
    validate_receipt,
)
from shared.receipt_validation import ReceiptKeyMode, ReceiptValidationContext
from tests.ctf.receipt_test_transport import receipt_wire

_FOREIGN_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _profile(**overrides):
    values = {
        "profile_id": "keplerops-penr1",
        "deployment_id": "gcp-dev",
        "provider_contract": "penr1-v1",
        "endpoint_url": "https://proof.example.test/v1/receipts/flag-agent-control/verify",
        "audience": "https://proof.example.test",
        "service_auth_secret_ref": "projects/test/secrets/receipt-callback/versions/1",
        "issuer_id": "keplerops-proof",
        "allowed_key_modes": (ReceiptKeyMode.REMOTE_SYMMETRIC,),
        "allowed_algorithms": ("hmac-sha256",),
        "permitted_objectives": ("flag-agent-control",),
        "total_timeout_seconds": 5,
        "max_addresses": 2,
        "max_request_bytes": 8192,
        "max_response_bytes": 4096,
        "max_receipt_ttl_seconds": 900,
    }
    values.update(overrides)
    return ReceiptVerifierProfile(**values)


def _context(**overrides):
    values = {
        "deployment_id": "gcp-dev",
        "profile_id": "keplerops-penr1",
        "provider_contract": "penr1-v1",
        "event_id": uuid4(),
        "participant_id": uuid4(),
        "challenge_id": uuid4(),
        "range_instance_id": 42,
        "materialization_id": uuid4(),
        "assignment_epoch": uuid4(),
        "registration_revision": uuid4(),
        "provider_range_namespace": uuid4().hex,
        "provider_participant_namespace": uuid4().hex,
        "issuer_id": "keplerops-proof",
        "key_mode": ReceiptKeyMode.REMOTE_SYMMETRIC,
        "algorithm_id": "hmac-sha256",
        "key_id": "range-key-v1",
        "public_verification_key": "",
        "reset_generation": 3,
        "registered_objectives": ("flag-agent-control",),
        "objective_id": "flag-agent-control",
    }
    values.update(overrides)
    return ReceiptValidationContext(**values)


def _response(context, **overrides):
    binding = {
        "event": str(context.event_id),
        "participant": context.provider_participant_namespace,
        "challenge": str(context.challenge_id),
        "range_instance": context.provider_range_namespace,
        "materialization": str(context.materialization_id),
        "assignment_epoch": str(context.assignment_epoch),
        "registration_revision": str(context.registration_revision),
        "reset_generation": context.reset_generation,
        "objective": context.objective_id,
    }
    payload = {
        "valid": True,
        "receipt_id": "penr1:receipt-identity",
        "issuer": context.issuer_id,
        "expires_at": (timezone.now() + timedelta(minutes=5)).isoformat(),
        "binding": binding,
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


@pytest.fixture
def registered_profile(monkeypatch):
    from ctf.validators import _receipt_profiles

    monkeypatch.setattr(_receipt_profiles, "_PROFILES", {})
    profile = _profile()
    register_receipt_profile(profile)
    return profile


def test_receipt_config_selects_only_a_registered_profile_and_objective(registered_profile):
    assert normalize_http_validator_config(
        {
            "protocol": "receipt-v1",
            "profile_id": registered_profile.profile_id,
            "objective_id": "flag-agent-control",
        }
    ) == {
        "protocol": "receipt-v1",
        "profile_id": registered_profile.profile_id,
        "objective_id": "flag-agent-control",
    }

    with pytest.raises(HTTPValidatorConfigError):
        normalize_http_validator_config(
            {
                "protocol": "receipt-v1",
                "profile_id": "missing-profile",
                "objective_id": "flag-agent-control",
            }
        )


@pytest.mark.parametrize(
    "override",
    [
        {"endpoint_url": "http://proof.example.test/verify"},
        {"endpoint_url": "https://proof.example.test/verify?auth=bad"},
        {"endpoint_url": "https://user@proof.example.test/verify"},
        {"permitted_objectives": ()},
        {"max_addresses": 0},
    ],
)
def test_receipt_profile_rejects_unsafe_or_unbounded_shapes(override):
    with pytest.raises(ReceiptProfileError):
        _profile(**override)


def test_authenticated_receipt_request_uses_only_server_context(registered_profile):
    context = _context()
    with receipt_wire(_response(context)) as wire:
        evidence = validate_receipt("PENR1.token", registered_profile, context)

    assert evidence is not None
    assert evidence.receipt_id == "penr1:receipt-identity"
    request_body = wire.request_json()
    assert request_body["receipt"] == "PENR1.token"
    assert request_body["binding"]["participant"] == context.provider_participant_namespace
    assert request_body["binding"]["range_instance"] == context.provider_range_namespace
    assert request_body["binding"]["challenge"] == str(context.challenge_id)
    assert "range_instance_id" not in request_body
    assert b"X-Service-Token: service-auth-value\r\n" in wire.request_bytes()
    wire.secrets_client.get_secret_value.assert_called_once_with(SecretId=registered_profile.service_auth_secret_ref)


@pytest.mark.parametrize(
    "response_mutation",
    [
        {"issuer": "another-issuer"},
        {"receipt_id": ""},
        {"expires_at": "2000-01-01T00:00:00+00:00"},
        {"valid": "true"},
        {"unexpected": True},
    ],
)
def test_receipt_response_fails_closed_on_ambiguous_or_stale_evidence(registered_profile, response_mutation):
    context = _context()
    with receipt_wire(_response(context, **response_mutation)):
        assert validate_receipt("PENR1.token", registered_profile, context) is None


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("event", _FOREIGN_UUID),
        ("participant", "participant-foreign"),
        ("challenge", _FOREIGN_UUID),
        ("range_instance", "range-foreign"),
        ("materialization", _FOREIGN_UUID),
        ("assignment_epoch", _FOREIGN_UUID),
        ("registration_revision", _FOREIGN_UUID),
        ("reset_generation", 4),
        ("objective", "flag-foreign"),
    ],
)
def test_receipt_response_rejects_every_foreign_binding(registered_profile, field, replacement):
    context = _context()
    payload = json.loads(_response(context))
    payload["binding"][field] = replacement
    with receipt_wire(json.dumps(payload).encode()):
        assert validate_receipt("PENR1.token", registered_profile, context) is None


def test_receipt_failure_logs_only_bounded_categories(registered_profile, caplog):
    context = _context()
    receipt_logger = logging.getLogger("ctf.validators._receipt")
    receipt_logger.addHandler(caplog.handler)
    receipt_canary = "PENR1.receipt-canary"
    secret_canary = "service-auth-canary-value"
    exception_canary = "provider-exception-canary-value"
    try:
        with receipt_wire(
            connection_error=OSError(exception_canary),
            service_auth=secret_canary,
        ):
            assert validate_receipt(receipt_canary, registered_profile, context) is None
    finally:
        receipt_logger.removeHandler(caplog.handler)

    rendered = caplog.text
    assert "Receipt validator provider is unavailable" in rendered
    assert receipt_canary not in rendered
    assert secret_canary not in rendered
    assert exception_canary not in rendered


def test_well_formed_negative_verdict_is_not_logged_as_provider_failure(registered_profile, caplog):
    context = _context()
    receipt_logger = logging.getLogger("ctf.validators._receipt")
    receipt_logger.addHandler(caplog.handler)
    try:
        with receipt_wire(b'{"valid":false}'):
            assert validate_receipt("PENR1.token", registered_profile, context) is None
    finally:
        receipt_logger.removeHandler(caplog.handler)

    assert "Receipt validator" not in caplog.text


def test_receipt_transport_caps_address_fallbacks(registered_profile):
    context = _context()
    with receipt_wire(
        ips=("8.8.8.8", "1.1.1.1", "9.9.9.9"),
        connection_error=OSError("offline"),
    ) as wire:
        assert validate_receipt("PENR1.token", registered_profile, context) is None
    assert wire.connect.call_count == registered_profile.max_addresses


@pytest.mark.parametrize("receipt", [" PENR1.token", "PENR1.token ", "PENR1.\ntoken", "PENR1.\x00token"])
def test_receipt_transport_rejects_ambiguous_token_framing(registered_profile, receipt):
    context = _context()
    with receipt_wire() as wire:
        assert validate_receipt(receipt, registered_profile, context) is None
    wire.boto_client_factory.assert_not_called()


def test_receipt_transport_stops_when_auth_lookup_exhausts_total_deadline(registered_profile):
    context = _context()
    with (
        patch("time.monotonic", side_effect=[10.0, 16.0]),
        receipt_wire() as wire,
    ):
        assert validate_receipt("PENR1.token", registered_profile, context) is None
    wire.dns.assert_not_called()


def test_legacy_http_config_and_payload_are_unchanged(registered_profile):
    assert normalize_http_validator_config({"url": "https://legacy.example.test/check"}) == {
        "url": "https://legacy.example.test/check",
        "method": "POST",
        "timeout": 10,
        "headers": {},
    }
