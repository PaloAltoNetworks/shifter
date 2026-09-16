"""Image-optional packs and parameterized-run representability (#1579, ADR-034).

ADR-034 makes "image-bearing" optional across ingestion, catalog projection, and
realizability, and requires parameterized experiment runs to be representable in
the catalog model. These tests pin, on the CMS side:

- a pack with zero image references validates, imports through the uniform
  ingestion service, and appears in the catalog (acceptance #1);
- the catalog-model run-capability projection reports whether a registered pack
  declares parameterized runs, with a bounded, body-free schema (acceptance #2).

Realizability (acceptance #3) is proven against the compiled plan in
``tests/shared/raes/test_runtime_target.py``; the run-representation seam itself
is pinned in ``tests/shared/raes/test_runs.py``.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import check_pack, pack_digest
from cms.scenarios.registry import get_catalog_entry, list_all_scenarios
from cms.scenarios.run_capability import get_run_capability
from cms.services import PackRegistrationRequest, register_pack
from tests.cms.conftest import IMAGELESS_PACK_SDL, PARAMETERIZED_PACK_SDL

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="image-optional-staff@example.com",
        email="image-optional-staff@example.com",
        is_staff=True,
    )


def _register(staff_user, make_pack, tmp_path, monkeypatch, *, name, sdl=..., source_kind="repo", package_ref=None):
    """Place a pack under a monkeypatched RAES_PACKAGE_ROOT and register it."""
    root = make_pack(tmp_path / "packs" / name, name=name, sdl=sdl)
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    ref = package_ref if package_ref is not None else f"packs/{name}"
    digest = pack_digest(root) if source_kind == "repo" else "sha256:" + "a" * 64
    request = PackRegistrationRequest(
        scenario_id=name,
        source_kind=source_kind,
        contract_kind="raes",
        contract_profile="shifter",
        package_ref=ref,
        package_version="0.1.0",
        package_digest=digest,
        provenance={"repo": "acme/example", "commit": "c" * 40},
    )
    return register_pack(user=staff_user, request=request)


class TestImagelessPackImports:
    def test_imageless_pack_passes_foreign_input_validation(self, make_pack, tmp_path):
        # A pack whose SDL declares no VM `source` is valid content, not malformed.
        root = make_pack(tmp_path / "imageless", name="imageless", sdl=IMAGELESS_PACK_SDL)
        assert check_pack(root) == []

    def test_imageless_pack_imports_and_appears_in_catalog(self, staff_user, make_pack, tmp_path, monkeypatch):
        result = _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless", sdl=IMAGELESS_PACK_SDL)
        assert result.created is True
        assert RaesPackageSource.objects.filter(scenario_id="imageless").exists()
        assert get_catalog_entry("imageless") is not None
        assert any(entry["id"] == "imageless" for entry in list_all_scenarios(user=None))

    def test_parameterized_pack_imports_and_appears_in_catalog(self, staff_user, make_pack, tmp_path, monkeypatch):
        result = _register(
            staff_user, make_pack, tmp_path, monkeypatch, name="parameterized", sdl=PARAMETERIZED_PACK_SDL
        )
        assert result.created is True
        assert get_catalog_entry("parameterized") is not None


class TestRunCapabilityProjection:
    def test_unknown_scenario_returns_none(self, db):
        assert get_run_capability("does-not-exist") is None

    def test_imageless_pack_is_resolvable_and_not_parameterized(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless", sdl=IMAGELESS_PACK_SDL)
        capability = get_run_capability("imageless")
        assert capability is not None
        assert capability["resolvable"] is True
        assert capability["parameterized"] is False
        assert capability["parameters"] == []

    def test_parameterized_pack_reports_bounded_declarations(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="parameterized", sdl=PARAMETERIZED_PACK_SDL)
        capability = get_run_capability("parameterized")
        assert capability is not None
        assert capability["resolvable"] is True
        assert capability["parameterized"] is True
        params = {p["name"]: p for p in capability["parameters"]}
        assert set(params) == {"region"}
        assert params["region"] == {
            "name": "region",
            "type": "string",
            "required": False,
            "has_default": True,
            "allowed_value_count": 2,
        }

    def test_projection_never_leaks_author_declared_values(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="parameterized", sdl=PARAMETERIZED_PACK_SDL)
        rendered = repr(get_run_capability("parameterized"))
        # The declared default and allowed-value enumeration must not cross the boundary.
        assert "alpha" not in rendered
        assert "beta" not in rendered

    def test_object_backed_pack_is_not_resolvable(self, staff_user, make_pack, tmp_path, monkeypatch):
        # Object-backed packs have no containment-checked local resolution (#1567).
        _register(
            staff_user,
            make_pack,
            tmp_path,
            monkeypatch,
            name="obj-pack",
            source_kind="object",
            package_ref="object-key/pack",
        )
        capability = get_run_capability("obj-pack")
        assert capability is not None
        assert capability["source_kind"] == "object"
        assert capability["resolvable"] is False
        assert capability["parameterized"] is False

    def test_unresolvable_repo_pack_degrades_soft(self, staff_user, make_pack, tmp_path, monkeypatch):
        # Register a repo pack, then remove its files: a catalog read must not raise.
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="vanishing", sdl=IMAGELESS_PACK_SDL)
        for path in sorted((tmp_path / "packs" / "vanishing").rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        (tmp_path / "packs" / "vanishing").rmdir()
        capability = get_run_capability("vanishing")
        assert capability is not None
        assert capability["resolvable"] is False
