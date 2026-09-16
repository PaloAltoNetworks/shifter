"""A private registered pack passes real contract validation before preparation."""

import shutil
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied

from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import pack_digest
from cms.services import PackRegistrationRequest, register_pack
from cms.services._pack_conformance import validate_registered_pack_conformance
from shared.exceptions import ValidationError
from tests.cms.test_content_ingestion import staff_user

pytestmark = pytest.mark.django_db
__all__ = ["staff_user"]


@pytest.fixture
def preparation_pack(tmp_path, settings, staff_user):
    name = "preparation-http-smoke"
    source = Path(__file__).resolve().parents[4] / "scenario-dev" / name
    root = tmp_path / name
    shutil.copytree(source, root)
    settings.RAES_PACKAGE_ROOT = str(tmp_path)
    register_pack(
        user=staff_user,
        request=PackRegistrationRequest(
            scenario_id=name,
            source_kind="repo",
            contract_kind="raes",
            contract_profile="shifter",
            package_ref=name,
            package_version="0.1.1",
            package_digest=pack_digest(root),
        ),
    )
    return root, RaesPackageSource.objects.get(scenario_id=name)


def test_conformance_compiles_real_private_preparation_intent_without_artifact_inventory(staff_user, preparation_pack):
    from engine.models import PreparationAttempt, Range

    _, source = preparation_pack
    assert source.conformance_status == "pending"
    result = validate_registered_pack_conformance(
        user=staff_user, scenario_id=source.scenario_id, expected_package_digest=source.package_digest
    )
    source.refresh_from_db()
    assert result == "passed" and source.conformance_status == "passed"
    assert source.conformance_report_ref.startswith("urn:shifter:pack-conformance:")
    assert not PreparationAttempt.objects.exists() and not Range.objects.exists()


@pytest.mark.parametrize("failure", ["bytes", "stale", "inactive"])
def test_conformance_cannot_promote_changed_bytes_or_stale_identity(staff_user, preparation_pack, failure):
    root, source = preparation_pack
    digest = source.package_digest
    if failure == "bytes":
        (root / "sdl/preparation-http-smoke.sdl.yaml").write_text("changed")
    elif failure == "stale":
        digest = "sha256:" + "0" * 64
    else:
        staff_user.is_active = False
        staff_user.save()
    with pytest.raises((ValidationError, PermissionDenied)):
        validate_registered_pack_conformance(
            user=staff_user, scenario_id=source.scenario_id, expected_package_digest=digest
        )
    source.refresh_from_db()
    assert source.conformance_status == "pending"
