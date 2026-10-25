"""Closed transient credentials; no caller-selected OAuth or SDK endpoints."""

from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, model_validator

from shared.model_access import ContractError
from shared.model_access.core_models import ClosedModel
from shared.model_access.sources import ModelSourceConfiguration

INVALID_SERVICE_ACCOUNT = "invalid service account credential"


class APIKeyCredential(ClosedModel):
    """Bounded printable provider API key, kept secret in representations."""

    api_key: SecretStr

    @model_validator(mode="after")
    def validate_key(self) -> Self:
        key = self.api_key.get_secret_value()
        if not 1 <= len(key) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError("invalid API credential")
        return self


class AWSKeyCredential(ClosedModel):
    """AWS access credentials with an optional bounded session token."""

    access_key_id: Annotated[str, Field(pattern=r"^[A-Z0-9]{16,128}$")]
    secret_access_key: SecretStr
    session_token: SecretStr | None = None

    @model_validator(mode="after")
    def validate_keys(self) -> Self:
        for value, minimum, maximum in [(self.secret_access_key, 32, 256), (self.session_token, 1, 8192)]:
            if value is not None:
                raw = value.get_secret_value()
                if not minimum <= len(raw) <= maximum or any(ord(c) < 33 or ord(c) > 126 for c in raw):
                    raise ValueError("invalid AWS credential")
        return self


class GoogleKeyCredential(ClosedModel):
    """Closed Google service account credential with fixed OAuth destinations."""

    type: Literal["service_account"]
    project_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")]
    private_key_id: Annotated[str, Field(min_length=1, max_length=256)]
    private_key: SecretStr
    client_email: Annotated[
        str, Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$")
    ]
    client_id: Annotated[str, Field(max_length=128)] = ""
    token_uri: Literal["https://oauth2.googleapis.com/token"]
    auth_uri: Literal["https://accounts.google.com/o/oauth2/auth"] = "https://accounts.google.com/o/oauth2/auth"
    auth_provider_x509_cert_url: Literal["https://www.googleapis.com/oauth2/v1/certs"] = (
        "https://www.googleapis.com/oauth2/v1/certs"
    )
    client_x509_cert_url: Annotated[str, Field(max_length=1024)] = ""
    universe_domain: Literal["googleapis.com"] = "googleapis.com"

    @model_validator(mode="after")
    def validate_private_key(self) -> Self:
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        raw = self.private_key.get_secret_value()
        if not 1 <= len(raw) <= 16384:
            raise ValueError(INVALID_SERVICE_ACCOUNT)
        try:
            key = load_pem_private_key(raw.encode(), password=None)
        except (ValueError, TypeError):
            raise ValueError(INVALID_SERVICE_ACCOUNT) from None
        if not isinstance(key, RSAPrivateKey) or not 2048 <= key.key_size <= 8192:
            raise ValueError(INVALID_SERVICE_ACCOUNT)
        return self


def parse_source_credential(provider: str, value: object) -> APIKeyCredential | AWSKeyCredential | GoogleKeyCredential:
    """Validate a provider's closed credential shape without echoing secrets."""
    models: dict[str, type[APIKeyCredential] | type[AWSKeyCredential] | type[GoogleKeyCredential]] = {
        "vertex-v1": GoogleKeyCredential,
        "bedrock-v1": AWSKeyCredential,
        "anthropic-v1": APIKeyCredential,
        "openai-v1": APIKeyCredential,
        "openrouter-v1": APIKeyCredential,
    }
    model = models.get(provider)
    try:
        if model is None:
            raise ValueError
        return model.model_validate(value)
    except ValueError:
        raise ContractError("source.invalid_credential") from None


def validate_source_credential(config: ModelSourceConfiguration, value: object) -> None:
    """Bind cloud credentials to the configured source identity."""
    credential = parse_source_credential(config.provider, value)
    if isinstance(credential, GoogleKeyCredential) and (
        credential.client_email != config.principal or credential.project_id != config.project
    ):
        raise ContractError("source.invalid_credential")
