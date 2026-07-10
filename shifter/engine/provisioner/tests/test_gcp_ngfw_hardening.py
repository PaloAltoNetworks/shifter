"""PR-1 hardening tests for the GCP VM-Series NGFW path (issue #613).

Two behaviours are locked in here:

1. ``resolve_ngfw_attachment_config`` must not misclassify a GCP NGFW state as
   AWS. A GCP attachment carries a namespaced KubeVirt ``data_attachment_id``
   (``"<ns>/<vm>:eth1"``); the inference fallback must treat that shape as GCP
   rather than assuming any ``data_attachment_id`` implies AWS.
2. The bootstrap GCS object URL and the NGFW next-hop IP must be fingerprinted
   in logs, never emitted in clear text.

Per ADR-019-R1 these tests mock only true process/network/cloud boundaries: the
Google Cloud SDK is injected via ``sys.modules`` (the import boundary, since it
is not installed in the test venv) and ``boto3.client`` is stubbed for the
secrets fetch. No first-party seams are patched.
"""

import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import ngfw_runtime
from config import resolve_ngfw_attachment_config
from gdc_vmseries_assets import _delete_bootstrap_iso, _upload_bootstrap_iso


def _install_fake_gcs(storage_module: ModuleType, exceptions_module: ModuleType):
    """Inject fake google SDK modules into sys.modules (the import boundary)."""
    fake_modules = {
        "google": ModuleType("google"),
        "google.cloud": ModuleType("google.cloud"),
        "google.cloud.storage": storage_module,
        "google.api_core": ModuleType("google.api_core"),
        "google.api_core.exceptions": exceptions_module,
    }
    return patch.dict(sys.modules, fake_modules)


class TestNgfwProviderClassification:
    """resolve_ngfw_attachment_config provider inference (issue #613 gap 1)."""

    def test_explicit_gcp_provider_wins(self, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        config = resolve_ngfw_attachment_config(
            {
                "cloud_provider": "gcp",
                "management_ip": "10.200.0.20",
                "ssh_key_secret_id": "projects/p/secrets/ssh",
                "data_attachment_id": "eni-should-be-ignored",
            }
        )
        assert config.cloud_provider == "gcp"

    def test_gcp_shaped_attachment_without_explicit_provider_is_gcp(self, monkeypatch):
        """The core bug: a GCP-shaped data_attachment_id must not infer AWS."""
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        config = resolve_ngfw_attachment_config(
            {
                "management_ip": "10.200.0.20",
                "ssh_key_secret_id": "projects/p/secrets/ssh",
                "data_attachment_id": "range-ns/ngfw-vm:eth1",
                "route_next_hop_ip": "10.200.1.1",
            }
        )
        assert config.cloud_provider == "gcp"
        assert config.attachment_mode == "gdc-static-route"

    def test_aws_eni_attachment_without_explicit_provider_is_aws(self, monkeypatch):
        """Regression guard: an AWS ENI id must still infer AWS."""
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        config = resolve_ngfw_attachment_config(
            {
                "management_ip": "10.0.0.5",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:...:ssh",
                "data_attachment_id": "eni-0abc123def456",
            }
        )
        assert config.cloud_provider == "aws"
        assert config.attachment_mode == "aws-route-table-eni"

    def test_route_next_hop_only_infers_gcp(self, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        config = resolve_ngfw_attachment_config(
            {
                "management_ip": "10.200.0.20",
                "ssh_key_secret_id": "projects/p/secrets/ssh",
                "route_next_hop_ip": "10.200.1.1",
            }
        )
        assert config.cloud_provider == "gcp"


class TestBootstrapIsoUrlRedaction:
    """Bootstrap GCS object URLs must be fingerprinted, not logged clear-text."""

    _BUCKET = "shifter-gcp-dev-vmseries-bootstrap"
    _INSTANCE = "ngfw-inst-1"

    def _config(self):
        return SimpleNamespace(bootstrap_bucket=self._BUCKET)

    def _storage_module(self):
        module = ModuleType("google.cloud.storage")
        module.Client = MagicMock()
        return module

    def _exceptions_module(self):
        module = ModuleType("google.api_core.exceptions")
        module.NotFound = type("NotFound", (Exception,), {})
        return module

    def test_upload_does_not_log_clear_text_gcs_url(self, caplog):
        storage_module = self._storage_module()
        with (
            _install_fake_gcs(storage_module, self._exceptions_module()),
            caplog.at_level(logging.INFO, logger="gdc_vmseries_assets"),
        ):
            url = _upload_bootstrap_iso(
                config=self._config(),
                request_id="req-1",
                instance_id=self._INSTANCE,
                iso_path=Path("bootstrap.iso"),
            )
        # Prove the function used the injected fake SDK (not the real one) so the
        # log assertion below is meaningful.
        storage_module.Client.assert_called_once()
        # The returned URL still carries the real bucket/key for callers...
        assert self._BUCKET in url
        # ...but the log line must not.
        assert self._BUCKET not in caplog.text
        assert self._INSTANCE not in caplog.text

    def test_delete_does_not_log_clear_text_gcs_url(self, caplog):
        storage_module = self._storage_module()
        url = f"gs://{self._BUCKET}/bootstrap/ngfw/{self._INSTANCE}/bootstrap.iso"
        with (
            _install_fake_gcs(storage_module, self._exceptions_module()),
            caplog.at_level(logging.INFO, logger="gdc_vmseries_assets"),
        ):
            _delete_bootstrap_iso(url)
        storage_module.Client.assert_called()
        assert self._BUCKET not in caplog.text
        assert self._INSTANCE not in caplog.text


class TestNgfwRuntimeIpRedaction:
    """route_next_hop_ip must be fingerprinted in runtime logs (not clear-text).

    Driven to the log line by stubbing the boto3 secrets boundary so the secret
    fetch raises immediately after the next-hop is logged; this avoids the SSH
    poll loop while keeping the mock at a true cloud boundary. The management_ip
    log lines use the identical safe_log_fingerprint() pattern.
    """

    _NEXT_HOP = "10.200.1.1"

    def test_configure_subnets_redacts_next_hop(self, caplog, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        with (
            patch("boto3.client", side_effect=RuntimeError("secrets boundary unavailable")),
            caplog.at_level(logging.INFO, logger="ngfw_runtime"),
            pytest.raises(RuntimeError),
        ):
            ngfw_runtime.configure_ngfw_subnets(
                subnets=[{"cidr": "10.1.0.0/24"}],
                range_id=42,
                management_ip="10.200.0.20",
                ssh_key_secret_arn="projects/p/secrets/ssh",
                route_next_hop_ip=self._NEXT_HOP,
            )
        assert "Configuring NGFW" in caplog.text
        assert self._NEXT_HOP not in caplog.text
