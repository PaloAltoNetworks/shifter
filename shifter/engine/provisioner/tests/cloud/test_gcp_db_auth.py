"""Native database proof renewal and credential-safe failure reporting."""

import logging
import sys
import traceback
from types import ModuleType
from unittest.mock import Mock

import pytest

from cloud.exceptions import CloudDBAuthError
from cloud.gcp.db_auth import GCPDBAuth


def _google_boundary(monkeypatch, credentials):
    auth = ModuleType("google.auth")
    auth.default = Mock(return_value=(credentials, "synthetic-project"))
    transport = ModuleType("google.auth.transport.requests")
    transport.Request = Mock()
    monkeypatch.setitem(sys.modules, "google.auth", auth)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", transport)
    return auth


@pytest.mark.parametrize("stage", ["source", "refresh"])
def test_provider_error_cannot_disclose_credentials(monkeypatch, caplog, stage):
    marker = "synthetic-sensitive-credential-2320"
    credentials = Mock(token="unused")
    auth = _google_boundary(monkeypatch, credentials)
    failing_call = auth.default if stage == "source" else credentials.refresh
    failing_call.side_effect = RuntimeError(marker)
    with caplog.at_level(logging.DEBUG), pytest.raises(CloudDBAuthError) as error:
        GCPDBAuth.generate_auth_token("db.example.test", 5432, "runtime")
    assert marker not in caplog.text
    assert marker not in "".join(traceback.format_exception(error.value))
    assert str(error.value) == "Failed to generate Cloud SQL IAM auth token"


def test_each_new_connection_obtains_fresh_native_proof(monkeypatch):
    credentials = Mock(token=None)
    _google_boundary(monkeypatch, credentials)
    tokens = iter(["synthetic-first-proof", "synthetic-renewed-proof"])

    def refresh(request):
        credentials.token = next(tokens)

    credentials.refresh.side_effect = refresh
    first = GCPDBAuth.generate_auth_token("db.example.test", 5432, "runtime")
    second = GCPDBAuth.generate_auth_token("db.example.test", 5432, "runtime")
    assert (first, second) == ("synthetic-first-proof", "synthetic-renewed-proof")


def test_empty_native_proof_fails_closed(monkeypatch):
    _google_boundary(monkeypatch, Mock(token=None))
    with pytest.raises(CloudDBAuthError):
        GCPDBAuth.generate_auth_token("db.example.test", 5432, "runtime")
