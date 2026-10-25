"""Uploaded cloud credentials cannot choose token endpoints or target identities."""

import pytest

from shared.model_access import ContractError


def test_bedrock_rejects_extra_credential_fields_and_accepts_explicit_keys():
    from shared.model_access.source_credentials import parse_source_credential

    valid = {"access_key_id": "A" * 20, "secret_access_key": "x" * 40}
    assert parse_source_credential("bedrock-v1", valid).access_key_id == "A" * 20
    with pytest.raises(ContractError):
        parse_source_credential("bedrock-v1", {**valid, "endpoint_url": "http://127.0.0.1"})


def test_vertex_rejects_arbitrary_oauth_endpoints_without_echoing_private_key():
    from shared.model_access.source_credentials import parse_source_credential

    value = {
        "type": "service_account",
        "project_id": "models-example",
        "private_key_id": "id",
        "private_key": "synthetic-private-sentinel",
        "client_email": "model-invoke@models-example.iam.gserviceaccount.com",
        "token_uri": "http://169.254.169.254/token",
    }
    with pytest.raises(ContractError) as error:
        parse_source_credential("vertex-v1", value)
    assert "synthetic-private-sentinel" not in str(error.value)
    assert error.value.__cause__ is None


def test_vertex_accepts_a_parseable_key_bound_to_the_selected_principal():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from shared.model_access.source_credentials import parse_source_credential

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    value = {
        "type": "service_account",
        "project_id": "models-example",
        "private_key_id": "synthetic",
        "private_key": pem,
        "client_email": "model-invoke@models-example.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    parsed = parse_source_credential("vertex-v1", value)
    assert parsed.project_id == "models-example" and pem not in repr(parsed)
    with pytest.raises(ContractError):
        parse_source_credential("vertex-v1", {**value, "private_key": "malformed-private-sentinel"})
