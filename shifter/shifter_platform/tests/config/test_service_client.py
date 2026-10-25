"""Native google-auth refresh across multiple application token expirations."""

import datetime
import json
from unittest.mock import Mock

import pytest
from google.oauth2.credentials import Credentials


def test_official_transport_renews_app_tokens_without_replaying_mutations(monkeypatch):
    from shifter_client import ServiceClient

    source = Credentials(
        "cloud-access", expiry=datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(hours=4)
    )
    monkeypatch.setattr("google.auth.default", lambda **kwargs: (source, "synthetic"))
    client = ServiceClient.from_adc(
        "https://portal.example.test", target_principal="agent@synthetic.iam.gserviceaccount.com"
    )
    native_token = "eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjIwMDAwMDAwMDB9.c2ln"
    # The IAM response is the external seam; token minting and before_request
    # remain the official library implementation (with its JWT expiry parser).
    sent = []
    minted = []
    access_minted = []

    def request(self, method, url, **kwargs):
        if url.startswith("https://iamcredentials.googleapis.com/"):
            if url.endswith(":generateAccessToken"):
                access_minted.append(json.loads(kwargs["data"]))
                return Mock(
                    status_code=200,
                    content=json.dumps(
                        {"accessToken": "native-cloud-token", "expireTime": "2099-01-01T00:00:00Z"}
                    ).encode(),
                )
            minted.append(json.loads(kwargs["data"]))
            return Mock(status_code=200, json=lambda: {"token": native_token})
        sent.append(kwargs)
        return Mock(status_code=200)

    monkeypatch.setattr("requests.Session.request", request)
    for _ in range(3):
        client.application.credentials.expiry = datetime.datetime.now(datetime.UTC).replace(
            tzinfo=None
        ) - datetime.timedelta(seconds=1)
        client.request("POST", "/api/v1/jobs/", json={"synthetic": True})
        client.cloud.credentials.expiry = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(
            seconds=1
        )
        client.cloud.get("https://storage.googleapis.com/storage/v1/b", timeout=30)
    assert len(minted) == 3
    assert all(item["audience"] == "https://portal.example.test" for item in minted)
    assert len(access_minted) == 3
    assert len(sent) == 6
    assert all(item["headers"]["authorization"] == f"Bearer {native_token}" for item in sent[::2])
    assert all(item["headers"]["authorization"] == "Bearer native-cloud-token" for item in sent[1::2])
    assert client.cloud.credentials is not client.application.credentials
    assert source.token == "cloud-access"
    with pytest.raises(ValueError):
        client.request("GET", "https://other.example.test/private")
    client.close()


def test_static_keys_and_untargeted_nonattached_adc_are_rejected(monkeypatch):
    from google.oauth2 import service_account
    from shifter_client import ServiceClient

    for source in (Credentials("human-access"), Mock(spec=service_account.Credentials)):
        monkeypatch.setattr("google.auth.default", lambda result=source, **kwargs: (result, "synthetic"))
        with pytest.raises(ValueError):
            ServiceClient.from_adc("https://portal.example.test")


def test_external_federation_uses_native_subject_exchange_and_impersonation(monkeypatch):
    from google.auth import identity_pool
    from shifter_client import ServiceClient

    source = identity_pool.Credentials(
        audience="//iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/synthetic/providers/synthetic",
        subject_token_type="urn:ietf:params:oauth:token-type:jwt",
        token_url="https://sts.googleapis.com/v1/token",
        credential_source={"url": "https://issuer.example.test/proof"},
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    monkeypatch.setattr("google.auth.default", lambda **kwargs: (source, "synthetic"))
    visited = []
    native_token = "eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjIwMDAwMDAwMDB9.c2ln"

    def request(self, method, url, **kwargs):
        visited.append(url)
        if url == "https://issuer.example.test/proof":
            return Mock(status_code=200, content=b"fresh-external-subject")
        if url.startswith("https://sts.googleapis.com/"):
            assert b"fresh-external-subject" in kwargs["data"]
            return Mock(
                status_code=200,
                content=json.dumps(
                    {"access_token": "federated-access", "expires_in": 3600, "token_type": "Bearer"}
                ).encode(),
            )
        if url.endswith(":generateIdToken"):
            assert kwargs["headers"]["authorization"] == "Bearer federated-access"
            return Mock(status_code=200, json=lambda: {"token": native_token})
        assert kwargs["headers"]["authorization"] == f"Bearer {native_token}"
        return Mock(status_code=200)

    monkeypatch.setattr("requests.Session.request", request)
    client = ServiceClient.from_adc(
        "https://portal.example.test", target_principal="agent@synthetic.iam.gserviceaccount.com"
    )
    assert client.request("GET", "/api/v1/bootstrap/").status_code == 200
    assert visited[:2] == ["https://issuer.example.test/proof", "https://sts.googleapis.com/v1/token"]
    client.close()


def test_attached_workload_uses_native_metadata_identity_endpoint(monkeypatch):
    from google.auth.compute_engine.credentials import Credentials as AttachedCredentials
    from shifter_client import ServiceClient

    monkeypatch.setattr("google.auth.default", lambda **kwargs: (AttachedCredentials(), "synthetic"))
    native_token = "eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjIwMDAwMDAwMDB9.c2ln"
    visited = []

    def request(self, method, url, **kwargs):
        visited.append(url)
        if "computeMetadata/v1/" in url:
            if "/identity?" in url:
                assert "audience=https%3A%2F%2Fportal.example.test" in url
                return Mock(status_code=200, content=native_token.encode(), headers={"content-type": "text/plain"})
            return Mock(
                status_code=200,
                content=json.dumps({"email": "agent@synthetic.iam.gserviceaccount.com"}).encode(),
                headers={"content-type": "application/json"},
            )
        assert kwargs["headers"]["authorization"] == f"Bearer {native_token}"
        return Mock(status_code=200)

    monkeypatch.setattr("requests.Session.request", request)
    client = ServiceClient.from_adc("https://portal.example.test")
    assert client.request("GET", "/api/v1/bootstrap/").status_code == 200
    assert any("/identity?" in url for url in visited)
    client.close()
