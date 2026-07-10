"""Behavior tests for the ACES image registry service (ADR-032-R2).

Drives the real upsert seam against a real database: the single validated write
path for engine.models.AcesImageMapping (idempotent by natural key, soft-disable
via options.enabled=False, validated inputs). The provisioner reads/resolves these
rows; that side is tested in the provisioner suite.
"""

import pytest

from engine.models import AcesImageMapping
from engine.services import AcesImageMappingError, AcesImageMappingOptions, upsert_aces_image_mapping

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
        with pytest.raises(AcesImageMappingError):
            upsert_aces_image_mapping(
                provider="gce", source_name="kali", image_ref="img", options=AcesImageMappingOptions(disk_size_gb=0)
            )
