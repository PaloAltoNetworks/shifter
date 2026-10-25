"""In-box bootstrap seed through the uniform ingestion path (#1578, ADR-034).

The in-box seed is loaded through the SAME ``register_pack`` service an
operator uses — there is no privileged code path. The shipped manifest declares
the in-box seed; these tests prove the mechanism end-to-end with a
temporary manifest and confirm the shipped manifest parses to the expected
declaration.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

import pytest
import yaml
from django.contrib.auth import get_user_model

from cms.exceptions import CMSError
from cms.management.commands.bootstrap_inbox_catalog import SYSTEM_ACTOR_USERNAME
from cms.models import RaesPackageSource
from cms.scenarios.inbox import SHIPPED_INBOX_MANIFEST, load_inbox_manifest, register_inbox_packs
from cms.scenarios.pack_validation import PackDigestError, pack_digest
from cms.scenarios.registry import get_catalog_entry

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_actor(db):
    return User.objects.create_user(
        username="inbox-bootstrap@example.com",
        email="inbox-bootstrap@example.com",
        is_staff=True,
    )


def _write_manifest(path: Path, entries: list[object]) -> Path:
    path.write_text(yaml.safe_dump({"packs": entries}), encoding="utf-8")
    return path


def _inbox_entry(package_ref: str, **overrides) -> dict:
    entry = {
        "scenario_id": "inbox-fixture",
        "source_kind": "repo",
        "contract_kind": "raes",
        "contract_profile": "shifter",
        "package_ref": package_ref,
        "package_version": "0.1.0",
        "package_digest": "sha256:" + "a" * 64,
        "provenance": {"repo": "Brad-Edwards/shifter"},
    }
    entry.update(overrides)
    if "package_digest" not in overrides and entry["source_kind"] == "repo":
        from django.conf import settings

        with suppress(PackDigestError, OSError):
            entry["package_digest"] = pack_digest(Path(settings.RAES_PACKAGE_ROOT) / package_ref)
    return entry


class TestShippedManifest:
    def test_shipped_manifest_exists_and_parses_to_a_list(self):
        packs = load_inbox_manifest(SHIPPED_INBOX_MANIFEST)
        assert isinstance(packs, list)

    def test_shipped_manifest_contains_the_smoke_linux_packs(self):
        packs = load_inbox_manifest(SHIPPED_INBOX_MANIFEST)
        # smoke-linux is the GCP-authored scenario; smoke-linux-aws is its
        # portable-addressing variant for the AWS EC2 range backend (#1826).
        assert [pack.scenario_id for pack in packs] == ["smoke-linux", "smoke-linux-aws"]

    def test_shipped_packs_register_and_pass_release_conformance(self, admin_actor, monkeypatch):
        """Every shipped in-box pack has a valid byte-bound digest and conforms.

        Registering the real shipped manifest under the repo package root exercises
        each pack's digest verification and the trusted release-conformance gate
        (RAES load + plan + Shifter target + apply-contract) that the deploy's
        bootstrap_inbox_catalog runs -- so a bad pack fails here, not at deploy.
        """
        from django.conf import settings

        platform_root = Path(__file__).resolve().parents[2]
        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(platform_root))

        register_inbox_packs(actor=admin_actor, manifest_path=SHIPPED_INBOX_MANIFEST)

        assert RaesPackageSource.objects.filter(scenario_id="smoke-linux").exists()
        assert RaesPackageSource.objects.filter(scenario_id="smoke-linux-aws").exists()


class TestRegisterInboxPacks:
    def test_registers_each_entry_through_the_service(self, admin_actor, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        make_pack(tmp_path / "packs" / "inbox-fixture", name="inbox-fixture")
        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
        manifest = _write_manifest(tmp_path / "manifest.yaml", [_inbox_entry("packs/inbox-fixture")])

        registered = register_inbox_packs(actor=admin_actor, manifest_path=manifest)

        assert [r.scenario_id for r in registered] == ["inbox-fixture"]
        assert RaesPackageSource.objects.filter(scenario_id="inbox-fixture").exists()
        assert get_catalog_entry("inbox-fixture") is not None

    def test_is_idempotent(self, admin_actor, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        make_pack(tmp_path / "packs" / "inbox-fixture", name="inbox-fixture")
        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
        manifest = _write_manifest(tmp_path / "manifest.yaml", [_inbox_entry("packs/inbox-fixture")])

        first = register_inbox_packs(actor=admin_actor, manifest_path=manifest)
        second = register_inbox_packs(actor=admin_actor, manifest_path=manifest)

        assert len(first) == 1
        assert second == []  # exact service-level retry is a no-op
        assert RaesPackageSource.objects.filter(scenario_id="inbox-fixture").count() == 1

    def test_retry_rejects_manifest_identity_drift(self, admin_actor, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        make_pack(tmp_path / "packs" / "inbox-fixture", name="inbox-fixture")
        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
        manifest = _write_manifest(tmp_path / "manifest.yaml", [_inbox_entry("packs/inbox-fixture")])
        register_inbox_packs(actor=admin_actor, manifest_path=manifest)

        drifted = _inbox_entry("packs/inbox-fixture", package_digest="sha256:" + "b" * 64)
        _write_manifest(manifest, [drifted])
        with pytest.raises(CMSError, match="different identity"):
            register_inbox_packs(actor=admin_actor, manifest_path=manifest)

    def test_empty_manifest_is_a_noop(self, admin_actor, tmp_path):
        manifest = _write_manifest(tmp_path / "manifest.yaml", [])
        assert register_inbox_packs(actor=admin_actor, manifest_path=manifest) == []

    def test_absent_manifest_fails_closed(self, admin_actor, tmp_path):
        with pytest.raises(CMSError, match="manifest is missing"):
            register_inbox_packs(actor=admin_actor, manifest_path=tmp_path / "nope.yaml")

    @pytest.mark.parametrize(
        "body",
        [
            "",
            "- not\n- a\n- mapping\n",
            "wrong_key: []\n",
            "packs: {}\n",
            "packs:\n  - not-a-mapping\n",
            "packs:\n  - package_ref: packs/missing-id\n",
            "packs:\n  - scenario_id: bad\n    unsupported_field: true\n",
        ],
    )
    def test_malformed_manifest_fails_closed(self, admin_actor, tmp_path, body):
        manifest = tmp_path / "manifest.yaml"
        manifest.write_text(body, encoding="utf-8")

        with pytest.raises(CMSError, match="in-box pack manifest"):
            register_inbox_packs(actor=admin_actor, manifest_path=manifest)
        assert RaesPackageSource.objects.count() == 0

    def test_later_pack_failure_rolls_back_earlier_registration(
        self,
        admin_actor,
        make_pack,
        tmp_path,
        monkeypatch,
    ):
        from django.conf import settings

        make_pack(tmp_path / "packs" / "inbox-first", name="inbox-first")
        make_pack(tmp_path / "packs" / "inbox-second", name="inbox-second")
        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
        manifest = _write_manifest(
            tmp_path / "manifest.yaml",
            [
                _inbox_entry("packs/inbox-first", scenario_id="inbox-first"),
                _inbox_entry(
                    "packs/inbox-second",
                    scenario_id="inbox-second",
                    package_digest="sha256:" + "b" * 64,
                ),
            ],
        )

        with pytest.raises(CMSError, match="does not match"):
            register_inbox_packs(actor=admin_actor, manifest_path=manifest)
        assert not RaesPackageSource.objects.filter(scenario_id__in=["inbox-first", "inbox-second"]).exists()


class TestBootstrapCommand:
    def test_command_uses_bounded_non_login_system_actor_when_omitted(self, monkeypatch):
        from django.conf import settings
        from django.core.management import call_command

        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(SHIPPED_INBOX_MANIFEST.parents[3]))

        call_command("bootstrap_inbox_catalog")

        actor = User.objects.get(username=SYSTEM_ACTOR_USERNAME)
        assert actor.email == ""
        assert actor.is_active is True
        assert actor.is_staff is True
        assert actor.is_superuser is False
        assert actor.has_usable_password() is False
        assert RaesPackageSource.objects.filter(scenario_id="smoke-linux", registered_by=actor).exists()

    def test_command_rejects_a_conflicting_system_actor(self):
        from django.core.management import CommandError, call_command

        User.objects.create_user(username=SYSTEM_ACTOR_USERNAME, password="usable", is_staff=True)

        with pytest.raises(CommandError, match="system actor conflicts"):
            call_command("bootstrap_inbox_catalog")

    def test_shipped_upgrade_replaces_only_the_declared_previous_digest(self, admin_actor, monkeypatch):
        from django.conf import settings
        from django.core.management import CommandError, call_command

        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(SHIPPED_INBOX_MANIFEST.parents[3]))
        request = load_inbox_manifest()[0]
        source = RaesPackageSource.objects.create(
            scenario_id=request.scenario_id,
            source_kind=request.source_kind,
            contract_kind=request.contract_kind,
            contract_profile=request.contract_profile,
            package_ref=request.package_ref,
            package_version="0.1.0",
            package_digest=request.expected_package_digest,
            provenance=request.provenance,
            conformance_status="passed",
            conformance_report_ref="release://previous-version",
            registered_by=admin_actor,
        )
        original_id = source.id
        call_command("bootstrap_inbox_catalog", "--actor", admin_actor.username)
        source.refresh_from_db()
        assert source.id == original_id
        assert source.package_digest == request.package_digest
        assert source.package_version == request.package_version
        assert source.conformance_status == "passed"
        # A later customized tenant revision must not be overwritten by deploy.
        source.package_digest = "sha256:" + "f" * 64
        source.save()
        with pytest.raises(CommandError, match="conflicts"):
            call_command("bootstrap_inbox_catalog", "--actor", admin_actor.username)

    def test_command_registers_and_promotes_the_shipped_smoke_linux_pack(self, admin_actor, monkeypatch):
        from django.conf import settings
        from django.core.management import call_command

        # The shipped pack lives under shifter_platform/ so it bakes into the
        # container image at /app, where RAES_PACKAGE_ROOT defaults. In a source
        # checkout RAES_PACKAGE_ROOT defaults to the repo root, so point it at the
        # shifter_platform root (manifest parents[3]) where the pack resolves.
        monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(SHIPPED_INBOX_MANIFEST.parents[3]))
        call_command("bootstrap_inbox_catalog", "--actor", admin_actor.username)
        source = RaesPackageSource.objects.get(scenario_id="smoke-linux")
        shipped = next(r for r in load_inbox_manifest(SHIPPED_INBOX_MANIFEST) if r.scenario_id == "smoke-linux")
        assert source.conformance_status == RaesPackageSource.ConformanceStatus.PASSED
        assert source.conformance_report_ref == (
            f"release://cms/scenarios/inbox_packs/smoke-linux@{shipped.package_version}"
        )
        assert get_catalog_entry("smoke-linux")["launchable"] is True

    def test_command_errors_on_unknown_actor(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError):
            call_command("bootstrap_inbox_catalog", "--actor", "nobody@example.com")

    def test_command_surfaces_missing_shipped_manifest(self, admin_actor, tmp_path, monkeypatch):
        from django.core.management import CommandError, call_command

        monkeypatch.setattr("cms.scenarios.inbox.SHIPPED_INBOX_MANIFEST", tmp_path / "missing.yaml")
        with pytest.raises(CommandError, match="manifest is missing"):
            call_command("bootstrap_inbox_catalog", "--actor", admin_actor.username)
