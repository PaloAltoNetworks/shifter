"""Pytest fixtures and helpers for CMS tests.

Provides shared model builders and fixtures used across CMS test modules.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.db.models.base import ModelState
from django.utils import timezone

from cms.models import AgentConfig, Credential, CredentialType, OperatingSystem, RaesPackageSource

User = get_user_model()


# -----------------------------------------------------------------------------
# Behavior-test fixtures: real scenario hydration against the test DB
# -----------------------------------------------------------------------------


@pytest.fixture
def windows_os(db) -> OperatingSystem:
    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
    )
    return os_obj


@pytest.fixture
def make_agent(db, windows_os) -> Callable[..., AgentConfig]:
    """Factory creating a real AgentConfig owned by ``user``."""

    def _make(user, *, os=None, name="Test XDR Agent", **overrides) -> AgentConfig:
        fields: dict[str, Any] = {
            "name": name,
            "s3_key": "agents/test/agent.msi",
            "original_filename": "agent.msi",
            "file_size_bytes": 50_000_000,
            "sha256_hash": "abc123",
            "user": user,
            "os": os or windows_os,
        }
        fields.update(overrides)
        return AgentConfig.objects.create(**fields)

    return _make


@pytest.fixture
def hydratable_scenario(db, monkeypatch) -> RaesPackageSource:
    """A conformance-passed RAES source with dispatch held at the cloud seam."""
    staff = User.objects.create_user(
        username="cms-scenario-author@example.com",
        email="cms-scenario-author@example.com",
        is_staff=True,
    )
    monkeypatch.setattr("engine.services._raes_range.start_raes_range_provisioning", lambda *_a, **_kw: None)

    def dispatch(request_id, user, _source, backend_admission, workspace_id, egress_mode):
        from engine.services import create_raes_range

        create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan={"kind": "raes_provisioning_plan", "raes_version": "2.0", "resources": {}},
            backend_admission=backend_admission,
            workspace_id=workspace_id,
            egress_mode=egress_mode,
        )

    monkeypatch.setattr("cms.services._raes_range_create._dispatch_raes_package", dispatch)
    return RaesPackageSource.objects.create(
        scenario_id="cms-behavior-test",
        contract_kind="raes",
        contract_profile="shifter",
        package_ref="tests/packs/cms-behavior-test",
        package_version="1.0.0",
        package_digest="sha256:" + "a" * 64,
        conformance_status="passed",
        registered_by=staff,
    )


@pytest.fixture
def provision_range(make_agent, hydratable_scenario) -> Callable[..., Any]:
    """Factory: create a real range for ``user`` (full hydrate->engine->persist
    stack), assign it a ``range_id``, and return the cms RangeInstance.

    The matching engine ``Range``/``Request`` rows are created too, so range
    lifecycle services (destroy/cancel/pause/resume) operate on genuine state.
    """
    from cms import services
    from cms.models import RangeInstance

    def _make(user, *, range_id=42, engine_status=None):
        services.create_range(user, hydratable_scenario.scenario_id, {"windows": make_agent(user).id})
        ri = RangeInstance.objects.get(user_id=user.id)
        ri.range_id = range_id
        ri.save(update_fields=["range_id"])
        if engine_status is not None:
            from engine.models import Range as EngineRange

            EngineRange.objects.filter(user=user).update(status=engine_status)
        return ri

    return _make


# -----------------------------------------------------------------------------
# In-memory model builders (no DB required)
# -----------------------------------------------------------------------------


@pytest.fixture
def credential_type_obj():
    """Create a CredentialType instance in memory (no DB)."""
    ct = CredentialType(
        name="Deployment Profile",
        slug="deployment_profile",
        spec_slug="credential.deployment_profile",
    )
    ct.pk = 1
    ct.id = 1
    return ct


@pytest.fixture
def scm_credential_type_obj():
    """Create an SCM CredentialType instance in memory (no DB)."""
    ct = CredentialType(
        name="SCM Credential",
        slug="scm",
        spec_slug="credential.scm",
    )
    ct.pk = 2
    ct.id = 2
    return ct


def make_credential(credential_type_obj, pk=1, **overrides):
    """Build a Credential instance in memory using _id fields to bypass FK checks.

    Uses __new__ + manual __dict__ population to avoid Django's FK descriptor
    type-checking (which rejects MagicMock users). The _state object is
    initialized manually to keep FK cache access working.
    """
    cred = Credential.__new__(Credential)
    cred._state = ModelState()
    # Set fields directly to avoid FK descriptor type checks
    cred.__dict__["name"] = overrides.get("name", "My Credential")
    cred.__dict__["user_id"] = overrides.get("user_id", 1)
    cred.__dict__["credential_type_id"] = credential_type_obj.pk
    cred.__dict__["data"] = overrides.get("data", {"authcode": "D1234567"})
    cred.__dict__["deleted_at"] = overrides.get("deleted_at")
    cred.__dict__["expires_at"] = overrides.get("expires_at")
    cred.__dict__["created_at"] = overrides.get("created_at", timezone.now())
    # Cache the FK object so descriptor access works without DB
    cred._state.fields_cache["credential_type"] = credential_type_obj
    cred.pk = pk
    cred.id = pk
    return cred


# -----------------------------------------------------------------------------
# Uniform content-ingestion fixtures (#1578): build conformant / malformed RAES
# scenario packs on disk for pack-validation and registration tests.
# -----------------------------------------------------------------------------

# A minimal RAES SDL start state that parses through raes (mirrors
# scenario-dev/shifter-raes-validation/sdl/shifter-raes-validation.sdl.yaml).
CONFORMANT_PACK_SDL = """\
name: __PACK_NAME__
description: Minimal provisioning-only RAES start state for ingestion tests.
nodes:
  lan:
    type: Switch
  web:
    type: compute
    os: linux
    os_distribution: x-shifter:alpine
    os_version: "3.19"
    source: {name: "alpine", version: "3.19"}
    resources: {ram: 512 mib, cpu: 1}
    services:
      - {port: 80, name: http}
infrastructure:
  lan:
    count: 1
    properties: {cidr: 10.60.0.0/24, gateway: 10.60.0.1}
  web:
    count: 1
    links: [lan]
    properties:
      - lan: 10.60.0.10
"""

# A conformant SDL start state with ZERO image references (#1579): no VM node
# declares a `source`, so the pack carries no images and the backend supplies a
# base OS at realization. Used to prove image-bearing is optional across
# ingestion, catalog projection, and realizability (ADR-034).
IMAGELESS_PACK_SDL = """\
name: __PACK_NAME__
description: Image-less provisioning-only RAES start state (no VM source).
nodes:
  lan:
    type: Switch
  host:
    type: compute
    os: linux
    resources: {ram: 512 mib, cpu: 1}
infrastructure:
  lan:
    count: 1
    properties: {cidr: 10.80.0.0/24, gateway: 10.80.0.1}
  host:
    count: 1
    links: [lan]
    properties:
      - lan: 10.80.0.10
"""

# A conformant SDL start state whose runs are parameterized via RAES SDL
# `variables` (#1579): the multi-run experiment unit. Also image-less.
PARAMETERIZED_PACK_SDL = """\
name: __PACK_NAME__
description: Parameterized RAES scenario using SDL variables.
variables:
  region:
    type: string
    default: alpha
    required: false
    allowed_values: [alpha, beta]
nodes:
  lan:
    type: Switch
  host:
    type: compute
    os: linux
    resources: {ram: 512 mib, cpu: 1}
infrastructure:
  lan:
    count: 1
    properties: {cidr: 10.81.0.0/24, gateway: 10.81.0.1}
  host:
    count: 1
    links: [lan]
    properties:
      - lan: 10.81.0.10
"""


def conformant_pack_yaml(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "title": name.replace("-", " ").title(),
        "version": "0.1.0",
        "status": "draft",
        "description": "Minimal conformant pack for ingestion tests.",
        "authors": ["Test Author <test@example.com>"],
        "provenance_ledger": "docs/provenance-ledger.yaml",
        "associated_artifact_manifest": "associated-artifacts.json",
    }


def conformant_provenance(name: str) -> dict[str, Any]:
    return {
        "schema_version": "environment-pack-provenance/v3",
        "pack": {"name": name},
        "sources": [
            {
                "source_id": "original-design",
                "name": "Original RAES design",
                "license": "proprietary",
                "usage": "reused",
                "attribution_required": False,
            }
        ],
        "artifacts": [{"artifact_id": "briefing", "path": "docs/concepts.md", "classification": "open"}],
        "content_safety": {
            "no_real_malware": True,
            "no_real_third_party_targets": True,
            "no_real_credentials": True,
            "no_sensitive_data": True,
            "offensive_tooling_boundary": True,
        },
        "review": {
            "status": "approved",
            "gates": [
                {"gate_id": "licensing", "status": "approved"},
                {"gate_id": "attribution", "status": "approved"},
                {"gate_id": "sensitive-data", "status": "approved"},
                {"gate_id": "offensive-tooling", "status": "approved"},
            ],
        },
    }


def write_pack_content_manifest(root: Path, name: str) -> str:
    """Write the canonical RAES associated-artifact manifest for test bytes."""
    from raes_contracts.associated_artifacts import associated_artifact_set_digest
    from raes_contracts.contracts import AssociatedArtifactManifestModel

    manifest_rel = "associated-artifacts.json"
    members = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != manifest_rel
    )
    artifacts: dict[str, dict[str, object]] = {}
    for index, rel in enumerate(members):
        body = (root / rel).read_bytes()
        artifact_id = f"artifact-{index}"
        artifacts[artifact_id] = {
            "artifact_id": artifact_id,
            "role": "other",
            "media_type": "application/octet-stream",
            "uri": f"raes-environment-pack:/{quote(rel, safe='/-._~')}",
            "checksum": {"algorithm": "sha256", "value": hashlib.sha256(body).hexdigest()},
            "size_bytes": len(body),
            "created_at": "2026-07-13T00:00:00Z",
            "source": "shifter-test-fixture",
            "sensitivity": "internal",
        }
    model = AssociatedArtifactManifestModel.model_validate(
        {
            "schema_version": "associated-artifact-manifest/v1",
            "manifest_id": f"{name}-associated-artifacts",
            "manifest_version": "0.1.0",
            "canonicalization_profile": "associated-artifact-set/v1",
            "scope": "scenario",
            "parent_ref": {"ref_kind": "scenario", "ref_id": name},
            "artifacts": artifacts,
            "set_digest": "sha256:" + "0" * 64,
        }
    )
    model = model.model_copy(update={"set_digest": associated_artifact_set_digest(model)})
    (root / manifest_rel).write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return model.set_digest


@pytest.fixture
def make_pack():
    """Factory: write an RAES scenario pack to disk and return its root Path.

    Defaults produce a conformant pack (valid pack.yaml, provenance ledger,
    concepts doc, and an SDL start state that parses through raes). Override
    ``pack_yaml`` / ``provenance`` / ``sdl`` (pass ``sdl=None`` to omit SDL) to
    build malformed packs for negative tests.
    """
    import yaml

    def _make(root, *, name=None, pack_yaml=..., provenance=..., sdl=...):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        name = name or root.name
        pack_yaml = conformant_pack_yaml(name) if pack_yaml is ... else pack_yaml
        provenance = conformant_provenance(name) if provenance is ... else provenance
        sdl = CONFORMANT_PACK_SDL if sdl is ... else sdl
        if pack_yaml is not None:
            (root / "pack.yaml").write_text(yaml.safe_dump(pack_yaml), encoding="utf-8")
        docs = root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "concepts.md").write_text("# Concepts\n", encoding="utf-8")
        if provenance is not None:
            (docs / "provenance-ledger.yaml").write_text(yaml.safe_dump(provenance), encoding="utf-8")
        if sdl is not None:
            # Substitute the pack name into any SDL that carries the placeholder
            # (a no-op for override SDL that omits it), so a pack's scenario
            # identity matches its root regardless of which SDL body is used.
            sdl_dir = root / "sdl"
            sdl_dir.mkdir(parents=True, exist_ok=True)
            (sdl_dir / "scenario.sdl.yaml").write_text(sdl.replace("__PACK_NAME__", name), encoding="utf-8")
        write_pack_content_manifest(root, name)
        return root

    return _make
