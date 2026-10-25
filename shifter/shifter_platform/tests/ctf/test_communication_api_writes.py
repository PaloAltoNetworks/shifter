"""Closed REST communication authoring contracts (#2100)."""

import json
from io import BytesIO
from uuid import uuid4

import pytest
from rest_framework.exceptions import ParseError


def payload():
    event = str(uuid4())
    return {
        "workspace_id": str(uuid4()),
        "title": "Welcome",
        "target_event_ids": [event],
        "audience_spec": {"kind": "event", "event_ids": [event]},
        "trigger_spec": {"kind": "manual"},
        "channels": ["in_app"],
        "subject": "Welcome",
        "body": "Hello",
        "acknowledgement_policy": "none",
    }


def serializer(data):
    from ctf.api.serializers.communication import CommunicationCreateSerializer

    return CommunicationCreateSerializer(data=data)


def test_create_contract_accepts_maximum_body_with_envelope():
    from ctf.api.serializers.communication import CommunicationJSONParser

    data = payload()
    data["body"] = "\t" * 65536
    parsed = CommunicationJSONParser().parse(BytesIO(json.dumps(data).encode()))
    instance = serializer(parsed)
    assert instance.is_valid(), instance.errors


@pytest.mark.parametrize(
    "field", ["system", "origin", "actor_user_id", "actor_token_id", "generation", "allow_early_release", "metadata"]
)
def test_authority_and_unknown_fields_are_rejected_without_echo(field):
    data = payload()
    data[field] = "private-canary"
    instance = serializer(data)
    assert not instance.is_valid()
    assert "private-canary" not in str(instance.errors)
    assert field not in str(instance.errors)


@pytest.mark.parametrize("field", ["audience_spec", "trigger_spec"])
def test_nested_contract_rejects_unknown_keys(field):
    data = payload()
    data[field]["private-canary"] = "secret"
    instance = serializer(data)
    assert not instance.is_valid()
    assert "private-canary" not in str(instance.errors)


def test_parser_rejects_duplicate_keys_and_oversized_envelope():
    from ctf.api.serializers.communication import CommunicationJSONParser

    for raw in [b'{"body":"a","body":"b"}', b" " * (CommunicationJSONParser.max_bytes + 1)]:
        with pytest.raises(ParseError):
            CommunicationJSONParser().parse(BytesIO(raw))


def test_domain_body_byte_bound_is_applied():
    data = payload()
    data["body"] = "a" * 65537
    instance = serializer(data)
    assert not instance.is_valid()


@pytest.mark.parametrize(
    "code, expected",
    [
        ("CTF_COMMUNICATION_DECLARATION_CONFLICT", 409),
        ("CTF_COMMUNICATION_REVISION_MISMATCH", 404),
        ("CTF_COMMUNICATION_AUDIENCE_OUT_OF_SCOPE", 404),
        ("CTF_COMMUNICATION_CHANNEL_UNAVAILABLE", 503),
    ],
)
def test_domain_errors_have_authored_status_and_no_raw_detail(code, expected):
    from ctf.api._base import ctf_error_response
    from ctf.exceptions import CTFCommunicationError

    response = ctf_error_response(
        None, CTFCommunicationError("private-canary", code=code, details={"private-key": "private-value"})
    )
    assert response.status_code == expected
    assert "private" not in str(response.data)
