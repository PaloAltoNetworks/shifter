"""Stored provider authentication is distinct from broker hosting identity."""

import pytest

from model_broker.provider_credentials import ProviderCredentials
from shared.model_access import ContractError
from shared.model_access.provider_runtime import ProviderTarget


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,host,header",
    [
        ("anthropic-v1", "api.anthropic.com", "x-api-key"),
        ("openai-v1", "api.openai.com", "authorization"),
        ("openrouter-v1", "openrouter.ai", "authorization"),
    ],
)
async def test_api_key_only_goes_to_the_registered_provider_origin(provider, host, header):
    target = ProviderTarget(
        shard_id="source-test",
        provider=provider,
        authentication="stored-credential",
        region="provider-managed",
        model="synthetic-v1",
        credential_reference="source:00000000-0000-0000-0000-000000000001:1",
        principal="",
        context_window_tokens=200_000,
    )
    credentials = ProviderCredentials(credential={"api_key": "synthetic-key"})
    result = await credentials.headers(target, url=f"https://{host}/v1/messages", body=b"{}")
    assert result[header].endswith("synthetic-key")
    with pytest.raises(ContractError):
        await credentials.headers(target, url="https://foreign.example.test/v1/messages", body=b"{}")
    with pytest.raises(ContractError):
        await credentials.headers(target, url=f"http://{host}/v1/messages", body=b"{}")
