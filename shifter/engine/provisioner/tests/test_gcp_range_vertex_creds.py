"""Legacy cleanup deletes owned copies without reading or managing provider keys."""

from types import SimpleNamespace

import pytest

from gcp_range_vertex_creds import delete_range_vertex_key


class NotFound(Exception):
    """Missing cloud resource."""


@pytest.mark.parametrize("missing", [False, True])
def test_cleanup_uses_only_secret_deletion_boundary(monkeypatch, missing):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    calls = []

    class Secrets:
        # No payload-reading or IAM methods: teardown must work after provider
        # key authority is removed from this workload.
        def delete_secret(self, *, request):
            calls.append(request["name"])
            if missing:
                raise NotFound()

    delete_range_vertex_key(
        42, secret_client=Secrets(), google_exceptions=SimpleNamespace(NotFound=NotFound), project_id="platform-project"
    )
    assert set(calls) == {
        "projects/platform-project/secrets/shifter-range-42-vertex-key",
        "projects/range-secrets/secrets/shifter-gcp-dev-dynamic-workload-vertex-range-42-service-account-key",
    }
