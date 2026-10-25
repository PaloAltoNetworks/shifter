"""Signed workload assertions are audience-, issuer- and principal-bound."""

import base64
import io
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from botocore.credentials import Credentials
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt

from shared.model_access import ContractError
from shared.model_access.control_identity import (
    aws_control_assertion,
    verify_aws_control_assertion,
    verify_google_control_assertion,
)

_ROLE = "arn:aws:iam::123456789012:role/synthetic-model-broker"


def _signed_aws():
    return aws_control_assertion(
        credentials=Credentials("AKIASYNTHETICEXAMPLE", "synthetic-signing-key", "session"),
        region="us-east-1",
        audience="control-test",
    )


def _sts_response(arn="arn:aws:sts::123456789012:assumed-role/synthetic-model-broker/session"):
    session = Mock()
    response = Mock(status_code=200)
    response.raw = io.BytesIO(
        f'<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
        f"<GetCallerIdentityResult><Arn>{arn}</Arn></GetCallerIdentityResult>"
        "</GetCallerIdentityResponse>".encode()
    )
    stream = response.raw
    response.raw = Mock()
    response.raw.read.side_effect = lambda amount, decode_content: stream.read(amount)
    session.post.return_value.__enter__ = Mock(return_value=response)
    session.post.return_value.__exit__ = Mock(return_value=False)
    return session


def test_aws_control_uses_fixed_sts_endpoint_and_verifies_returned_role():
    session = _sts_response()
    verify_aws_control_assertion(
        _signed_aws(), region="us-east-1", audience="control-test", expected_role=_ROLE, session=session
    )
    assert session.post.call_args.args == ("https://sts.us-east-1.amazonaws.com",)
    assert session.post.call_args.kwargs["allow_redirects"] is False
    assert session.post.call_args.kwargs["data"] == "Action=GetCallerIdentity&Version=2011-06-15"
    with pytest.raises(ContractError):
        verify_aws_control_assertion(
            _signed_aws(),
            region="us-east-1",
            audience="control-test",
            expected_role=_ROLE,
            session=_sts_response("arn:aws:sts::000000000000:assumed-role/other/session"),
        )


@pytest.mark.parametrize("change", ["host", "audience", "date", "unsigned_audience"])
def test_aws_rejects_unbound_transport_before_any_network(change):
    value = json.loads(base64.urlsafe_b64decode(_signed_aws()[8:]))
    headers = value["headers"]
    if change == "host":
        headers["host"] = "evil.example"
    elif change == "audience":
        headers["x-shifter-audience"] = "another-control"
    elif change == "date":
        headers["x-amz-date"] = "20200101T000000Z"
    else:
        headers["authorization"] = headers["authorization"].replace(";x-shifter-audience", "")
    assertion = "AWS-STS " + base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    session = Mock()
    with pytest.raises(ContractError):
        verify_aws_control_assertion(
            assertion, region="us-east-1", audience="control-test", expected_role=_ROLE, session=session
        )
    session.post.assert_not_called()


@pytest.fixture
def google_signer():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    signer = crypt.RSASigner.from_string(pem, key_id="test-key")
    cert = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    response = Mock(status=200, data=json.dumps({"test-key": cert.decode()}).encode())
    return signer, Mock(return_value=response)


@pytest.mark.parametrize(
    "mutation",
    [
        {},
        {"aud": "other"},
        {"email": "other@example.invalid"},
        {"email_verified": "true"},
        {"iss": "https://evil.example"},
        {"exp": 1},
        {"sub": None},
        {"sub": ""},
        {"sub": "123456789012345678902"},
    ],
)
def test_google_signature_and_exact_claims(google_signer, mutation):
    signer, request = google_signer
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "aud": "control-test",
        "iss": "https://accounts.google.com",
        "iat": now,
        "exp": now + 60,
        "email": "broker@example.invalid",
        "email_verified": True,
        "sub": "123456789012345678901",
        **mutation,
    }
    assertion = "Bearer " + jwt.encode(signer, claims).decode()
    if mutation:
        with pytest.raises(ContractError):
            verify_google_control_assertion(
                assertion,
                audience="control-test",
                expected_subject="broker@example.invalid",
                expected_subject_id="123456789012345678901",
                request=request,
            )
    else:
        verify_google_control_assertion(
            assertion,
            audience="control-test",
            expected_subject="broker@example.invalid",
            expected_subject_id="123456789012345678901",
            request=request,
        )
