"""Wire-level provider tests using real HTTP serialization and stream decoders."""

import base64
import json
import struct
import zlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from botocore.eventstream import ChecksumMismatch

from model_broker.provider_usage import StreamUsage, bedrock_events, usage_from_message, vertex_events
from model_broker.providers import MessagesProvider
from shared.model_access import ContractError
from shared.model_access.messages import parse_messages
from shared.model_access.provider_runtime import ProviderTarget
from tests.engine.services.test_model_request_accounting import _limits

pytestmark = pytest.mark.asyncio


def target(provider):
    return ProviderTarget(
        shard_id="synthetic",
        provider=provider,
        region="us-east-1" if provider == "bedrock-v1" else "us-east5",
        model="anthropic.claude-synthetic-v1:0"
        if provider == "bedrock-v1"
        else "publishers/anthropic/models/claude-synthetic@20260901",
        credential_reference="synthetic-identity",
        context_window_tokens=200_000,
        principal="arn:aws:iam::123456789012:role/model-test"
        if provider == "bedrock-v1"
        else "model-test@models-test.iam.gserviceaccount.com",
        project="" if provider == "bedrock-v1" else "models-test",
        count_region="" if provider == "bedrock-v1" else "us",
    )


class CredentialsPort:
    async def headers(self, target, *, url, body):
        return {"content-type": "application/json", "authorization": "synthetic-workload-proof"}


async def lease():
    return (datetime.now(UTC) + timedelta(seconds=5)).isoformat()


def message(*, stream=False):
    return parse_messages(
        json.dumps(
            {
                "model": "coding-main",
                "max_tokens": 20,
                "stream": stream,
                "messages": [{"role": "user", "content": "test"}],
            }
        ).encode(),
        count_only=False,
        limits=_limits(),
    )


@pytest.mark.parametrize("provider", ["vertex-v1", "bedrock-v1"])
async def test_fixed_provider_origins_count_before_invoke_and_normalize_usage(provider):
    calls = []

    def transport(request):
        calls.append(request)
        if "count-tokens" in request.url.path:
            return httpx.Response(200, json={"input_tokens" if provider == "vertex-v1" else "inputTokens": 12})
        return httpx.Response(
            200,
            json={
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "answer"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 12, "output_tokens": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        adapter = MessagesProvider(
            target=target(provider), limits=_limits(), credentials=CredentialsPort(), client=client
        )
        bound = adapter.message_billing_bound(message(), count_only=False)
        assert bound.amounts[0].units == 200_000  # full model context; no character-count estimate
        contract_bound = adapter.billing_bound(model=target(provider).model, features=("messages",), request_bytes=20)
        assert contract_bound.amounts[0].units == bound.amounts[0].units
        assert contract_bound.amounts[1].units == _limits().max_output_tokens
        free_count = adapter.billing_bound(model=target(provider).model, features=("token-count",), request_bytes=20)
        assert [(amount.component, amount.units) for amount in free_count.amounts] == [("request", 1)]
        with pytest.raises(ContractError, match=r"provider\.capability_mismatch"):
            adapter.billing_bound(model="unapproved-model", features=("messages",), request_bytes=20)
        async with adapter.invoke(message(), count_only=False, before_transport=lease) as result:
            raw = b"".join([chunk async for chunk in result.chunks])
        assert json.loads(raw)["content"][0]["text"] == "answer"
        assert [(item.component, item.units) for item in result.usage.items] == [
            ("input_tokens", 12),
            ("output_tokens", 5),
        ]
    assert len(calls) == 2
    invoke = json.loads(calls[1].content)
    assert "model" not in invoke
    if provider == "vertex-v1":
        assert calls[0].url.host == "aiplatform.us.rep.googleapis.com"
        assert calls[1].url.host == "us-east5-aiplatform.googleapis.com"
        assert invoke["anthropic_version"] == "vertex-2023-10-16"
    else:
        assert all(request.url.host == "bedrock-runtime.us-east-1.amazonaws.com" for request in calls)
        assert "stream" not in invoke
        prompt = json.loads(base64.b64decode(json.loads(calls[0].content)["input"]["invokeModel"]["body"]))
        assert prompt["messages"][0]["content"] == "test"
        assert invoke["anthropic_version"] == "bedrock-2023-05-31"


@pytest.mark.parametrize(
    "status,code",
    [
        (429, "provider.rate_limited"),
        (503, "provider.unavailable"),
        (500, "provider.unavailable"),
        (403, "provider.unavailable"),
        (400, "provider.invalid_request"),
    ],
)
async def test_provider_error_status_is_normalized_without_leaking_diagnostics(status, code):
    def transport(request):
        if "count-tokens" in request.url.path:
            return httpx.Response(200, json={"input_tokens": 12})
        return httpx.Response(status, json={"error": {"message": "secret-upstream-diagnostic"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        adapter = MessagesProvider(
            target=target("vertex-v1"), limits=_limits(), credentials=CredentialsPort(), client=client
        )
        with pytest.raises(ContractError) as err:
            async with adapter.invoke(message(), count_only=False, before_transport=lease):
                pytest.fail("provider error yielded a response")
    assert err.value.code == code
    assert "secret-upstream-diagnostic" not in str(err.value)


async def test_message_response_contract_rejects_unqualified_blocks_but_tolerates_additive_fields():
    from model_broker.provider_usage import validate_message_response

    # A qualified reply (text + local tool_use blocks) with a benign additive top-level
    # field passes; the additive field is tolerated so a working range is not blocked.
    validate_message_response(
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "id": "t1", "name": "read", "input": {}}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 3},
            "container": {"id": "benign-additive"},
        }
    )
    usage = {"input_tokens": 1, "output_tokens": 1}
    for malformed in (
        # Unqualified, cost/semantics-changing block is rejected, not admitted.
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "…"}],
            "stop_reason": "end_turn",
            "usage": usage,
        },
        {
            "type": "error",
            "role": "assistant",
            "content": [{"type": "text", "text": "x"}],
            "stop_reason": "end_turn",
            "usage": usage,
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "text", "text": "x"}],
            "stop_reason": "end_turn",
            "usage": usage,
        },
        {"type": "message", "role": "assistant", "content": [], "stop_reason": "end_turn", "usage": usage},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "x"}],
            "usage": usage,
        },  # no stop_reason
        {"type": "message", "role": "assistant", "content": "not-a-list", "stop_reason": "end_turn", "usage": usage},
        # An unknown field inside a qualified block is rejected by the closed block contract.
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}],
            "stop_reason": "end_turn",
            "usage": usage,
        },
    ):
        with pytest.raises(ContractError, match="invalid_response"):
            validate_message_response(malformed)


async def test_stream_usage_rejects_unqualified_streamed_blocks_and_deltas():
    from model_broker.provider_usage import StreamUsage

    rejecting = StreamUsage()
    rejecting.observe({"type": "message_start", "message": {"usage": {"input_tokens": 1}}})
    with pytest.raises(ContractError, match="invalid_stream"):
        rejecting.observe({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}})

    ok = StreamUsage()
    ok.observe({"type": "message_start", "message": {"usage": {"input_tokens": 1}}})
    ok.observe({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
    ok.observe({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}})
    with pytest.raises(ContractError, match="invalid_stream"):
        ok.observe({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "x"}})


async def test_revocation_between_count_and_invoke_prevents_paid_transport():
    calls = []

    async def before_transport():
        if calls:
            raise ContractError("request.revoked")
        return await lease()

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"input_tokens": 12})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        adapter = MessagesProvider(
            target=target("vertex-v1"), limits=_limits(), credentials=CredentialsPort(), client=client
        )
        with pytest.raises(ContractError):
            async with adapter.invoke(message(), count_only=False, before_transport=before_transport):
                pytest.fail("revoked invocation yielded a provider response")
    assert len(calls) == 1 and "count-tokens" in calls[0].url.path


async def test_vertex_count_can_use_the_same_regional_endpoint_as_inference():
    configured = ProviderTarget.model_validate({**target("vertex-v1").model_dump(), "count_region": "us-east5"})
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"input_tokens": 2})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        adapter = MessagesProvider(target=configured, limits=_limits(), credentials=CredentialsPort(), client=client)
        async with adapter.invoke(message(), count_only=True, before_transport=lease) as result:
            assert json.loads(b"".join([chunk async for chunk in result.chunks])) == {"input_tokens": 2}
    assert calls[0].url.host == "us-east5-aiplatform.googleapis.com"


async def test_short_lease_never_starts_provider_transport():
    async def expired():
        return (datetime.now(UTC) + timedelta(seconds=1)).isoformat()

    def forbidden(request):
        pytest.fail("expired lease reached network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        adapter = MessagesProvider(
            target=target("vertex-v1"), limits=_limits(), credentials=CredentialsPort(), client=client
        )
        with pytest.raises(ContractError, match="count_unavailable"):
            async with adapter.invoke(message(), count_only=False, before_transport=expired):
                pytest.fail("expired lease returned a response")


def _aws_frame(event):
    def header(name, value):
        return bytes([len(name)]) + name.encode() + b"\x07" + struct.pack(">H", len(value)) + value.encode()

    headers = header(":message-type", "event") + header(":event-type", "chunk")
    payload = json.dumps({"bytes": base64.b64encode(json.dumps(event).encode()).decode()}).encode()
    prelude = struct.pack(">II", 16 + len(headers) + len(payload), len(headers))
    raw = prelude + struct.pack(">I", zlib.crc32(prelude)) + headers + payload
    return raw + struct.pack(">I", zlib.crc32(raw))


@pytest.mark.parametrize("provider", ["vertex-v1", "bedrock-v1"])
async def test_fragmented_stream_frames_require_complete_verified_usage(provider):
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
        {"type": "message_delta", "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]
    if provider == "vertex-v1":
        raw = b"".join(b"data: " + json.dumps(event).encode() + b"\r\n\r\n" for event in events)
    else:
        raw = b"".join(_aws_frame(event) for event in events)

    async def chunks():
        for index in range(0, len(raw), 7):
            yield raw[index : index + 7]

    tracker = StreamUsage()
    decoder = vertex_events if provider == "vertex-v1" else bedrock_events
    observed = []
    async for event in decoder(chunks()):
        tracker.observe(event)
        observed.append(event)
    assert observed == events
    assert [item.units for item in tracker.result().items] == [12, 5]
    incomplete = StreamUsage()
    incomplete.observe(events[0])
    incomplete.observe(events[1])
    with pytest.raises(ContractError):
        incomplete.result()


async def test_corrupt_aws_crc_is_rejected():
    raw = bytearray(_aws_frame({"type": "message_stop"}))
    raw[-1] ^= 1

    async def chunks():
        yield bytes(raw)

    with pytest.raises(ChecksumMismatch, match="Checksum mismatch"):
        [event async for event in bedrock_events(chunks())]


async def test_undeclared_cache_write_cannot_be_refunded_as_ordinary_input():
    with pytest.raises(ContractError, match="undeclared_cache_write"):
        usage_from_message({"usage": {"input_tokens": 5, "output_tokens": 1, "cache_creation_input_tokens": 100}})


async def test_broker_entry_import_does_not_initialize_application_or_database():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(  # noqa: S603 - current interpreter and fixed, repository-owned import probe.
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, {str(root)!r}); import model_broker.__main__; "
            "assert not {'django', 'psycopg', 'redis', 'config.settings', 'engine.models'} & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


async def test_direct_anthropic_uses_owned_key_and_fixed_messages_and_count_routes():
    from model_broker.provider_credentials import ProviderCredentials

    configured = ProviderTarget(
        shard_id="direct",
        provider="anthropic-v1",
        authentication="stored-credential",
        region="provider-managed",
        model="synthetic-model",
        credential_reference="source:00000000-0000-0000-0000-000000000001:1",
        principal="",
        context_window_tokens=200_000,
    )
    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.host == "api.anthropic.com"
        assert request.headers["x-api-key"] == "synthetic-owned-key"
        assert json.loads(request.content)["model"] == "synthetic-model"
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 12})
        return httpx.Response(
            200,
            json={
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "answer"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 12, "output_tokens": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        adapter = MessagesProvider(
            target=configured,
            limits=_limits(),
            client=client,
            credentials=ProviderCredentials(credential={"api_key": "synthetic-owned-key"}),
        )
        async with adapter.invoke(message(), count_only=False, before_transport=lease) as result:
            raw = b"".join([chunk async for chunk in result.chunks])
        assert json.loads(raw)["content"][0]["text"] == "answer"
        assert [(item.component, item.units) for item in result.usage.items] == [
            ("input_tokens", 12),
            ("output_tokens", 5),
        ]
    assert [request.url.path for request in calls] == ["/v1/messages/count_tokens", "/v1/messages"]


async def test_direct_openai_counts_complete_prompt_and_preserves_local_tools():
    calls = []
    bound = ProviderTarget(
        shard_id="source-test",
        provider="openai-v1",
        authentication="stored-credential",
        region="provider-managed",
        model="gpt-synthetic",
        credential_reference="source:11111111-1111-4111-8111-111111111111:1",
        principal="",
        context_window_tokens=200_000,
    )
    prompt = parse_messages(
        json.dumps(
            {
                "model": "coding-main",
                "max_tokens": 32,
                "system": "Be concise",
                "messages": [{"role": "user", "content": "read it"}],
                "tools": [{"name": "read", "description": "Read local text", "input_schema": {"type": "object"}}],
                "tool_choice": {"type": "any"},
            }
        ).encode(),
        count_only=False,
        limits=_limits(),
    )

    def transport(request):
        calls.append(request)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 20})
        return httpx.Response(
            200,
            json={
                "id": "resp-synthetic",
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-synthetic",
                        "name": "read",
                        "arguments": '{"path":"example.txt"}',
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 12, "output_tokens_details": {"reasoning_tokens": 8}},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        adapter = MessagesProvider(target=bound, limits=_limits(), credentials=CredentialsPort(), client=client)
        async with adapter.invoke(prompt, count_only=False, before_transport=lease) as result:
            reply = json.loads(b"".join([part async for part in result.chunks]))
    assert [(r.url.host, r.url.path) for r in calls] == [
        ("api.openai.com", "/v1/responses/input_tokens"),
        ("api.openai.com", "/v1/responses"),
    ]
    count, invoke = [json.loads(r.content) for r in calls]
    assert count["tools"] == invoke["tools"] and count["input"] == invoke["input"]
    assert invoke["store"] is False and invoke["truncation"] == "disabled"
    assert invoke["model"] == "gpt-synthetic" and invoke["tool_choice"] == "required"
    assert reply["content"][0] == {
        "type": "tool_use",
        "id": "call-synthetic",
        "name": "read",
        "input": {"path": "example.txt"},
    }
    assert reply["stop_reason"] == "tool_use"
    assert [(item.component, item.units) for item in result.usage.items] == [
        ("input_tokens", 20),
        ("output_tokens", 12),
    ]


async def test_openai_stream_translates_text_and_requires_terminal_usage():
    bound = ProviderTarget(
        shard_id="source-test",
        provider="openai-v1",
        authentication="stored-credential",
        region="provider-managed",
        model="gpt-synthetic",
        credential_reference="source:11111111-1111-4111-8111-111111111111:1",
        principal="",
        context_window_tokens=200_000,
    )
    events = [
        {"type": "response.created", "response": {"id": "resp-stream"}},
        {"type": "response.output_item.added", "output_index": 0, "item": {"type": "message"}},
        {
            "type": "response.content_part.added",
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": ""},
        },
        {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "answer"},
        {"type": "response.content_part.done", "output_index": 0, "content_index": 0},
        {
            "type": "response.completed",
            "response": {
                "id": "resp-stream",
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}],
                "usage": {"input_tokens": 12, "output_tokens": 5},
            },
        },
    ]

    def transport(request):
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 12})
        return httpx.Response(200, content=b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events))

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        adapter = MessagesProvider(target=bound, limits=_limits(), credentials=CredentialsPort(), client=client)
        async with adapter.invoke(message(stream=True), count_only=False, before_transport=lease) as result:
            reply = b"".join([part async for part in result.chunks])
        assert b'"text":"answer"' in reply and b"event: message_stop" in reply
        assert [(item.component, item.units) for item in result.usage.items] == [
            ("input_tokens", 12),
            ("output_tokens", 5),
        ]
        events.pop()
        with pytest.raises(ContractError, match="incomplete_usage"):
            async with adapter.invoke(message(stream=True), count_only=False, before_transport=lease) as result:
                _ = b"".join([part async for part in result.chunks])
        assert result.usage is None


async def test_openrouter_pins_upstream_without_inventing_a_count_endpoint():
    calls = []
    bound = ProviderTarget(
        shard_id="source-test",
        provider="openrouter-v1",
        authentication="stored-credential",
        region="provider-managed",
        model="vendor/synthetic",
        credential_reference="source:11111111-1111-4111-8111-111111111111:1",
        principal="",
        context_window_tokens=200_000,
    )
    limits = _limits().model_copy(update={"max_input_tokens": 200_000})

    def transport(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "answer"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 12, "output_tokens": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        adapter = MessagesProvider(
            target=bound, limits=limits, credentials=CredentialsPort(), client=client, upstream_provider="Synthetic"
        )
        assert adapter.capabilities().token_counting is False
        async with adapter.invoke(message(), count_only=False, before_transport=lease) as result:
            _ = b"".join([part async for part in result.chunks])
        assert len(calls) == 1 and str(calls[0].url) == "https://openrouter.ai/api/v1/messages"
        payload = json.loads(calls[0].content)
        assert payload["provider"] == {
            "only": ["Synthetic"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        }
        with pytest.raises(ContractError, match="count_unsupported"):
            async with adapter.invoke(message(), count_only=True, before_transport=lease):
                pytest.fail("Unsupported counting returned a fabricated count")
        assert len(calls) == 1
        adapter.limits = _limits()
        with pytest.raises(ContractError, match="input_limit"):
            async with adapter.invoke(message(), count_only=False, before_transport=lease):
                pytest.fail("A source without counting exceeded the admitted input envelope")
        assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["output_item", "content", "part", "part_type", "incomplete"])
async def test_malformed_openai_reply_fails_with_bounded_contract_error(mutation):
    from model_broker.openai_messages import response_message

    reply = {"status": "completed", "usage": {"input_tokens": 2, "output_tokens": 3}, "output": []}
    if mutation == "output_item":
        reply["output"] = [None]
    elif mutation == "content":
        reply["output"] = [{"type": "message", "content": "unexpected-private-provider-text"}]
    elif mutation == "part":
        reply["output"] = [{"type": "message", "content": [None]}]
    elif mutation == "part_type":
        reply["output"] = [{"type": "message", "content": [{"type": ["unexpected-private-provider-text"]}]}]
    else:
        reply.update(status="incomplete", incomplete_details="unexpected-private-provider-text")
    with pytest.raises(ContractError) as error:
        response_message(reply, model="synthetic")
    assert "unexpected-private-provider-text" not in str(error.value)


async def test_openai_stream_preserves_local_tool_arguments_and_usage():
    from model_broker.openai_messages import responses_events

    item = {"type": "function_call", "call_id": "call-synthetic", "name": "read", "arguments": '{"path":"example.txt"}'}
    events = [
        {"type": "response.created", "response": {"id": "response-synthetic"}},
        {"type": "response.output_item.added", "output_index": 0, "item": {**item, "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"path":'},
        {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '"example.txt"}'},
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {
            "type": "response.completed",
            "response": {"status": "completed", "output": [item], "usage": {"input_tokens": 4, "output_tokens": 7}},
        },
    ]

    async def chunks():
        for event in events:
            yield b"data: " + json.dumps(event).encode() + b"\n\n"

    translated = [event async for event in responses_events(chunks(), model="synthetic")]
    assert translated[1]["content_block"] == {"type": "tool_use", "id": "call-synthetic", "name": "read", "input": {}}
    fragments = [event["delta"]["partial_json"] for event in translated if event["type"] == "content_block_delta"]
    assert json.loads("".join(fragments)) == {"path": "example.txt"}
    assert translated[-2]["usage"] == {"input_tokens": 4, "output_tokens": 7}
    events[2]["output_index"] = True
    with pytest.raises(ContractError, match="invalid_stream"):
        _ = [event async for event in responses_events(chunks(), model="synthetic")]
