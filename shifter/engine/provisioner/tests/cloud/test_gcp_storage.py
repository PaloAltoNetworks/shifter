"""Tests for the provisioner-side GCS storage adapter.

Per ADR-019-R1 these tests mock only true process/network/cloud boundaries:
the Google Cloud SDK is injected via ``sys.modules`` (the import boundary,
since it is an optional dependency absent from the base provisioner venv).
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from cloud.exceptions import CloudStorageError
from cloud.gcp.storage import GCPObjectStorage


def _install_fake_google(storage_client, auth_default):
    """Inject fake google SDK modules into sys.modules (the import boundary).

    Returns ``(patch_context, generate_signed_url_mock)``. The adapter resolves
    the SDK only through ``import_google_module`` -> ``importlib.import_module``,
    so populating sys.modules patches the real cloud boundary.
    """
    storage_module = ModuleType("google.cloud.storage")
    storage_module.Client = MagicMock(return_value=storage_client)

    auth_module = ModuleType("google.auth")
    auth_module.default = auth_default

    transport_module = ModuleType("google.auth.transport")
    requests_module = ModuleType("google.auth.transport.requests")
    requests_module.Request = MagicMock()

    fake_modules = {
        "google": ModuleType("google"),
        "google.cloud": ModuleType("google.cloud"),
        "google.cloud.storage": storage_module,
        "google.auth": auth_module,
        "google.auth.transport": transport_module,
        "google.auth.transport.requests": requests_module,
    }
    return patch.dict(sys.modules, fake_modules)


def _client_returning(url):
    fake_blob = MagicMock()
    fake_blob.generate_signed_url.return_value = url
    fake_client = MagicMock()
    fake_client.bucket.return_value.blob.return_value = fake_blob
    return fake_client, fake_blob


class TestPresignedDownloadUrlIamSigning:
    """The provisioner signs each instance's XDR agent download URL. Under
    Workload Identity (token-only creds, no private key) it must sign via the
    IAM signBlob API, and locally when a service-account key is present.
    """

    @staticmethod
    def _wi_credentials():
        # Compute/Workload-Identity creds: token only, no local signer.
        creds = MagicMock()
        creds.signer = None
        creds.signer_email = None
        creds.service_account_email = "provisioner@example.iam.gserviceaccount.com"
        creds.token = "wi-access-token"
        return creds

    @staticmethod
    def _key_credentials():
        # Service-account JSON-key creds: can sign locally.
        creds = MagicMock()
        creds.signer = MagicMock()
        creds.signer_email = "key@example.iam.gserviceaccount.com"
        return creds

    def test_download_url_uses_iam_signblob_under_workload_identity(self):
        storage = GCPObjectStorage()
        fake_client, fake_blob = _client_returning("https://signed/get")
        creds = self._wi_credentials()

        with _install_fake_google(fake_client, MagicMock(return_value=(creds, "proj"))):
            url = storage.generate_presigned_download_url("b", "k", 600)

        assert url == "https://signed/get"
        creds.refresh.assert_called_once()
        kwargs = fake_blob.generate_signed_url.call_args.kwargs
        assert kwargs["service_account_email"] == "provisioner@example.iam.gserviceaccount.com"
        assert kwargs["access_token"] == "wi-access-token"
        assert kwargs["method"] == "GET"

    def test_local_key_credentials_sign_without_iam_kwargs(self):
        storage = GCPObjectStorage()
        fake_client, fake_blob = _client_returning("https://signed/get")
        creds = self._key_credentials()

        with _install_fake_google(fake_client, MagicMock(return_value=(creds, "proj"))):
            storage.generate_presigned_download_url("b", "k", 600)

        creds.refresh.assert_not_called()
        kwargs = fake_blob.generate_signed_url.call_args.kwargs
        assert "service_account_email" not in kwargs
        assert "access_token" not in kwargs

    def test_signing_failure_maps_to_cloud_storage_error(self):
        storage = GCPObjectStorage()
        fake_client, fake_blob = _client_returning("https://signed/get")
        fake_blob.generate_signed_url.side_effect = RuntimeError("boom")
        creds = self._wi_credentials()

        with (
            _install_fake_google(fake_client, MagicMock(return_value=(creds, "proj"))),
            pytest.raises(CloudStorageError),
        ):
            storage.generate_presigned_download_url("b", "k", 600)
