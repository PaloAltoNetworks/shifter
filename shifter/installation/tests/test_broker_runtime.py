"""Broker runtime projection rejects application authority and catalog drift."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from shared.model_access import ContractError

from installation import gcp_model_broker


def test_runtime_catalog_loader_is_django_free_and_digest_bound(tmp_path):
    from shared.model_access import runtime

    source = Path(__file__).resolve().parents[3] / "docs/architecture/model-access/example-policy.v1.json"
    raw = source.read_text()
    path = tmp_path / "catalog.json"
    path.write_text(raw)
    digest = json.loads(raw)["digest"]
    assert runtime.load_mounted_catalog(enabled=False, path=str(path), expected_digest=digest).digest == digest
    assert "django.conf" not in sys.modules
    with pytest.raises(ContractError):
        runtime.load_mounted_catalog(enabled=False, path=str(path), expected_digest="sha256:" + "0" * 64)
    path.write_text('{"enabled":false,"enabled":true}')
    with pytest.raises(ContractError):
        runtime.load_mounted_catalog(enabled=False, path=str(path), expected_digest=digest)


def test_broker_inventory_is_a_distinct_consumer():
    from installation.contract import ProcessRole
    from installation.registry import get_backend_bundle

    role = ProcessRole.MODEL_BROKER
    outputs = get_backend_bundle("gcp").generated_outputs
    broker_outputs = [output for output in outputs if role in output.process_roles]
    names = {output.name for output in broker_outputs}
    assert names == gcp_model_broker.BROKER_RUNTIME_ENV_KEYS
    assert all(output.process_roles == (role,) for output in broker_outputs)
    assert not any(name.startswith(("DB_", "REDIS_", "APP_", "DJANGO_")) for name in names)


@pytest.mark.parametrize(
    "peer,subnet,expected",
    [
        ("10.50.1.5", "10.50.1.0/24", True),
        ("10.50.2.5", "10.50.1.0/24", False),
        ("10.50.2.5, 10.50.1.5", "10.50.1.0/24", False),
        ("::ffff:10.50.1.5", "10.50.1.0/24", False),
        ("10.50.1.5", "0.0.0.0/0", False),
        ("10.50.1.5", "10.50.1.5/24", False),
    ],
)
def test_peer_binding_rejects_foreign_and_header_shaped_sources(peer, subnet, expected):
    from shared.model_access.network import peer_matches_binding

    assert peer_matches_binding(peer, subnet) is expected
