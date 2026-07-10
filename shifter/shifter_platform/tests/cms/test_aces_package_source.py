"""Tests for the AcesPackageSource model (provenance-only persistence)."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from cms.models import AcesPackageSource
from shared.schemas.aces_package_source import AcesPackageSourceError

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff@example.com",
        email="staff@example.com",
        password="testpass",
        is_staff=True,
    )


def _create(staff_user, **overrides):
    fields = {
        "scenario_id": "polaris-aces",
        "contract_kind": "aces",
        "contract_profile": "shifter",
        "package_ref": "scenario-dev/polaris/content-packages/polaris",
        "package_version": "1.0.0",
        "package_digest": "sha256:" + "a" * 64,
        "registered_by": staff_user,
    }
    fields.update(overrides)
    return AcesPackageSource.objects.create(**fields)


class TestAcesPackageSourcePersistence:
    def test_create_valid(self, staff_user):
        row = _create(staff_user)
        assert row.pk is not None
        assert row.conformance_status == "pending"
        assert row.source_kind == "repo"

    def test_is_conformance_passed_tracks_conformance(self, staff_user):
        assert _create(staff_user, scenario_id="p-pending").is_conformance_passed is False
        assert _create(staff_user, scenario_id="p-passed", conformance_status="passed").is_conformance_passed is True
        assert _create(staff_user, scenario_id="p-failed", conformance_status="failed").is_conformance_passed is False

    def test_unique_scenario_id(self, staff_user):
        _create(staff_user, scenario_id="dup")
        with pytest.raises(IntegrityError):
            _create(staff_user, scenario_id="dup")

    def test_rejects_bad_digest(self, staff_user):
        with pytest.raises(AcesPackageSourceError):
            _create(staff_user, scenario_id="bad-digest", package_digest="nope")

    def test_rejects_multiline_ref(self, staff_user):
        with pytest.raises(AcesPackageSourceError):
            _create(staff_user, scenario_id="bad-ref", package_ref="line1\nSDL body line2")

    @pytest.mark.parametrize(
        "key",
        ["sdl", "module_body", "generated", "credential", "token", "runtime_config"],
    )
    def test_rejects_forbidden_provenance(self, staff_user, key):
        with pytest.raises(AcesPackageSourceError):
            _create(staff_user, scenario_id=f"bad-{key}", provenance={key: "x"})

    def test_accepts_bounded_provenance(self, staff_user):
        row = _create(
            staff_user,
            scenario_id="good-prov",
            provenance={"repo": "Brad-Edwards/shifter", "commit": "abc123"},
        )
        assert row.provenance == {"repo": "Brad-Edwards/shifter", "commit": "abc123"}
