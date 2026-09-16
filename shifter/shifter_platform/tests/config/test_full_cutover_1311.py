"""Hard-cut invariants for the RAES and platform-SPA authority switch (#1311)."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.test import Client

from cms.scenarios.inbox import SHIPPED_INBOX_MANIFEST, load_inbox_manifest
from cms.scenarios.pack_validation import pack_digest, validate_pack

pytestmark = pytest.mark.django_db

REPO_ROOT = Path(__file__).resolve().parents[4]
SPA_PATHS = (
    "/",
    "/mission-control/",
    "/scenario-editor/",
    "/ctf/",
    "/raes-image-registry/",
    "/administer/",
)
RETIRED_SETTINGS = (
    "PLATFORM_SPA_ENABLED",
    "MISSION_CONTROL_SPA_ENABLED",
    "SCENARIO_EDITOR_SPA_ENABLED",
    "CTF_WORKSPACE_SPA_ENABLED",
    "ADMINISTER_SPA_ENABLED",
    "RAES_NATIVE_PROVISIONING_ENABLED",
    "RAES_CATALOG_CUTOVERS",
)


@pytest.fixture
def operator(django_user_model):
    return django_user_model.objects.create_user(
        username="cutover-operator",
        email="cutover-operator@example.com",
        password="pw",
        is_staff=True,
    )


def test_every_migrated_page_is_owned_by_the_spa_without_rollout_settings(settings, operator):
    for setting_name in RETIRED_SETTINGS:
        assert not hasattr(settings, setting_name)

    client = Client()
    client.force_login(operator)
    for path in SPA_PATHS:
        response = client.get(path)
        assert response.status_code == 200, path
        assert b'id="root"' in response.content, path


def test_smoke_linux_is_the_single_digest_bound_shipped_raes_pack():
    packs = load_inbox_manifest(SHIPPED_INBOX_MANIFEST)
    assert len(packs) == 1
    source = packs[0]
    assert source.scenario_id == "smoke-linux"
    assert source.contract_kind == "raes"
    assert source.contract_profile == "shifter"

    # The shipped pack's package_ref is relative to RAES_PACKAGE_ROOT, which is the
    # shifter_platform dir (the manifest's parents[3]) — baked to /app in the
    # container. Resolve against that root, not the repo root.
    pack_root = SHIPPED_INBOX_MANIFEST.parents[3] / source.package_ref
    assert validate_pack(pack_root) == "smoke-linux"
    assert pack_digest(pack_root) == source.package_digest


def test_legacy_runtime_authorities_are_absent_from_the_checkout():
    retired_paths = (
        REPO_ROOT / "shifter/cyberscript",
        REPO_ROOT / "shifter/shifter_platform/cms/scenarios/templates",
        REPO_ROOT / "scripts/polaris-aws-range",
    )
    assert [str(path.relative_to(REPO_ROOT)) for path in retired_paths if path.exists()] == []
