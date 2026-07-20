"""Behavior tests for the ACES image registry service (ADR-032-R2).

Drives the real upsert seam against a real database: the single validated write
path for engine.models.AcesImageMapping (idempotent by natural key, soft-disable
via options.enabled=False, validated inputs). The provisioner reads/resolves these
rows; that side is tested in the provisioner suite.
"""

import pytest

from engine.models import AcesImageMapping
from engine.services import (
    AcesImageMappingError,
    AcesImageMappingOptions,
    AcesImageMappingView,
    disable_aces_image_mapping,
    list_aces_image_mappings,
    upsert_aces_image_mapping,
)

pytestmark = pytest.mark.django_db


class TestUpsert:
    def test_creates_mapping(self):
        mapping = upsert_aces_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="projects/x/global/images/kali-2024-1",
            options=AcesImageMappingOptions(source_version="2024.1", machine_type="e2-medium"),
        )
        assert mapping.pk is not None
        assert mapping.provider == "gce"
        assert mapping.enabled is True
        assert AcesImageMapping.objects.count() == 1

    def test_idempotent_update_by_natural_key(self):
        opts = AcesImageMappingOptions(source_version="2024.1")
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img-a", options=opts)
        updated = upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img-b", options=opts)
        assert AcesImageMapping.objects.count() == 1
        assert updated.image_ref == "img-b"

    def test_blank_version_is_a_distinct_fallback_row(self):
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img-any")
        upsert_aces_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="img-v1",
            options=AcesImageMappingOptions(source_version="1.0"),
        )
        assert AcesImageMapping.objects.filter(provider="gce", source_name="kali").count() == 2

    def test_soft_disable_via_upsert(self):
        opts = AcesImageMappingOptions(source_version="1.0")
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img", options=opts)
        disabled = upsert_aces_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="img",
            options=AcesImageMappingOptions(source_version="1.0", enabled=False),
        )
        assert disabled.enabled is False
        assert AcesImageMapping.objects.count() == 1

    def test_normalizes_provider_case_and_whitespace(self):
        mapping = upsert_aces_image_mapping(provider=" GCE ", source_name="kali", image_ref="img")
        assert mapping.provider == "gce"


class TestValidation:
    def test_rejects_unknown_provider(self):
        with pytest.raises(AcesImageMappingError):
            upsert_aces_image_mapping(provider="azure", source_name="kali", image_ref="img")

    def test_rejects_empty_source_name(self):
        with pytest.raises(AcesImageMappingError):
            upsert_aces_image_mapping(provider="gce", source_name="   ", image_ref="img")

    def test_rejects_empty_image_ref(self):
        with pytest.raises(AcesImageMappingError):
            upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="")

    def test_rejects_non_positive_disk_size(self):
        options = AcesImageMappingOptions(disk_size_gb=0)
        with pytest.raises(AcesImageMappingError):
            upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img", options=options)


class TestList:
    def test_returns_views_in_natural_key_order(self):
        upsert_aces_image_mapping(
            provider="gce", source_name="kali", image_ref="img-v2", options=AcesImageMappingOptions(source_version="2")
        )
        upsert_aces_image_mapping(provider="gce", source_name="alpine", image_ref="img-any")
        rows = list_aces_image_mappings()
        assert [(r.source_name, r.source_version) for r in rows] == [("alpine", ""), ("kali", "2")]
        assert all(isinstance(r, AcesImageMappingView) for r in rows)
        assert rows[0].image_ref == "img-any"

    def test_empty_registry_returns_empty_list(self):
        assert list_aces_image_mappings() == []

    def test_provider_filter(self):
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img")
        upsert_aces_image_mapping(provider="aws", source_name="kali", image_ref="ami-1")
        rows = list_aces_image_mappings(provider="aws")
        assert [r.provider for r in rows] == ["aws"]

    def test_include_disabled_false_hides_disabled_rows(self):
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img")
        upsert_aces_image_mapping(
            provider="gce", source_name="ubuntu", image_ref="img", options=AcesImageMappingOptions(enabled=False)
        )
        enabled_only = list_aces_image_mappings(include_disabled=False)
        assert [r.source_name for r in enabled_only] == ["kali"]
        assert len(list_aces_image_mappings()) == 2

    def test_unknown_provider_filter_raises(self):
        with pytest.raises(AcesImageMappingError):
            list_aces_image_mappings(provider="azure")


class TestDisable:
    def test_disables_existing_row_preserving_image_ref(self):
        upsert_aces_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="img-keep",
            options=AcesImageMappingOptions(source_version="1"),
        )
        view = disable_aces_image_mapping(provider="gce", source_name="kali", source_version="1")
        assert view.enabled is False
        assert view.image_ref == "img-keep"
        assert AcesImageMapping.objects.get(source_name="kali").enabled is False

    def test_targets_blank_version_fallback_row(self):
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img-any")
        upsert_aces_image_mapping(
            provider="gce", source_name="kali", image_ref="img-v1", options=AcesImageMappingOptions(source_version="1")
        )
        disable_aces_image_mapping(provider="gce", source_name="kali")
        assert AcesImageMapping.objects.get(source_name="kali", source_version="").enabled is False
        assert AcesImageMapping.objects.get(source_name="kali", source_version="1").enabled is True

    def test_idempotent_on_already_disabled(self):
        upsert_aces_image_mapping(
            provider="gce", source_name="kali", image_ref="img", options=AcesImageMappingOptions(enabled=False)
        )
        view = disable_aces_image_mapping(provider="gce", source_name="kali")
        assert view.enabled is False

    def test_missing_mapping_raises(self):
        with pytest.raises(AcesImageMappingError):
            disable_aces_image_mapping(provider="gce", source_name="absent")

    def test_unknown_provider_raises(self):
        with pytest.raises(AcesImageMappingError):
            disable_aces_image_mapping(provider="azure", source_name="kali")
