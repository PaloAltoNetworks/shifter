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

from cloud.exceptions import CloudStorageError, ObjectPreconditionError
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


class _FakePreconditionFailed(Exception):
    """Stand-in for google.api_core.exceptions.PreconditionFailed."""


def _install_fake_google_storage(storage_client):
    """Inject fake ``google.cloud.storage`` + ``google.api_core.exceptions`` modules.

    Used by head_object/download_object tests: the adapter resolves both SDK
    surfaces only through ``import_google_module`` -> ``importlib.import_module``,
    so populating sys.modules patches the real cloud boundary (google-cloud-storage
    and google-api-core are optional dependencies absent from the base provisioner
    venv, same as the presigned-URL tests above).
    """
    storage_module = ModuleType("google.cloud.storage")
    storage_module.Client = MagicMock(return_value=storage_client)

    api_core_module = ModuleType("google.api_core")
    exceptions_module = ModuleType("google.api_core.exceptions")
    exceptions_module.PreconditionFailed = _FakePreconditionFailed

    fake_modules = {
        "google": ModuleType("google"),
        "google.cloud": ModuleType("google.cloud"),
        "google.cloud.storage": storage_module,
        "google.api_core": api_core_module,
        "google.api_core.exceptions": exceptions_module,
    }
    return patch.dict(sys.modules, fake_modules)


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

    def test_download_url_binds_generation_when_supplied(self):
        # #1644: the POLARIS tarball URL is bound to the exact immutable object
        # generation so a swap after signing fails closed. The neutral selector is
        # an opaque string; GCS parses its numeric generation from it.
        storage = GCPObjectStorage()
        fake_client, _fake_blob = _client_returning("https://signed/get")
        creds = self._wi_credentials()

        with _install_fake_google(fake_client, MagicMock(return_value=(creds, "proj"))):
            storage.generate_presigned_download_url("b", "k", 600, object_version="42")

        assert fake_client.bucket.return_value.blob.call_args.kwargs["generation"] == 42

    def test_download_url_leaves_generation_unbound_by_default(self):
        storage = GCPObjectStorage()
        fake_client, _fake_blob = _client_returning("https://signed/get")
        creds = self._wi_credentials()

        with _install_fake_google(fake_client, MagicMock(return_value=(creds, "proj"))):
            storage.generate_presigned_download_url("b", "k", 600)

        assert fake_client.bucket.return_value.blob.call_args.kwargs["generation"] is None

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


class TestHeadObjectIdentity:
    def test_exposes_generation_alongside_size_and_etag(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.size = 42
        fake_blob.etag = "etag-value"
        fake_blob.generation = 1720000000000001
        fake_client.bucket.return_value.get_blob.return_value = fake_blob

        with _install_fake_google_storage(fake_client):
            identity = storage.head_object("b", "k")

        assert identity == {
            "content_length": 42,
            "etag": "etag-value",
            "generation": 1720000000000001,
        }

    def test_missing_object_maps_to_cloud_storage_error(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_client.bucket.return_value.get_blob.return_value = None

        with _install_fake_google_storage(fake_client), pytest.raises(CloudStorageError):
            storage.head_object("b", "k")


class TestDownloadObject:
    @staticmethod
    def _blob_writing(payload: bytes, *, size: int | None = None, generation: int = 777):
        blob = MagicMock()
        blob.etag = "e"
        blob.generation = generation
        # GCS reports the authoritative size; the resolver uses it (from the head
        # identity or a reload) to bound the transfer before writing.
        blob.size = len(payload) if size is None else size

        def _download(fh, **kwargs):
            fh.write(payload)

        blob.download_to_file.side_effect = _download
        return blob

    def test_downloads_with_head_identity_without_reload(self, tmp_path):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = self._blob_writing(b"packbytes")
        fake_client.bucket.return_value.blob.return_value = fake_blob
        dest = tmp_path / "pkg.tar"

        with _install_fake_google_storage(fake_client):
            identity = storage.download_object(
                "b", "k", str(dest), max_bytes=1024, expected_identity={"generation": 777, "content_length": 9}
            )

        assert dest.read_bytes() == b"packbytes"
        assert identity == {"content_length": 9, "etag": "e", "generation": 777}
        # Head identity carried the size, so no extra metadata round-trip.
        fake_blob.reload.assert_not_called()
        # Bind the download to the validated generation (TOCTOU).
        assert fake_blob.download_to_file.call_args.kwargs["if_generation_match"] == 777

    def test_rejects_when_head_size_exceeds_max_bytes_without_leaving_oversize_file(self, tmp_path):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = self._blob_writing(b"x" * 10)
        fake_client.bucket.return_value.blob.return_value = fake_blob
        dest = tmp_path / "big.tar"
        dest_str = str(dest)

        with _install_fake_google_storage(fake_client), pytest.raises(CloudStorageError):
            storage.download_object("b", "k", dest_str, max_bytes=1024, expected_identity={"content_length": 5000})

        # Fail closed before touching the network: no oversize file left behind.
        fake_blob.download_to_file.assert_not_called()
        assert not dest.exists()

    def test_reloads_for_size_and_downloads_without_identity(self, tmp_path):
        # No head identity: the resolver reloads to learn the authoritative size
        # and generation, then downloads bound to that generation.
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = self._blob_writing(b"packbytes", size=9, generation=555)
        fake_client.bucket.return_value.blob.return_value = fake_blob
        dest = tmp_path / "pkg.tar"

        with _install_fake_google_storage(fake_client):
            storage.download_object("b", "k", str(dest), max_bytes=1024)

        fake_blob.reload.assert_called_once()
        assert dest.read_bytes() == b"packbytes"
        assert fake_blob.download_to_file.call_args.kwargs["if_generation_match"] == 555

    def test_precondition_failure_maps_to_object_precondition_error(self, tmp_path):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = self._blob_writing(b"packbytes", size=9)
        fake_blob.download_to_file.side_effect = _FakePreconditionFailed("generation mismatch")
        fake_client.bucket.return_value.blob.return_value = fake_blob
        dest = str(tmp_path / "x.tar")

        with (
            _install_fake_google_storage(fake_client),
            pytest.raises(ObjectPreconditionError),
        ):
            storage.download_object("b", "k", dest, max_bytes=1024, expected_identity={"generation": 777})

    def test_other_failure_maps_to_cloud_storage_error(self, tmp_path):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = self._blob_writing(b"packbytes", size=9)
        fake_blob.download_to_file.side_effect = RuntimeError("transport error")
        fake_client.bucket.return_value.blob.return_value = fake_blob
        dest = str(tmp_path / "x.tar")

        with (
            _install_fake_google_storage(fake_client),
            pytest.raises(CloudStorageError) as exc,
        ):
            storage.download_object("b", "k", dest, max_bytes=1024, expected_identity={"content_length": 9})
        assert not isinstance(exc.value, ObjectPreconditionError)

    def test_rejects_non_positive_max_bytes(self, tmp_path):
        storage = GCPObjectStorage()
        dest = str(tmp_path / "x")
        with pytest.raises(ValueError):
            storage.download_object("b", "k", dest, max_bytes=0)
