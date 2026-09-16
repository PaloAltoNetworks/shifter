"""Behavior tests for the RAES image registry service (ADR-032-R2).

Drives the real upsert seam against a real database: the single validated write
path for engine.models.RaesImageMapping (idempotent by natural key, soft-disable
via options.enabled=False, validated inputs). The provisioner reads/resolves these
rows; that side is tested in the provisioner suite.
"""

import pytest

from engine.models import RaesImageMapping
from engine.services import (
    RaesImageMappingError,
    RaesImageMappingOptions,
    RaesImageMappingView,
    disable_raes_image_mapping,
    list_raes_image_mappings,
    upsert_raes_image_mapping,
)

pytestmark = pytest.mark.django_db


class TestUpsert:
    def test_creates_mapping(self):
        mapping = upsert_raes_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="projects/x/global/images/kali-2024-1",
            options=RaesImageMappingOptions(source_version="2024.1", machine_type="e2-medium"),
        )
        assert mapping.pk is not None
        assert mapping.provider == "gce"
        assert mapping.enabled is True
        assert RaesImageMapping.objects.count() == 1

    def test_idempotent_update_by_natural_key(self):
        opts = RaesImageMappingOptions(source_version="2024.1")
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img-a", options=opts)
        updated = upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img-b", options=opts)
        assert RaesImageMapping.objects.count() == 1
        assert updated.image_ref == "img-b"

    def test_blank_version_is_a_distinct_fallback_row(self):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img-any")
        upsert_raes_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="img-v1",
            options=RaesImageMappingOptions(source_version="1.0"),
        )
        assert RaesImageMapping.objects.filter(provider="gce", source_name="kali").count() == 2

    def test_soft_disable_via_upsert(self):
        opts = RaesImageMappingOptions(source_version="1.0")
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img", options=opts)
        disabled = upsert_raes_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="img",
            options=RaesImageMappingOptions(source_version="1.0", enabled=False),
        )
        assert disabled.enabled is False
        assert RaesImageMapping.objects.count() == 1

    def test_normalizes_provider_case_and_whitespace(self):
        mapping = upsert_raes_image_mapping(provider=" GCE ", source_name="kali", image_ref="img")
        assert mapping.provider == "gce"


class TestValidation:
    def test_rejects_unknown_provider(self):
        with pytest.raises(RaesImageMappingError):
            upsert_raes_image_mapping(provider="azure", source_name="kali", image_ref="img")

    def test_rejects_empty_source_name(self):
        with pytest.raises(RaesImageMappingError):
            upsert_raes_image_mapping(provider="gce", source_name="   ", image_ref="img")

    def test_rejects_empty_image_ref(self):
        with pytest.raises(RaesImageMappingError):
            upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="")

    def test_rejects_non_positive_disk_size(self):
        options = RaesImageMappingOptions(disk_size_gb=0)
        with pytest.raises(RaesImageMappingError):
            upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img", options=options)


class TestList:
    def test_returns_views_in_natural_key_order(self):
        upsert_raes_image_mapping(
            provider="gce", source_name="kali", image_ref="img-v2", options=RaesImageMappingOptions(source_version="2")
        )
        upsert_raes_image_mapping(provider="gce", source_name="alpine", image_ref="img-any")
        rows = list_raes_image_mappings()
        assert [(r.source_name, r.source_version) for r in rows] == [("alpine", ""), ("kali", "2")]
        assert all(isinstance(r, RaesImageMappingView) for r in rows)
        assert rows[0].image_ref == "img-any"

    def test_empty_registry_returns_empty_list(self):
        assert list_raes_image_mappings() == []

    def test_provider_filter(self):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img")
        upsert_raes_image_mapping(provider="aws", source_name="kali", image_ref="ami-1")
        rows = list_raes_image_mappings(provider="aws")
        assert [r.provider for r in rows] == ["aws"]

    def test_include_disabled_false_hides_disabled_rows(self):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img")
        upsert_raes_image_mapping(
            provider="gce", source_name="ubuntu", image_ref="img", options=RaesImageMappingOptions(enabled=False)
        )
        enabled_only = list_raes_image_mappings(include_disabled=False)
        assert [r.source_name for r in enabled_only] == ["kali"]
        assert len(list_raes_image_mappings()) == 2

    def test_unknown_provider_filter_raises(self):
        with pytest.raises(RaesImageMappingError):
            list_raes_image_mappings(provider="azure")


class TestDisable:
    def test_disables_existing_row_preserving_image_ref(self):
        upsert_raes_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="img-keep",
            options=RaesImageMappingOptions(source_version="1"),
        )
        view = disable_raes_image_mapping(provider="gce", source_name="kali", source_version="1")
        assert view.enabled is False
        assert view.image_ref == "img-keep"
        assert RaesImageMapping.objects.get(source_name="kali").enabled is False

    def test_targets_blank_version_fallback_row(self):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img-any")
        upsert_raes_image_mapping(
            provider="gce", source_name="kali", image_ref="img-v1", options=RaesImageMappingOptions(source_version="1")
        )
        disable_raes_image_mapping(provider="gce", source_name="kali")
        assert RaesImageMapping.objects.get(source_name="kali", source_version="").enabled is False
        assert RaesImageMapping.objects.get(source_name="kali", source_version="1").enabled is True

    def test_idempotent_on_already_disabled(self):
        upsert_raes_image_mapping(
            provider="gce", source_name="kali", image_ref="img", options=RaesImageMappingOptions(enabled=False)
        )
        view = disable_raes_image_mapping(provider="gce", source_name="kali")
        assert view.enabled is False

    def test_missing_mapping_raises(self):
        with pytest.raises(RaesImageMappingError):
            disable_raes_image_mapping(provider="gce", source_name="absent")

    def test_unknown_provider_raises(self):
        with pytest.raises(RaesImageMappingError):
            disable_raes_image_mapping(provider="azure", source_name="kali")
