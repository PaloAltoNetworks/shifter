"""Exercise the real web-identity credential chain through a fake HTTP transport."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs

import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ReadTimeoutError
from botocore.httpsession import URLLib3Session

from model_broker.provider_credentials import ProviderCredentials
from shared.model_access import ContractError
from shared.model_access.workload_identity import workload_assertion


@pytest.fixture
def aws_transport(monkeypatch, tmp_path):
    import os

    for key in list(os.environ):
        if key.startswith("AWS_"):
            monkeypatch.delenv(key)
    empty = tmp_path / "empty-config"
    empty.write_text("")
    token = tmp_path / "synthetic-web-identity"
    token.write_text("synthetic-workload-assertion")
    for key in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "BOTO_CONFIG"):
        monkeypatch.setenv(key, str(empty))
    monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", str(token))
    monkeypatch.setenv("AWS_ROLE_ARN", "arn:aws:iam::123456789012:role/test-broker")
    monkeypatch.setenv("AWS_ROLE_SESSION_NAME", "synthetic-session")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)
    calls = []

    def send(session, request):
        calls.append((session, request))
        body = request.body.decode() if isinstance(request.body, bytes) else request.body
        action = parse_qs(body)["Action"][0]
        expiry = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        raw = (
            f'<{action}Response xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
            f"<{action}Result><Credentials><AccessKeyId>ASIASYNTHETICEXAMPLE1</AccessKeyId>"
            "<SecretAccessKey>synthetic-signing-key</SecretAccessKey>"
            f"<SessionToken>synthetic-session</SessionToken><Expiration>{expiry}</Expiration>"
            f"</Credentials></{action}Result></{action}Response>"
        ).encode()
        return AWSResponse(request.url, 200, {"content-type": "text/xml"}, SimpleNamespace(stream=lambda: iter([raw])))

    monkeypatch.setattr(URLLib3Session, "send", send)
    return calls


def invoke(surface):
    if surface == "control":
        return workload_assertion(provider="aws", region="us-east-2", audience="shifter-model-control")
    return ProviderCredentials._headers(
        SimpleNamespace(
            provider="bedrock-v1", region="us-east-2", principal="arn:aws:iam::123456789012:role/test-model"
        ),
        url="https://bedrock-runtime.us-east-2.amazonaws.com/model/synthetic/invoke",
        body=b"{}",
    )


@pytest.mark.parametrize("surface", ["control", "provider"])
def test_web_identity_refresh_and_role_assumption_are_bounded_and_regional(aws_transport, surface):
    assert invoke(surface)
    assert len(aws_transport) == (1 if surface == "control" else 2)
    for session, request in aws_transport:
        assert request.url == "https://sts.us-east-2.amazonaws.com/"
        assert session._timeout.connect_timeout == 2
        assert session._timeout.read_timeout == 2


@pytest.mark.parametrize("surface", ["control", "provider"])
def test_credential_transport_failure_is_not_implicitly_retried(aws_transport, monkeypatch, surface):
    attempts = []

    def fail(_session, request):
        attempts.append(request.url)
        raise ReadTimeoutError(endpoint_url=request.url)

    monkeypatch.setattr(URLLib3Session, "send", fail)
    with pytest.raises(ContractError if surface == "control" else ReadTimeoutError):
        invoke(surface)
    assert len(attempts) == 1
