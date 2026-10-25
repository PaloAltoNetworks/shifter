"""Published communication contracts derive closure and policy from runtime."""

import json

import pytest

from shared.api.contract import generate_openapi_document


@pytest.fixture(scope="module")
def schema():
    return json.loads(generate_openapi_document())


def test_exact_scopes_and_session_only_receipts(schema):
    collection = schema["paths"]["/api/v1/ctf/communications/"]
    assert collection["get"]["x-required-scopes"] == ["ctf:communication:read"]
    assert collection["post"]["x-required-scopes"] == ["ctf:communication:write"]
    receipt = schema["paths"]["/api/v1/ctf/me/events/{event_id}/communications/{snapshot_id}/read/"]["post"]
    assert receipt["security"] == [{"cookieAuth": []}]


def test_write_schemas_are_closed_and_bounded(schema):
    components = schema["components"]["schemas"]
    assert components["CommunicationCreate"]["additionalProperties"] is False
    assert components["CommunicationCreate"]["properties"]["target_event_ids"]["maxItems"] == 100
    assert components["CommunicationAudience"]["additionalProperties"] is False
    assert "oneOf" in components["CommunicationAudience"]
    assert "oneOf" in components["CommunicationTrigger"]


def test_communication_errors_are_published(schema):
    operation = schema["paths"]["/api/v1/ctf/communications/{campaign_id}/release/"]["post"]
    for status in ["400", "404", "409", "429", "503"]:
        assert operation["responses"][status]["content"]["application/json"]["schema"]["$ref"].endswith("/ApiError")


@pytest.mark.parametrize(
    "kind,field,count",
    [
        ("participant", "participant_ids", 1),
        ("participant_set", "participant_ids", 2),
        ("team", "team_ids", 1),
        ("event", "event_ids", 1),
        ("multi_event", "event_ids", 2),
    ],
)
def test_audience_variants_match_exactly_one_branch(schema, kind, field, count):
    from uuid import uuid4

    from jsonschema import Draft7Validator

    validator = Draft7Validator(
        {"$ref": "#/components/schemas/CommunicationAudience", "components": schema["components"]}
    )
    value = {"kind": kind, field: [str(uuid4()) for _ in range(count)]}
    assert validator.is_valid(value)
    wrong_field = "team_ids" if field != "team_ids" else "participant_ids"
    assert not validator.is_valid({"kind": kind, wrong_field: value[field]})
    if kind in {"participant", "event"}:
        assert not validator.is_valid({"kind": kind, field: [str(uuid4()), str(uuid4())]})
    if kind == "multi_event":
        assert not validator.is_valid({"kind": kind, field: value[field][:1]})


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "manual"},
        {"kind": "absolute_time", "due_at": "2026-10-01T12:00:00Z"},
        {"kind": "event_lifecycle", "event_status": "active"},
        {"kind": "raes_occurrence", "declaration_ref": "notice", "occurrence_ref": "one"},
        {"kind": "range_signal", "declaration_ref": "ready"},
    ],
)
def test_trigger_variants_require_their_own_fields(schema, value):
    from jsonschema import Draft7Validator

    validator = Draft7Validator(
        {"$ref": "#/components/schemas/CommunicationTrigger", "components": schema["components"]}
    )
    assert validator.is_valid(value)
    assert not validator.is_valid({"kind": "absolute_time"})
    assert not validator.is_valid({"kind": "manual", "due_at": "2026-10-01T12:00:00Z"})
