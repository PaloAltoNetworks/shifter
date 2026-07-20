"""In-box catalog bootstrap through the uniform ingestion path (#1578, ADR-034).

The in-box catalog is loaded through the SAME ``register_pack`` service an
operator uses — there is no privileged code path. There are no conformant default
packs yet, so the shipped manifest is empty; these tests prove the mechanism
end-to-end with a temporary manifest and confirm the shipped manifest stays a
valid, empty declaration.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

import pytest
import yaml
from django.contrib.auth import get_user_model

from cms.exceptions import CMSError
from cms.models import AcesPackageSource
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
        "contract_kind": "aces",
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
            entry["package_digest"] = pack_digest(Path(settings.ACES_PACKAGE_ROOT) / package_ref)
    return entry


class TestShippedManifest:
    def test_shipped_manifest_exists_and_parses_to_a_list(self):
        packs = load_inbox_manifest(SHIPPED_INBOX_MANIFEST)
        assert isinstance(packs, list)

    def test_shipped_manifest_is_empty_no_default_packs_yet(self):
        # No conformant default scenario packs ship yet (program #1584).
        assert load_inbox_manifest(SHIPPED_INBOX_MANIFEST) == []


class TestRegisterInboxPacks:
    def test_registers_each_entry_through_the_service(self, admin_actor, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        make_pack(tmp_path / "packs" / "inbox-fixture", name="inbox-fixture")
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        manifest = _write_manifest(tmp_path / "manifest.yaml", [_inbox_entry("packs/inbox-fixture")])

        registered = register_inbox_packs(actor=admin_actor, manifest_path=manifest)

        assert [r.scenario_id for r in registered] == ["inbox-fixture"]
        assert AcesPackageSource.objects.filter(scenario_id="inbox-fixture").exists()
        assert get_catalog_entry("inbox-fixture") is not None

    def test_is_idempotent(self, admin_actor, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        make_pack(tmp_path / "packs" / "inbox-fixture", name="inbox-fixture")
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
        manifest = _write_manifest(tmp_path / "manifest.yaml", [_inbox_entry("packs/inbox-fixture")])

        first = register_inbox_packs(actor=admin_actor, manifest_path=manifest)
        second = register_inbox_packs(actor=admin_actor, manifest_path=manifest)

        assert len(first) == 1
        assert second == []  # exact service-level retry is a no-op
        assert AcesPackageSource.objects.filter(scenario_id="inbox-fixture").count() == 1

    def test_retry_rejects_manifest_identity_drift(self, admin_actor, make_pack, tmp_path, monkeypatch):
        from django.conf import settings

        make_pack(tmp_path / "packs" / "inbox-fixture", name="inbox-fixture")
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
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
        assert AcesPackageSource.objects.count() == 0

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
        monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
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
        assert not AcesPackageSource.objects.filter(scenario_id__in=["inbox-first", "inbox-second"]).exists()


class TestBootstrapCommand:
    def test_command_runs_against_shipped_empty_manifest(self, admin_actor):
        from django.core.management import call_command

        # The shipped manifest is empty today: the command is a clean no-op.
        call_command("bootstrap_inbox_catalog", "--actor", admin_actor.username)
        assert AcesPackageSource.objects.count() == 0

    def test_command_errors_on_unknown_actor(self, db):
        from django.core.management import CommandError, call_command

        with pytest.raises(CommandError):
            call_command("bootstrap_inbox_catalog", "--actor", "nobody@example.com")

    def test_command_surfaces_missing_shipped_manifest(self, admin_actor, tmp_path, monkeypatch):
        from django.core.management import CommandError, call_command

        monkeypatch.setattr("cms.scenarios.inbox.SHIPPED_INBOX_MANIFEST", tmp_path / "missing.yaml")
        with pytest.raises(CommandError, match="manifest is missing"):
            call_command("bootstrap_inbox_catalog", "--actor", admin_actor.username)
