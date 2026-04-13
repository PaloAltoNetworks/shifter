"""Tests for the GCP object storage adapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from shared.cloud.gcp.storage import GCPObjectStorage


class TestSignedUrlKwargs:
    def test_uses_iam_signing_inputs_for_workload_identity_credentials(self, monkeypatch):
        storage = GCPObjectStorage()
        credentials = SimpleNamespace(
            service_account_email="portal@test-project.iam.gserviceaccount.com",
            token=None,
            expired=False,
        )
        refresh = Mock(side_effect=lambda request: setattr(credentials, "token", "fresh-access-token"))
        credentials.refresh = refresh
        client = SimpleNamespace(_credentials=credentials)

        request_factory = Mock(return_value="request-sentinel")
        transport_requests = SimpleNamespace(Request=request_factory)
        import_google_module = Mock(return_value=transport_requests)
        monkeypatch.setattr("shared.cloud.gcp.storage.import_google_module", import_google_module)

        result = storage._signed_url_kwargs(client)

        assert result == {
            "version": "v4",
            "service_account_email": "portal@test-project.iam.gserviceaccount.com",
            "access_token": "fresh-access-token",
        }
        import_google_module.assert_called_once_with("google.auth.transport.requests")
        request_factory.assert_called_once_with()
        refresh.assert_called_once_with("request-sentinel")

    def test_uses_existing_token_without_refresh(self, monkeypatch):
        storage = GCPObjectStorage()
        credentials = SimpleNamespace(
            service_account_email="portal@test-project.iam.gserviceaccount.com",
            token="cached-token",
            expired=False,
            refresh=Mock(),
        )
        client = SimpleNamespace(_credentials=credentials)

        import_google_module = Mock()
        monkeypatch.setattr("shared.cloud.gcp.storage.import_google_module", import_google_module)

        result = storage._signed_url_kwargs(client)

        assert result == {
            "version": "v4",
            "service_account_email": "portal@test-project.iam.gserviceaccount.com",
            "access_token": "cached-token",
        }
        credentials.refresh.assert_not_called()
        import_google_module.assert_not_called()

    def test_refreshes_when_metadata_credentials_still_report_default_email(self, monkeypatch):
        storage = GCPObjectStorage()
        credentials = SimpleNamespace(
            service_account_email="default",
            token="cached-token",
            expired=False,
        )

        def _refresh(_request):
            credentials.service_account_email = "portal@test-project.iam.gserviceaccount.com"

        credentials.refresh = Mock(side_effect=_refresh)
        client = SimpleNamespace(_credentials=credentials)

        request_factory = Mock(return_value="request-sentinel")
        transport_requests = SimpleNamespace(Request=request_factory)
        import_google_module = Mock(return_value=transport_requests)
        monkeypatch.setattr("shared.cloud.gcp.storage.import_google_module", import_google_module)

        result = storage._signed_url_kwargs(client)

        assert result == {
            "version": "v4",
            "service_account_email": "portal@test-project.iam.gserviceaccount.com",
            "access_token": "cached-token",
        }
        import_google_module.assert_called_once_with("google.auth.transport.requests")
        request_factory.assert_called_once_with()
        credentials.refresh.assert_called_once_with("request-sentinel")

    def test_returns_empty_kwargs_when_credentials_have_no_service_account_email(self):
        storage = GCPObjectStorage()
        client = SimpleNamespace(_credentials=SimpleNamespace(token="token"))

        assert storage._signed_url_kwargs(client) == {}


class TestGenerateSignedUrls:
    def test_generate_presigned_upload_url_passes_iam_signing_kwargs(self, monkeypatch):
        storage = GCPObjectStorage()
        blob = Mock()
        blob.generate_signed_url.return_value = "https://upload.example.test"
        client = Mock()
        client.bucket.return_value.blob.return_value = blob

        monkeypatch.setattr(storage, "_get_client", lambda: client)
        monkeypatch.setattr(
            storage,
            "_signed_url_kwargs",
            lambda supplied_client: {
                "version": "v4",
                "service_account_email": "portal@test-project.iam.gserviceaccount.com",
                "access_token": "token-123",
            },
        )

        result = storage.generate_presigned_upload_url(
            bucket="bucket-name",
            key="agents/test.bin",
            content_type="application/octet-stream",
            expires_in=900,
        )

        assert result == "https://upload.example.test"
        blob.generate_signed_url.assert_called_once()
        kwargs = blob.generate_signed_url.call_args.kwargs
        assert kwargs["method"] == "PUT"
        assert kwargs["content_type"] == "application/octet-stream"
        assert kwargs["version"] == "v4"
        assert kwargs["service_account_email"] == "portal@test-project.iam.gserviceaccount.com"
        assert kwargs["access_token"] == "token-123"

    def test_generate_presigned_download_url_passes_iam_signing_kwargs(self, monkeypatch):
        storage = GCPObjectStorage()
        blob = Mock()
        blob.generate_signed_url.return_value = "https://download.example.test"
        client = Mock()
        client.bucket.return_value.blob.return_value = blob

        monkeypatch.setattr(storage, "_get_client", lambda: client)
        monkeypatch.setattr(
            storage,
            "_signed_url_kwargs",
            lambda supplied_client: {
                "version": "v4",
                "service_account_email": "portal@test-project.iam.gserviceaccount.com",
                "access_token": "token-123",
            },
        )

        result = storage.generate_presigned_download_url(
            bucket="bucket-name",
            key="agents/test.bin",
            expires_in=900,
        )

        assert result == "https://download.example.test"
        blob.generate_signed_url.assert_called_once()
        kwargs = blob.generate_signed_url.call_args.kwargs
        assert kwargs["method"] == "GET"
        assert kwargs["version"] == "v4"
        assert kwargs["service_account_email"] == "portal@test-project.iam.gserviceaccount.com"
        assert kwargs["access_token"] == "token-123"
