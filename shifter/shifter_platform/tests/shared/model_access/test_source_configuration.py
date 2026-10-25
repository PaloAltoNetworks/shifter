"""Tenant source intent is closed, bounded and independent of compute hosting."""

import pytest


@pytest.mark.parametrize(
    "provider,model",
    [
        ("anthropic-v1", "claude-synthetic-20260901"),
        ("openai-v1", "gpt-synthetic-2026-09-01"),
        ("openrouter-v1", "anthropic/claude-synthetic"),
    ],
)
def test_direct_provider_sources_require_owned_credential_references(provider, model):
    from shared.model_access.provider_runtime import ProviderTarget

    target = ProviderTarget(
        shard_id="source-example",
        provider=provider,
        region="provider-managed",
        model=model,
        credential_reference="source:00000000-0000-0000-0000-000000000001:1",
        principal="",
        context_window_tokens=200_000,
        authentication="stored-credential",
    )
    assert target.provider == provider
    with pytest.raises(ValueError):
        ProviderTarget.model_validate({**target.model_dump(), "region": "europe-west4"})
    with pytest.raises(ValueError):
        ProviderTarget.model_validate({**target.model_dump(), "credential_reference": "projects/foreign/secrets/key"})
    with pytest.raises(ValueError):
        ProviderTarget.model_validate({**target.model_dump(), "authentication": "workload-identity"})


def test_source_configuration_never_accepts_an_arbitrary_provider_origin():
    from shared.model_access.sources import ModelSourceConfiguration

    config = {
        "name": "Workshop source",
        "provider": "openai-v1",
        "model": "gpt-synthetic-2026-09-01",
        "region": "provider-managed",
        "authentication": "stored-credential",
        "quota_identity": "account:workshop",
        "input_price_per_million": 1_000_000,
        "output_price_per_million": 3_000_000,
        "price_valid_until": "2027-10-01T00:00:00Z",
        "context_window_tokens": 200_000,
        "tokens_per_minute": 100_000,
    }
    assert ModelSourceConfiguration.model_validate(config).provider == "openai-v1"
    for field, value in [
        ("base_url", "http://169.254.169.254"),
        ("api_key", "synthetic-secret"),
        ("tokens_per_minute", True),
        ("input_price_per_million", -1),
    ]:
        with pytest.raises(ValueError):
            ModelSourceConfiguration.model_validate({**config, field: value})
