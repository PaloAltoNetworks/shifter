"""Tests for the fail-closed INSTALLED_APPS classification check (#1523)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "adr_guard.py"
SPEC = importlib.util.spec_from_file_location("adr_guard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ADR_GUARD = importlib.util.module_from_spec(SPEC)
sys.modules["adr_guard"] = ADR_GUARD
SPEC.loader.exec_module(ADR_GUARD)

EXPECTED_PACKAGES = {
    "shared",
    "engine",
    "cms",
    "management",
    "mission_control",
    "ctf",
    "config",
    "risk_register",
}

_CLASSIFICATION_YAML = """\
classification:
  domain:
    - engine
    - cms
    - management
    - ctf
    - risk_register
  presentation:
    - mission_control
  support_contracts:
    - shared
  support_composition:
    - config

allowed:
  engine:
    - shared
"""


def _write_repo(
    root: Path,
    *,
    installed_apps_body: str,
    app_packages: set[str],
    classification_yaml: str = _CLASSIFICATION_YAML,
) -> None:
    policy = root / "scripts" / "check_layer_imports" / "layer_imports.yaml"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(classification_yaml, encoding="utf-8")

    platform = root / "shifter" / "shifter_platform"
    for pkg in app_packages:
        apps_py = platform / pkg / "apps.py"
        apps_py.parent.mkdir(parents=True, exist_ok=True)
        cls = "".join(part.title() for part in pkg.split("_"))
        apps_py.write_text(
            f"from django.apps import AppConfig\n\n\nclass {cls}Config(AppConfig):\n    name = {pkg!r}\n",
            encoding="utf-8",
        )

    settings = platform / "config" / "settings.py"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(installed_apps_body, encoding="utf-8")


class InstalledAppsClassifiedTests(unittest.TestCase):
    def test_real_repo_passes(self) -> None:
        violations = ADR_GUARD.check_installed_apps_classified(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(violations, [])

    def test_canonical_classification_matches_expected_packages(self) -> None:
        classified = ADR_GUARD._classified_packages(ADR_GUARD.REPO_ROOT)
        self.assertEqual(classified, EXPECTED_PACKAGES)

    def test_adr_guard_layers_have_set_equality_with_classification(self) -> None:
        classified = ADR_GUARD._classified_packages(ADR_GUARD.REPO_ROOT)
        self.assertEqual(set(ADR_GUARD.LAYERS), classified)

    def test_consistent_temp_repo_passes(self) -> None:
        apps = {"engine", "cms", "management", "ctf", "risk_register", "mission_control", "shared", "config"}
        body = (
            "INSTALLED_APPS = [\n"
            "    'django.contrib.admin',\n"
            + "".join(f"    '{p}.apps.Config',\n" for p in sorted(apps))
            + "]\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_repo(root, installed_apps_body=body, app_packages=apps)
            self.assertEqual(ADR_GUARD.check_installed_apps_classified(root, None), [])

    def test_unclassified_installed_app_fails_closed(self) -> None:
        apps = {"engine", "cms", "management", "ctf", "risk_register", "mission_control", "shared", "config", "newapp"}
        body = "INSTALLED_APPS = [\n" + "".join(f"    '{p}.apps.Config',\n" for p in sorted(apps)) + "]\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # newapp has an AppConfig on disk + is installed but is NOT classified.
            _write_repo(root, installed_apps_body=body, app_packages=apps)
            violations = ADR_GUARD.check_installed_apps_classified(root, None)
            self.assertTrue(any("newapp" in v.message for v in violations))
            self.assertTrue(all(v.rule_id == "ADR-001-R3" for v in violations))

    def test_stale_classification_entry_fails_closed(self) -> None:
        # Classification names a package with no local AppConfig on disk.
        apps = {"engine", "cms", "management", "ctf", "mission_control", "shared", "config"}  # risk_register missing
        body = "INSTALLED_APPS = [\n" + "".join(f"    '{p}.apps.Config',\n" for p in sorted(apps)) + "]\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_repo(root, installed_apps_body=body, app_packages=apps)
            violations = ADR_GUARD.check_installed_apps_classified(root, None)
            self.assertTrue(any("risk_register" in v.message and "stale" in v.message for v in violations))

    def test_dynamic_installed_apps_entry_fails_closed(self) -> None:
        apps = {"engine", "cms", "management", "ctf", "risk_register", "mission_control", "shared", "config"}
        body = (
            "INSTALLED_APPS = [\n"
            + "".join(f"    '{p}.apps.Config',\n" for p in sorted(apps))
            + "]\n"
            "if something:\n"
            "    INSTALLED_APPS.append(dynamic_value)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_repo(root, installed_apps_body=body, app_packages=apps)
            violations = ADR_GUARD.check_installed_apps_classified(root, None)
            self.assertTrue(any("cannot resolve" in v.message for v in violations))

    def test_augassign_dynamic_list_fails_closed(self) -> None:
        apps = {"engine", "cms", "management", "ctf", "risk_register", "mission_control", "shared", "config"}
        body = (
            "INSTALLED_APPS = [\n"
            + "".join(f"    '{p}.apps.Config',\n" for p in sorted(apps))
            + "]\n"
            "INSTALLED_APPS += EXTRA_APPS\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_repo(root, installed_apps_body=body, app_packages=apps)
            violations = ADR_GUARD.check_installed_apps_classified(root, None)
            self.assertTrue(any("cannot resolve" in v.message for v in violations))

    def test_augassign_literal_unclassified_app_fails_closed(self) -> None:
        apps = {"engine", "cms", "management", "ctf", "risk_register", "mission_control", "shared", "config", "newapp"}
        body = (
            "INSTALLED_APPS = [\n"
            + "".join(f"    '{p}.apps.Config',\n" for p in sorted(apps - {'newapp'}))
            + "]\n"
            "INSTALLED_APPS += ['newapp.apps.Config']\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # newapp is added via += as a literal, has an AppConfig, but is unclassified.
            _write_repo(root, installed_apps_body=body, app_packages=apps)
            violations = ADR_GUARD.check_installed_apps_classified(root, None)
            self.assertTrue(any("newapp" in v.message for v in violations))

    def test_conditional_string_append_is_resolved(self) -> None:
        apps = {"engine", "cms", "management", "ctf", "risk_register", "mission_control", "shared", "config"}
        body = (
            "INSTALLED_APPS = [\n"
            + "".join(f"    '{p}.apps.Config',\n" for p in sorted(apps))
            + "]\n"
            "if flag:\n"
            "    INSTALLED_APPS.append('mozilla_django_oidc')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_repo(root, installed_apps_body=body, app_packages=apps)
            # mozilla_django_oidc is third-party (no local AppConfig) -> ignored, no violation.
            self.assertEqual(ADR_GUARD.check_installed_apps_classified(root, None), [])


if __name__ == "__main__":
    unittest.main()
