"""RAES scenario image projection for pre-bake planning (PLAT-201, #680)."""

from __future__ import annotations

import pytest
from django.conf import settings

from cms.models import RaesPackageSource
from cms.scenarios.images import project_scenario_images
from cms.scenarios.pack_validation import pack_digest

pytestmark = pytest.mark.django_db


@pytest.fixture
def registered_pack(django_user_model, make_pack, tmp_path, monkeypatch):
    """Register a digest-bound RAES pack beneath the configured package root."""
    actor = django_user_model.objects.create_user(username="image-projection-staff", is_staff=True)
    root = make_pack(tmp_path / "packs" / "image-projection", name="image-projection")
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    source = RaesPackageSource.objects.create(
        scenario_id="image-projection",
        contract_kind="raes",
        contract_profile="shifter",
        package_ref="packs/image-projection",
        package_version="1.0.0",
        package_digest=pack_digest(root),
        conformance_status="passed",
        registered_by=actor,
    )
    return source, root


def test_projects_raes_vm_image_identity(registered_pack):
    projection = project_scenario_images("image-projection")

    assert projection.resolved is True
    assert projection.shared == ()
    assert len(projection.per_range) == 1
    image = projection.per_range[0]
    assert (image.source_name, image.source_version, image.os_family, image.count) == (
        "alpine",
        "3.19",
        "linux",
        1,
    )


def test_digest_mismatch_is_unresolved(registered_pack):
    _source, root = registered_pack
    (root / "docs" / "concepts.md").write_text("# Tampered\n", encoding="utf-8")

    projection = project_scenario_images("image-projection")

    assert projection.resolved is False
    assert projection.per_range == ()
    assert projection.shared == ()


def test_unknown_scenario_is_unresolved(db):
    projection = project_scenario_images("no-such-scenario")

    assert projection.resolved is False
    assert projection.per_range == ()
    assert projection.shared == ()


def test_hint_is_bounded_to_image_identity(registered_pack):
    payload = project_scenario_images("image-projection").as_hint()

    assert payload["resolved"] is True
    assert payload["shared"] == []
    assert payload["per_range"] == [
        {
            "source_name": "alpine",
            "source_version": "3.19",
            "os_family": "linux",
            "count": 1,
        }
    ]
