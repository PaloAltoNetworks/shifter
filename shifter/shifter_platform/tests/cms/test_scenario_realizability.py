"""Catalog-side backend realizability projection for the Scenario Editor (#1581).

ADR-034-R3 requires non-realizable packs to be flagged and surfaced to the author
without creating loopholes. These tests pin the CMS projection that the editor
renders: it combines the capability envelope (via ``shared.raes.realizability``)
with backend *supply* (the tenant image registry), reports a closed outcome with
bounded gaps, and never reports "cannot assess" as realizable.

Unknown scenario identifiers have no realizability projection.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from cms.scenarios.pack_validation import pack_digest
from cms.scenarios.realizability import get_scenario_realizability
from cms.services import PackRegistrationRequest, register_pack
from engine.services import RaesImageMappingOptions, upsert_raes_image_mapping
from shared.raes.realizability import GapCategory, RealizabilityOutcome
from tests.cms.conftest import IMAGELESS_PACK_SDL

User = get_user_model()

pytestmark = pytest.mark.django_db

_GCE = "gce"


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(username="realizability-staff", password="pw", is_staff=True)


@pytest.fixture(autouse=True)
def _gcp_target(monkeypatch):
    """Run assessment against the GCE RAES realization adapter.

    ``CLOUD_PROVIDER`` dev-defaults to aws, which has no RAES adapter; without
    this the whole suite would only ever exercise the target-gap path.
    """
    monkeypatch.setattr(settings, "CLOUD_PROVIDER", "gcp")


def _register(staff_user, make_pack, tmp_path, monkeypatch, *, name, sdl=IMAGELESS_PACK_SDL):
    """Place a pack under a monkeypatched RAES_PACKAGE_ROOT and register it."""
    root = make_pack(tmp_path / "packs" / name, name=name, sdl=sdl)
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    request = PackRegistrationRequest(
        scenario_id=name,
        source_kind="repo",
        contract_kind="raes",
        contract_profile="shifter",
        package_ref=f"packs/{name}",
        package_version="0.1.0",
        package_digest=pack_digest(root),
        provenance={"repo": "acme/example", "commit": "c" * 40},
    )
    register_pack(user=staff_user, request=request)
    return root


def _map_base_os(os_family: str = "linux", image_ref: str = "projects/p/global/images/base-linux") -> None:
    """Register the tenant base-OS mapping a source-less node needs."""
    upsert_raes_image_mapping(
        provider=_GCE,
        source_name=os_family,
        image_ref=image_ref,
        options=RaesImageMappingOptions(source_version=""),
    )


class TestNotApplicable:
    """Unknown identifiers cannot be assessed."""

    def test_unknown_scenario_returns_none(self):
        assert get_scenario_realizability("no-such-scenario") is None


class TestRealizable:
    """A pack inside the envelope with its backend supply present is realizable."""

    def test_imageless_pack_with_base_os_mapping_is_realizable(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")
        _map_base_os()

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.REALIZABLE
        assert result["gaps"] == []
        assert result["target_id"] == _GCE


class TestImageSupplyGap:
    """A source-less node still needs a base image; zero images is not automatic success."""

    def test_missing_base_os_mapping_is_not_realizable(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")
        # Deliberately register no mapping.

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.NOT_REALIZABLE
        assert result["gaps"], "a missing image mapping must be reported"
        assert any(gap["category"] == GapCategory.IMAGE_SUPPLY for gap in result["gaps"])

    def test_disabled_mapping_does_not_satisfy_supply(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")
        upsert_raes_image_mapping(
            provider=_GCE,
            source_name="linux",
            image_ref="projects/p/global/images/retired",
            options=RaesImageMappingOptions(source_version="", enabled=False),
        )

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.NOT_REALIZABLE

    def test_image_supply_gap_names_the_node_address(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")

        gaps = get_scenario_realizability("imageless")["gaps"]
        supply = [gap for gap in gaps if gap["category"] == GapCategory.IMAGE_SUPPLY]
        assert supply
        assert all(gap["address"] for gap in supply)


class TestSourceIntegrity:
    """A pack that cannot be trusted is indeterminate, never realizable."""

    def test_digest_mismatch_is_indeterminate(self, staff_user, make_pack, tmp_path, monkeypatch):
        root = _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")
        _map_base_os()
        # Tamper after registration: the persisted digest no longer matches.
        (root / "sdl" / "scenario.sdl.yaml").write_text(
            IMAGELESS_PACK_SDL.replace("__PACK_NAME__", "imageless") + "\n# tampered\n", encoding="utf-8"
        )

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.INDETERMINATE
        assert any(gap["category"] == GapCategory.SOURCE_INTEGRITY for gap in result["gaps"])

    def test_missing_pack_on_disk_is_indeterminate(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")
        _map_base_os()
        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path / "elsewhere"))

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.INDETERMINATE
        assert result["outcome"] != RealizabilityOutcome.REALIZABLE


class TestObjectBackedPacks:
    """Object packs are assessed through the same bounded staging path as launch.

    Object rows are registered without content validation or digest binding
    (#1578), so assessment must provide the identity guarantees repo packs get:
    stage the immutable archive, validate the pack contract, check identity, and
    verify the digest -- all before compiling anything.
    """

    @pytest.fixture
    def _object_storage(self, monkeypatch, make_pack, tmp_path):
        """Stage a real pack tree in place of an object download."""
        import contextlib

        root = make_pack(tmp_path / "staged" / "imageless", name="imageless", sdl=IMAGELESS_PACK_SDL)
        monkeypatch.setattr(settings, "RAES_PACKAGE_BUCKET", "packs-bucket")

        @contextlib.contextmanager
        def _fake_stage(**_kwargs):
            yield root

        monkeypatch.setattr("shared.raes.object_source.stage_object_pack", _fake_stage)
        monkeypatch.setattr("shared.cloud.get_object_storage", lambda: object())
        return root

    def _register_object(self, staff_user, digest):
        return register_pack(
            user=staff_user,
            request=PackRegistrationRequest(
                scenario_id="imageless",
                source_kind="object",
                contract_kind="raes",
                contract_profile="shifter",
                package_ref="imageless.tar.gz",
                package_version="0.1.0",
                package_digest=digest,
                provenance={"repo": "acme/example", "commit": "c" * 40},
            ),
        )

    def test_object_pack_is_assessed_after_staging(self, staff_user, _object_storage):
        self._register_object(staff_user, pack_digest(_object_storage))
        _map_base_os()

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.REALIZABLE

    def test_object_pack_reports_supply_gaps(self, staff_user, _object_storage):
        self._register_object(staff_user, pack_digest(_object_storage))
        # No image mapping registered.

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.NOT_REALIZABLE
        assert any(gap["category"] == GapCategory.IMAGE_SUPPLY for gap in result["gaps"])

    def test_object_pack_digest_mismatch_is_indeterminate(self, staff_user, _object_storage):
        self._register_object(staff_user, "sha256:" + "b" * 64)
        _map_base_os()

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.INDETERMINATE
        assert any(gap["category"] == GapCategory.SOURCE_INTEGRITY for gap in result["gaps"])

    def test_object_pack_without_a_bucket_is_indeterminate(self, staff_user, _object_storage, monkeypatch):
        self._register_object(staff_user, pack_digest(_object_storage))
        monkeypatch.setattr(settings, "RAES_PACKAGE_BUCKET", "")

        result = get_scenario_realizability("imageless")

        assert result["outcome"] == RealizabilityOutcome.INDETERMINATE


class TestBoundedAndReadOnly:
    """The projection is derived data off the catalog hot path."""

    def test_assessment_performs_no_writes(self, staff_user, make_pack, tmp_path, monkeypatch):
        from cms.models import RaesPackageSource

        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")
        _map_base_os()
        before = RaesPackageSource.objects.get(scenario_id="imageless")

        get_scenario_realizability("imageless")

        after = RaesPackageSource.objects.get(scenario_id="imageless")
        assert after.package_digest == before.package_digest
        assert after.conformance_status == before.conformance_status

    def test_image_registry_is_read_in_one_bulk_query(
        self, staff_user, make_pack, tmp_path, monkeypatch, django_assert_max_num_queries
    ):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")
        _map_base_os()

        # Catalog entry + package source + one bulk registry read -- never one
        # registry query per node.
        with django_assert_max_num_queries(6):
            get_scenario_realizability("imageless")

    def test_gaps_are_bounded_dicts_without_payloads(self, staff_user, make_pack, tmp_path, monkeypatch):
        _register(staff_user, make_pack, tmp_path, monkeypatch, name="imageless")

        for gap in get_scenario_realizability("imageless")["gaps"]:
            assert set(gap) == {"code", "address", "category", "message"}
            assert str(tmp_path) not in gap["message"]
