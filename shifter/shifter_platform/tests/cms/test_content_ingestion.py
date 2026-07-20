"""Uniform, entitlement-blind pack registration service (#1578, ADR-034).

Pins the single CMS registration boundary: it is source-agnostic and
entitlement-blind, authorizes WHO may register (never whether they were entitled
to obtain the pack), validates the incoming pack as foreign input, binds the
catalog id to the pack's validated identity, never lets a caller assert
conformance, fails closed on legacy-id shadowing and duplicates, keeps
object-backed packs non-launchable until #1567, and audits every registration.
"""

from __future__ import annotations

import dataclasses
from contextlib import suppress
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.exceptions import CMSError
from cms.models import AcesPackageSource, Scenario
from cms.scenarios.legacy_ids import ScenarioIdCollisionError
from cms.scenarios.pack_validation import PackDigestError, pack_digest
from cms.scenarios.registry import get_catalog_entry
from cms.services import PackRegistrationRequest, register_pack
from risk_register.models import AuditLog
from shared.audit import AuditAction, AuditEntityType

User = get_user_model()

pytestmark = pytest.mark.django_db

# The conformant repo pack fixtures are built with this name; a repo pack's
# catalog id must equal its validated pack identity (finding: scenario_id binding).
FIXTURE_PACK_NAME = "ingestion-fixture"


def _legacy_definition() -> dict[str, object]:
    return {
        "instances": [{"name": "A", "role": "attacker", "os_type": "kali", "xdr_agent": False}],
        "subnets": [{"name": "n", "instances": ["A"]}],
        "ngfw": False,
    }


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="ingestion-staff@example.com",
        email="ingestion-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="ingestion-regular@example.com",
        email="ingestion-regular@example.com",
        is_staff=False,
    )


@pytest.fixture
def repo_pack(make_pack, tmp_path, monkeypatch):
    """A conformant repo-backed pack under a monkeypatched ACES_PACKAGE_ROOT.

    Returns the pack's package_ref (relative to the configured package root). Its
    validated identity is ``FIXTURE_PACK_NAME``.
    """
    from django.conf import settings

    make_pack(tmp_path / "packs" / FIXTURE_PACK_NAME, name=FIXTURE_PACK_NAME)
    monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
    return f"packs/{FIXTURE_PACK_NAME}"


def _request(package_ref: str, **overrides) -> PackRegistrationRequest:
    fields = {
        "scenario_id": FIXTURE_PACK_NAME,
        "source_kind": "repo",
        "contract_kind": "aces",
        "contract_profile": "shifter",
        "package_ref": package_ref,
        "package_version": "0.1.0",
        "package_digest": "sha256:" + "a" * 64,
        "provenance": {"repo": "acme/example", "commit": "c" * 40},
    }
    fields.update(overrides)
    if "package_digest" not in overrides and fields["source_kind"] == "repo":
        from django.conf import settings

        # Malformed/missing-pack tests must reach the service's fail-closed
        # validation path; their placeholder is never persisted.
        with suppress(PackDigestError, OSError):
            fields["package_digest"] = pack_digest(Path(settings.ACES_PACKAGE_ROOT) / package_ref)
    return PackRegistrationRequest(**fields)


class TestRegisterPackHappyPath:
    def test_persists_row_and_appears_in_catalog(self, staff_user, repo_pack):
        result = register_pack(user=staff_user, request=_request(repo_pack))
        assert result.scenario_id == FIXTURE_PACK_NAME
        assert result.created is True
        row = AcesPackageSource.objects.get(scenario_id=FIXTURE_PACK_NAME)
        assert row.registered_by_id == staff_user.id
        assert get_catalog_entry(FIXTURE_PACK_NAME) is not None

    def test_records_audit_event(self, staff_user, repo_pack):
        register_pack(user=staff_user, request=_request(repo_pack))
        entries = AuditLog.objects.filter(entity_type=AuditEntityType.SCENARIO, action=AuditAction.CREATE)
        assert any(FIXTURE_PACK_NAME in str(e.new_state) for e in entries)

    def test_audit_failure_rolls_back_registration(self, staff_user, repo_pack, monkeypatch):
        def fail_audit(_event, *, strict=False):
            assert strict is True
            raise RuntimeError("audit unavailable")

        monkeypatch.setattr("cms.services._content_ingestion.audit_log", fail_audit)
        request = _request(repo_pack)
        with pytest.raises(CMSError, match="audit failed"):
            register_pack(user=staff_user, request=request)
        assert not AcesPackageSource.objects.filter(scenario_id=FIXTURE_PACK_NAME).exists()


class TestRegisterPackAuthorization:
    def test_non_staff_is_denied(self, regular_user, repo_pack):
        from django.core.exceptions import PermissionDenied

        request = _request(repo_pack)
        with pytest.raises(PermissionDenied):
            register_pack(user=regular_user, request=request)
        assert not AcesPackageSource.objects.filter(scenario_id=FIXTURE_PACK_NAME).exists()

    def test_none_user_is_rejected(self, repo_pack):
        request = _request(repo_pack)
        with pytest.raises(TypeError):
            register_pack(user=None, request=request)


class TestRegisterPackEntitlementBlind:
    def test_provenance_does_not_gate_acceptance(self, staff_user, make_pack, tmp_path, monkeypatch):
        # Two packs whose registrations differ only in provenance (a public vs a
        # private-looking origin) both succeed: nothing branches on how a pack was
        # obtained. Distinct packs (with matching identities) are used because a
        # repo pack's catalog id is bound to its validated identity.
        from django.conf import settings

        make_pack(tmp_path / "packs" / "pack-public", name="pack-public")
        make_pack(tmp_path / "packs" / "pack-private", name="pack-private")
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))

        public = register_pack(
            user=staff_user,
            request=_request("packs/pack-public", scenario_id="pack-public", provenance={"repo": "public/catalog"}),
        )
        private = register_pack(
            user=staff_user,
            request=_request("packs/pack-private", scenario_id="pack-private", provenance={"repo": "licensed/private"}),
        )
        assert public.created and private.created
        assert AcesPackageSource.objects.filter(scenario_id__in=["pack-public", "pack-private"]).count() == 2


class TestRegisterPackConformanceIsNotCallerAsserted:
    def test_registration_always_lands_non_passed(self, staff_user, repo_pack):
        # A caller cannot promote its own pack to conformance-passed; conformance
        # is established out of band by a trusted process.
        register_pack(user=staff_user, request=_request(repo_pack))
        row = AcesPackageSource.objects.get(scenario_id=FIXTURE_PACK_NAME)
        assert row.conformance_status == AcesPackageSource.ConformanceStatus.PENDING
        assert row.conformance_report_ref == ""

    def test_request_has_no_conformance_fields(self):
        field_names = {f.name for f in dataclasses.fields(PackRegistrationRequest)}
        assert "conformance_status" not in field_names
        assert "conformance_report_ref" not in field_names


class TestRegisterPackIdentityBinding:
    def test_rejects_scenario_id_not_matching_pack_identity(self, staff_user, repo_pack):
        # The pack's validated identity is FIXTURE_PACK_NAME; a different catalog
        # id would let one immutable pack be aliased under many ids. Asserting the
        # bounded message pins the identity guard specifically (a different guard
        # would carry a different message and fail this match).
        request = _request(repo_pack, scenario_id="some-other-id")
        with pytest.raises(CMSError, match="validated identity"):
            register_pack(user=staff_user, request=request)
        assert not AcesPackageSource.objects.filter(scenario_id="some-other-id").exists()


class TestRegisterPackDigestBinding:
    def test_persists_the_verified_canonical_digest(self, staff_user, repo_pack):
        request = _request(repo_pack)
        register_pack(user=staff_user, request=request)
        row = AcesPackageSource.objects.get(scenario_id=FIXTURE_PACK_NAME)
        assert row.package_digest == request.package_digest

    def test_rejects_advertised_digest_mismatch(self, staff_user, repo_pack):
        request = _request(repo_pack, package_digest="sha256:" + "b" * 64)
        with pytest.raises(CMSError, match="does not match"):
            register_pack(user=staff_user, request=request)
        assert not AcesPackageSource.objects.filter(scenario_id=FIXTURE_PACK_NAME).exists()

    def test_rejects_missing_associated_artifact_manifest(self, staff_user, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        root = make_pack(tmp_path / "packs" / "missing-manifest", name="missing-manifest")
        (root / "associated-artifacts.json").unlink()
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        request = _request("packs/missing-manifest", scenario_id="missing-manifest")
        with pytest.raises(CMSError, match="digest could not be verified"):
            register_pack(user=staff_user, request=request)

    def test_rejects_bytes_changed_after_manifest_was_sealed(self, staff_user, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        root = make_pack(tmp_path / "packs" / "mutated-pack", name="mutated-pack")
        advertised = pack_digest(root)
        (root / "docs" / "concepts.md").write_text("changed after staging\n", encoding="utf-8")
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        request = _request(
            "packs/mutated-pack",
            scenario_id="mutated-pack",
            package_digest=advertised,
        )
        with pytest.raises(CMSError, match="digest could not be verified"):
            register_pack(user=staff_user, request=request)

    def test_rejects_mutation_between_validation_and_digest_binding(
        self,
        staff_user,
        make_pack,
        tmp_path,
        monkeypatch,
    ):
        from django.conf import settings

        from cms.scenarios.pack_validation import validate_pack as upstream_validate

        root = make_pack(tmp_path / "packs" / "validation-race", name="validation-race")
        advertised = pack_digest(root)
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))

        def validate_then_mutate(pack_root):
            identity = upstream_validate(pack_root)
            (pack_root / "docs" / "concepts.md").write_text("changed after validation\n", encoding="utf-8")
            return identity

        monkeypatch.setattr("cms.services._content_ingestion.validate_pack", validate_then_mutate)
        request = _request(
            "packs/validation-race",
            scenario_id="validation-race",
            package_digest=advertised,
        )
        with pytest.raises(CMSError, match="digest could not be verified"):
            register_pack(user=staff_user, request=request)
        assert not AcesPackageSource.objects.filter(scenario_id="validation-race").exists()


class TestRegisterPackFailsClosed:
    """Each guard is isolated so deleting it fails a test, not masked by an
    adjacent guard that raises the same CMSError for the same crafted input.
    """

    def test_rejects_shadow_of_yaml_default(self, staff_user, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        # The pack's validated identity equals the shadowed id, so the identity
        # guard would NOT fire: deleting the shadow branch would let registration
        # succeed, failing this test.
        make_pack(tmp_path / "packs" / "basic", name="basic")
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        request = _request("packs/basic", scenario_id="basic")
        with pytest.raises(CMSError, match="shadow"):
            register_pack(user=staff_user, request=request)
        assert not AcesPackageSource.objects.filter(scenario_id="basic").exists()

    def test_rejects_shadow_of_active_db_custom(self, staff_user, make_pack, tmp_path, monkeypatch, valid_db_scenario):
        from django.conf import settings

        make_pack(tmp_path / "packs" / valid_db_scenario, name=valid_db_scenario)
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        request = _request(f"packs/{valid_db_scenario}", scenario_id=valid_db_scenario)
        with pytest.raises(CMSError, match="shadow"):
            register_pack(user=staff_user, request=request)

    def test_rejects_legacy_creation_after_pack_registration(self, staff_user, repo_pack):
        register_pack(user=staff_user, request=_request(repo_pack))

        definition = _legacy_definition()
        with pytest.raises(ScenarioIdCollisionError, match="registered ACES pack"):
            Scenario.objects.create(
                scenario_id=FIXTURE_PACK_NAME,
                name="Late Legacy Shadow",
                description="Must not claim a registered pack id.",
                definition=definition,
                created_by=staff_user,
                updated_by=staff_user,
            )
        assert not Scenario.objects.filter(scenario_id=FIXTURE_PACK_NAME).exists()

    def test_rejects_legacy_restore_after_pack_registration(self, staff_user, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        scenario_id = "restore-shadow"
        scenario = Scenario.objects.create(
            scenario_id=scenario_id,
            name="Restore Shadow",
            description="Soft-deleted before pack registration.",
            definition=_legacy_definition(),
            created_by=staff_user,
            updated_by=staff_user,
        )
        scenario.deleted_at = timezone.now()
        scenario.save(update_fields=["deleted_at", "updated_at"])
        make_pack(tmp_path / "packs" / scenario_id, name=scenario_id)
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        register_pack(
            user=staff_user,
            request=_request(f"packs/{scenario_id}", scenario_id=scenario_id),
        )

        scenario.deleted_at = None
        with pytest.raises(ScenarioIdCollisionError, match="registered ACES pack"):
            scenario.save(update_fields=["deleted_at", "updated_at"])
        assert not Scenario.objects.filter(scenario_id=scenario_id).exists()
        assert Scenario.all_objects.get(pk=scenario.pk).is_deleted

    def test_rejects_duplicate_registration(self, staff_user, repo_pack):
        register_pack(user=staff_user, request=_request(repo_pack))
        duplicate_request = _request(repo_pack)
        with pytest.raises(CMSError, match="already registered"):
            register_pack(user=staff_user, request=duplicate_request)
        assert AcesPackageSource.objects.filter(scenario_id=FIXTURE_PACK_NAME).count() == 1

    def test_rejects_malformed_pack(self, staff_user, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        make_pack(tmp_path / "packs" / "broken-pack", name="broken-pack", sdl=None)
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        request = _request("packs/broken-pack", scenario_id="broken-pack")
        with pytest.raises(CMSError, match="ingestion validation"):
            register_pack(user=staff_user, request=request)

    def test_rejects_missing_repo_pack(self, staff_user, tmp_path, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        request = _request("packs/does-not-exist")
        with pytest.raises(CMSError, match="ingestion validation"):
            register_pack(user=staff_user, request=request)

    def test_rejects_package_ref_escaping_root(self, staff_user, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        # A real, conformant pack lives OUTSIDE the configured root. Only the
        # containment check rejects it: delete that check and the ref resolves to
        # the real pack, validates, and its identity matches, so registration
        # would succeed and fail this test.
        root = tmp_path / "root"
        root.mkdir()
        make_pack(tmp_path / "outside" / "escape-target", name="escape-target")
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(root))
        request = _request("../outside/escape-target", scenario_id="escape-target")
        with pytest.raises(CMSError, match="escapes the configured package root"):
            register_pack(user=staff_user, request=request)
        assert not AcesPackageSource.objects.filter(scenario_id="escape-target").exists()


class TestRegisterPackObjectSource:
    def test_object_registers_pending_and_not_launchable(self, staff_user):
        # Object-backed packs skip content resolution (no local resolver until
        # #1567); they register non-launchable and are never conformance-passed.
        result = register_pack(
            user=staff_user,
            request=_request("object-key/pack", scenario_id="obj-pending", source_kind="object"),
        )
        assert result.created is True
        row = AcesPackageSource.objects.get(scenario_id="obj-pending")
        assert row.conformance_status == AcesPackageSource.ConformanceStatus.PENDING
        assert get_catalog_entry("obj-pending")["launchable"] is False


@pytest.fixture
def valid_db_scenario(staff_user):
    Scenario.objects.create(
        scenario_id="db-custom-shadow",
        name="DB Custom Shadow",
        description="Active DB custom used to test no-shadow.",
        definition=_legacy_definition(),
        created_by=staff_user,
        updated_by=staff_user,
    )
    return "db-custom-shadow"


def test_request_is_immutable():
    req = _request("packs/fixture")
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.scenario_id = "mutated"  # type: ignore[misc]
