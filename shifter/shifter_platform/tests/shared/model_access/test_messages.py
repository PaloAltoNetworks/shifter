"""Unsupported protocol features fail before any provider transport."""

import json

import pytest

from shared.model_access import ContractError
from shared.model_access.messages import parse_messages, strict_json
from tests.engine.services.test_model_request_accounting import _limits


def _request(**kwargs):
    return json.dumps(
        {
            "model": "coding-main",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "synthetic prompt"}],
            **kwargs,
        }
    ).encode()


@pytest.mark.parametrize(
    "feature",
    [
        {"base_url": "https://untrusted.example"},
        {"thinking": {"type": "enabled", "budget_tokens": 5000}},
        {"messages": [{"role": "user", "content": [{"type": "image", "source": {"url": "https://example.invalid"}}]}]},
        {"tools": [{"type": "web_search_20250305", "name": "web_search"}]},
        {"max_tokens": True},
        {"stream": "true"},
        {"max_tokens": 9999},
    ],
)
def test_unknown_or_unbounded_features_are_rejected(feature):
    with pytest.raises(ContractError):
        parse_messages(_request(**feature), count_only=False, limits=_limits())


@pytest.mark.parametrize("raw", [b'{"model":"one","model":"two"}', b'{"x":NaN}', b"[]", b"\xff"])
def test_strict_json_rejects_ambiguous_payloads(raw):
    with pytest.raises(ContractError):
        strict_json(raw)


def test_depth_and_byte_limits_apply_before_provider_work():
    with pytest.raises(ContractError):
        strict_json(b'{"x":' * 34 + b"0" + b"}" * 34)
    with pytest.raises(ContractError):
        parse_messages(_request(system="a" * 1000), count_only=False, limits=_limits(max_request_bytes=100))


def test_text_and_local_tool_round_trip_is_supported():
    raw = _request(
        messages=[
            {"role": "user", "content": "test"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "x"}}],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "result"}]},
        ],
        tools=[{"name": "read_file", "input_schema": {"type": "object"}}],
    )
    parsed = parse_messages(raw, count_only=False, limits=_limits())
    assert parsed.messages[2].content[0].content == "result"


def test_count_has_its_own_closed_shape():
    with pytest.raises(ContractError):
        parse_messages(_request(), count_only=True, limits=_limits())
    raw = json.loads(_request())
    del raw["max_tokens"]
    assert parse_messages(json.dumps(raw).encode(), count_only=True, limits=_limits()).model == "coding-main"
