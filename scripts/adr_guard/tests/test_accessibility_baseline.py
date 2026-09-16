"""Tests for the ADR-055 accessibility baseline non-growth ratchet."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "adr_guard.py"
SPEC = importlib.util.spec_from_file_location("adr_guard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ADR_GUARD = importlib.util.module_from_spec(SPEC)
sys.modules["adr_guard"] = ADR_GUARD
SPEC.loader.exec_module(ADR_GUARD)

CHECK_MODULE = ADR_GUARD.accessibility_baseline
BASELINE_REL = "shifter/shifter_platform/frontend/e2e/a11y/baseline.json"


class AccessibilityBaselineRatchetTests(unittest.TestCase):
    def _repo(self, tmp: str, *, head: object, exceptions: object = None) -> Path:
        root = Path(tmp)
        baseline = root / BASELINE_REL
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(head if isinstance(head, str) else json.dumps(head), encoding="utf-8")
        exc_dir = root / "docs" / "adr"
        exc_dir.mkdir(parents=True, exist_ok=True)
        (exc_dir / "exceptions.yaml").write_text(json.dumps(exceptions or []), encoding="utf-8")
        return root

    def _run(self, root: Path, *, base: list[str] | None, enforce: bool = True):
        # base=None models "no baseline file on the base branch" (enrollment).
        base_raw = None if base is None else json.dumps(base)
        with (
            patch.object(CHECK_MODULE, "_boundary_mock_base_reference_candidates", return_value=["origin/dev"]),
            patch.object(CHECK_MODULE, "_git_text", return_value=base_raw),
            patch.object(CHECK_MODULE, "_a11y_enforced", return_value=enforce),
        ):
            return CHECK_MODULE.check_accessibility_baseline(root, None)

    def test_empty_baseline_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, head=[])
            self.assertEqual(self._run(root, base=[]), [])

    def test_shrink_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, head=[])
            self.assertEqual(self._run(root, base=["s|p|rule|wcag2aa|.x"]), [])

    def test_growth_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, head=["s|p|color-contrast|wcag2aa|.x"])
            violations = self._run(root, base=[])
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-055-R4")

    def test_growth_allowed_when_exactly_waived(self) -> None:
        fp = "s|p|color-contrast|wcag2aa|.x"
        waiver = [
            {
                "rule_id": "ADR-055-R6",
                "owner": "team",
                "reason": "tracked",
                "expires_on": "2099-01-01",
                "fingerprints": [fp],
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, head=[fp], exceptions=waiver)
            self.assertEqual(self._run(root, base=[]), [])

    def test_growth_not_waived_by_non_adr055_exception(self) -> None:
        # The rule_id scoping guard must hold: a waiver targeting a different ADR
        # (even with a matching fingerprint) must NOT suppress a real growth
        # violation, or an unrelated waiver could silently hide a11y debt.
        fp = "s|p|color-contrast|wcag2aa|.x"
        unrelated = [
            {
                "rule_id": "ADR-019-R2",
                "owner": "team",
                "reason": "unrelated",
                "expires_on": "2099-01-01",
                "fingerprints": [fp],
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, head=[fp], exceptions=unrelated)
            violations = self._run(root, base=[])
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-055-R4")

    def test_malformed_head_baseline_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, head="{not-a-list}")
            violations = self._run(root, base=[])
            self.assertEqual(len(violations), 1)

    def test_initial_enrollment_when_base_absent_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, head=["s|p|rule|wcag2aa|.x"])
            self.assertEqual(self._run(root, base=None), [])

    def test_unresolvable_base_fails_closed_only_when_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, head=["s|p|rule|wcag2aa|.x"])
            with (
                patch.object(CHECK_MODULE, "_boundary_mock_base_reference_candidates", return_value=[]),
                patch.object(CHECK_MODULE, "_a11y_enforced", return_value=True),
            ):
                self.assertEqual(len(CHECK_MODULE.check_accessibility_baseline(root, None)), 1)
            with (
                patch.object(CHECK_MODULE, "_boundary_mock_base_reference_candidates", return_value=[]),
                patch.object(CHECK_MODULE, "_a11y_enforced", return_value=False),
            ):
                self.assertEqual(CHECK_MODULE.check_accessibility_baseline(root, None), [])


if __name__ == "__main__":
    unittest.main()
