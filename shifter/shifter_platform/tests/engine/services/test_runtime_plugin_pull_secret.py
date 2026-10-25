"""Runtime plugin image-pull secret creation under ResourceQuota contention.

Concurrent plugin launches race on the plugin namespace's ResourceQuota, and the
API server rejects the losers with HTTP 409 ``Conflict``. The same status code
also means ``AlreadyExists``; only the Status ``reason`` separates a write that
created nothing (retry) from an existing object (verify and reuse).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.kubernetes._helpers import ADMISSION_CONFLICT_ATTEMPTS, is_admission_conflict


class _ApiException(Exception):
    def __init__(self, status: int, reason: str = "", *, raw_body: bytes | None = None):
        super().__init__(f"status={status}")
        self.status = status
        self.body = raw_body if raw_body is not None else (json.dumps({"reason": reason}) if reason else None)


@pytest.fixture
def pull_secret_env(monkeypatch):
    """Fake Kubernetes APIs for ``_pull_secret`` with sleeps disabled."""
    batch = MagicMock()
    batch.read_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(uid="job-uid"))
    core = MagicMock()
    monkeypatch.setattr(
        "engine.services._runtime_plugin_controller.load_kubernetes_api",
        lambda: (batch, core, None, _ApiException),
    )
    monkeypatch.setattr("shared.cloud.kubernetes._helpers.time.sleep", lambda _seconds: None)
    row = SimpleNamespace(registry_credentials=json.dumps({"auth": "dXNlcjp0b2tlbg=="}))
    request = SimpleNamespace(
        manifest=SimpleNamespace(worker_image="registry.example.test/org/worker@sha256:" + "a" * 64),
        invocation_id=uuid4(),
    )
    return SimpleNamespace(core=core, row=row, request=request)


def test_admission_conflict_is_distinguished_from_already_exists():
    assert is_admission_conflict(_ApiException(409, "Conflict"))
    assert is_admission_conflict(_ApiException(409, raw_body=b'{"reason": "Conflict"}'))
    assert not is_admission_conflict(_ApiException(409, "AlreadyExists"))
    # No parseable Status body keeps the historical "already exists" handling.
    assert not is_admission_conflict(_ApiException(409))
    assert not is_admission_conflict(_ApiException(409, raw_body=b"not json"))
    assert not is_admission_conflict(_ApiException(500, "Conflict"))


def test_pull_secret_retries_quota_conflicts_and_never_reads_an_absent_secret(pull_secret_env):
    from engine.services._runtime_plugin_controller import _pull_secret

    env = pull_secret_env
    env.core.create_namespaced_secret.side_effect = [
        _ApiException(409, "Conflict"),
        _ApiException(409, "Conflict"),
        None,
    ]

    name = _pull_secret(env.row, env.request)

    assert name == f"runtime-plugin-pull-{env.request.invocation_id.hex}"
    assert env.core.create_namespaced_secret.call_count == 3
    env.core.read_namespaced_secret.assert_not_called()

    env.core.reset_mock()
    env.core.create_namespaced_secret.side_effect = _ApiException(409, "Conflict")
    with pytest.raises(CloudTaskError, match="could not be installed"):
        _pull_secret(env.row, env.request)
    assert env.core.create_namespaced_secret.call_count == ADMISSION_CONFLICT_ATTEMPTS
    env.core.read_namespaced_secret.assert_not_called()


def test_pull_secret_reuses_an_existing_matching_secret(pull_secret_env):
    from engine.services._runtime_plugin_controller import _pull_secret

    env = pull_secret_env
    env.core.create_namespaced_secret.side_effect = _ApiException(409, "AlreadyExists")

    def _existing(**_kwargs):
        body = env.core.create_namespaced_secret.call_args.kwargs["body"]
        return SimpleNamespace(
            type=body["type"],
            data=body["data"],
            immutable=True,
            metadata=SimpleNamespace(owner_references=[SimpleNamespace(uid="job-uid")]),
        )

    env.core.read_namespaced_secret.side_effect = _existing

    assert _pull_secret(env.row, env.request) == f"runtime-plugin-pull-{env.request.invocation_id.hex}"
    assert env.core.create_namespaced_secret.call_count == 1
    env.core.read_namespaced_secret.assert_called_once()
