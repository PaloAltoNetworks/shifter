"""Tests for the production-path quality-ownership contract and gate (#1530).

Covers the shared contract module (scripts/quality_ownership/contract.py), the
fail-closed classifier CLI (classify_paths.py), and the adr_guard
`quality-path-ownership` conformance check. Negative fixtures are the
load-bearing evidence: each proves the gate fails closed on a real regression
(unknown path, rename, ownership gap, advisory/missing job, package drift,
unreachable routing, docs-routes-production).

Fixtures are synthetic filesystem repos under tempfile — no mocks — matching
the adr_guard test idiom. The check enumerates the estate via _walk_all_files
when the repo is not a git worktree, so every scaffolding file the fixture
writes is classified by the synthetic contract.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_REAL_CONTRACT = _SCRIPTS_DIR / "quality_ownership" / "contract.py"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from quality_ownership import classify_paths  # noqa: E402
from quality_ownership import contract as C  # noqa: E402


def _load_adr_guard():
    spec = importlib.util.spec_from_file_location("adr_guard", _SCRIPTS_DIR / "adr_guard" / "adr_guard.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["adr_guard"] = module
    spec.loader.exec_module(module)
    return module


ADR_GUARD = _load_adr_guard()


# --------------------------------------------------------------------------- #
# Synthetic fixtures
# --------------------------------------------------------------------------- #
DEFAULT_CLASSIFICATION = {
    "classification": {"domain": ["alpha"], "support_contracts": ["common"]},
}

DEFAULT_CONTRACT = {
    "schema_version": 1,
    "force_full_matrix": [
        ".github/workflows/**",
        ".github/quality-path-filters.yaml",
    ],
    "quality_units": [
        {
            "id": "alpha",
            "paths": ["src/alpha/**"],
            "packages": ["alpha"],
            "sonar": True,
            "responsibilities": {
                "lint": ["alpha-lint"],
                "security": ["alpha-sast"],
                "test": ["alpha-tests"],
            },
        },
        {
            "id": "common",
            "paths": ["common/**"],
            "packages": ["common"],
            "sonar": False,
            "responsibilities": {
                "lint": ["common-lint"],
                "security": ["common-sast"],
                "test": ["common-tests"],
            },
        },
    ],
    "exclusions": [
        {"type": "docs", "reason": "docs prose", "paths": ["docs/**"]},
        {
            "type": "config",
            "reason": "guard tooling scaffolding",
            "paths": [
                "scripts/quality_ownership/**",
                "scripts/check_layer_imports/**",
            ],
        },
    ],
}

DEFAULT_ESTATE = ["src/alpha/mod.py", "common/lib.py", "docs/readme.md"]


def _gated_if(category: str, *, test: bool = False) -> str:
    inner = f"(needs.paths.outputs.run_all == 'true' || needs.paths.outputs.{category} == 'true')"
    if test:
        inner = f"!inputs.skip_tests && ({inner})"
    return "${{ " + inner + " }}"


_MATRIX_OUTPUT = {"mcp-lint": "mcp_lint_packages", "mcp-tests": "mcp_test_packages"}


def synthetic_workflow(contract_dict: dict) -> str:
    """Generate a _quality.yml whose paths-job outputs and per-responsibility
    jobs match a contract, so the output-wiring, matrix-consumption, and routing
    checks pass for a valid contract. Negative tests mutate the result."""
    contract = C.build_contract(contract_dict)
    emitted = C.compute_outputs(contract, None, run_full_matrix=True).keys()
    outputs = {key: "${{ steps.detect.outputs." + key + " }}" for key in emitted}
    jobs = {"paths": {"runs-on": "ubuntu-latest", "outputs": outputs, "steps": [{"run": "true"}]}}
    for unit in contract.units:
        for resp, refs in unit.responsibilities.items():
            for ref in refs:
                if ref.job in jobs:
                    continue
                if ref.matrix:
                    matrix_key = ref.matrix[0][0]
                    output = _MATRIX_OUTPUT.get(ref.job, f"{matrix_key}s")
                    any_output = "mcp_lint_any" if ref.job == "mcp-lint" else "mcp_test_any"
                    jobs[ref.job] = {
                        "needs": ["paths"],
                        "if": "${{ needs.paths.outputs." + any_output + " == 'true' }}",
                        "strategy": {"matrix": {matrix_key: "${{ fromJSON(needs.paths.outputs." + output + ") }}"}},
                    }
                else:
                    jobs[ref.job] = {"needs": ["paths"], "if": _gated_if(unit.id, test=(resp == "test"))}
    return yaml.safe_dump({"name": "Quality", "on": "workflow_call", "jobs": jobs})


def _classification_yaml(cls: dict) -> str:
    """Render layer_imports.yaml in the exact 2-space/4-space shape the
    adr_guard hand-rolled classification reader (_iter_yaml_section) expects."""
    lines = ["classification:"]
    for bucket, packages in cls["classification"].items():
        lines.append(f"  {bucket}:")
        for pkg in packages:
            lines.append(f"    - {pkg}")
    return "\n".join(lines) + "\n"


def write_repo(
    root: Path,
    *,
    contract: dict | None = None,
    workflow: str | None = None,
    classification: dict | None = None,
    estate: list[str] | None = None,
) -> None:
    qo = root / "scripts" / "quality_ownership"
    qo.mkdir(parents=True, exist_ok=True)
    shutil.copy(_REAL_CONTRACT, qo / "contract.py")
    (qo / "__init__.py").write_text("", encoding="utf-8")

    gh = root / ".github"
    (gh / "workflows").mkdir(parents=True, exist_ok=True)
    (gh / "quality-path-filters.yaml").write_text(
        yaml.safe_dump(contract if contract is not None else DEFAULT_CONTRACT),
        encoding="utf-8",
    )
    (gh / "workflows" / "_quality.yml").write_text(
        workflow
        if workflow is not None
        else synthetic_workflow(contract if contract is not None else DEFAULT_CONTRACT),
        encoding="utf-8",
    )

    cli = root / "scripts" / "check_layer_imports"
    cli.mkdir(parents=True, exist_ok=True)
    (cli / "layer_imports.yaml").write_text(
        _classification_yaml(classification if classification is not None else DEFAULT_CLASSIFICATION),
        encoding="utf-8",
    )

    for rel in estate if estate is not None else DEFAULT_ESTATE:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")


def run_check(root: Path):
    return ADR_GUARD.check_quality_path_ownership(root, None)


def messages(violations) -> str:
    return "\n".join(v.message for v in violations)


# --------------------------------------------------------------------------- #
# contract.py: schema validation
# --------------------------------------------------------------------------- #
class SchemaValidationTests(unittest.TestCase):
    def test_default_contract_is_valid(self):
        self.assertEqual(C.validate_schema(DEFAULT_CONTRACT), [])
        contract = C.build_contract(DEFAULT_CONTRACT)
        self.assertEqual(len(contract.units), 2)

    def test_wrong_schema_version_rejected(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["schema_version"] = 2
        self.assertTrue(any("schema_version" in e for e in C.validate_schema(data)))

    def test_unknown_top_level_key_rejected(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["bogus"] = []
        self.assertTrue(any("unknown top-level" in e for e in C.validate_schema(data)))

    def test_unknown_exclusion_type_rejected(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["exclusions"][0]["type"] = "whatever"
        self.assertTrue(any("type" in e for e in C.validate_schema(data)))

    def test_non_contained_path_rejected(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["paths"] = ["../escape/**"]
        self.assertTrue(any("invalid path pattern" in e for e in C.validate_schema(data)))

    def test_duplicate_unit_id_rejected(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][1]["id"] = "alpha"
        self.assertTrue(any("duplicate" in e for e in C.validate_schema(data)))

    def test_catch_all_exclusion_rejected(self):
        for pattern in ("**", "*", "**/*"):
            data = json.loads(json.dumps(DEFAULT_CONTRACT))
            data["exclusions"][0]["paths"] = [pattern]
            errs = C.validate_schema(data)
            self.assertTrue(
                any("catch-all" in e or "unbounded" in e for e in errs),
                f"catch-all exclusion {pattern!r} must be rejected: {errs}",
            )

    def test_extension_bounded_and_prefixed_patterns_allowed(self):
        # docs/** (literal prefix) and **/*.md (literal extension) stay valid.
        for pattern in ("docs/**", "**/*.md"):
            self.assertTrue(C.is_bounded_pattern(pattern), pattern)
        for pattern in ("**", "*", "**/*"):
            self.assertFalse(C.is_bounded_pattern(pattern), pattern)

    def test_missing_responsibility_key_defaults_empty_not_error(self):
        # A responsibility may be omitted/empty; ownership-completeness (not the
        # schema) flags the gap, so an exception can cover it.
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["responsibilities"].pop("security")
        self.assertEqual(C.validate_schema(data), [])


# --------------------------------------------------------------------------- #
# contract.py: classification precedence + routing outputs
# --------------------------------------------------------------------------- #
class ClassificationTests(unittest.TestCase):
    def test_most_specific_unit_wins_over_broader_exclusion(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"].append(
            {
                "id": "guardrail_docs",
                "paths": ["docs/adr/**"],
                "responsibilities": {"lint": ["x"], "security": ["y"], "test": ["z"]},
            }
        )
        contract = C.build_contract(data)
        # docs/adr/** (unit, 2 literal segments) beats docs/** (exclusion, 1).
        self.assertEqual(C.classify_path(contract, "docs/adr/0001.md"), ("unit", "guardrail_docs"))
        self.assertEqual(C.classify_path(contract, "docs/other.md"), ("exclusion", "docs"))

    def test_equal_specificity_unit_exclusion_is_contradiction(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["exclusions"][0]["paths"] = ["src/alpha/**"]  # same as alpha unit
        contract = C.build_contract(data)
        with self.assertRaises(C.ContractError):
            C.classify_path(contract, "src/alpha/mod.py")

    def test_matching_units_returns_all_overlapping(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][1]["paths"] = ["src/alpha/**", "common/**"]
        contract = C.build_contract(data)
        self.assertEqual(
            sorted(C.matching_units(contract, "src/alpha/mod.py")),
            ["alpha", "common"],
        )

    def test_compute_outputs_activates_matching_unit(self):
        contract = C.build_contract(DEFAULT_CONTRACT)
        out = C.compute_outputs(contract, ["src/alpha/mod.py"])
        self.assertEqual(out["alpha"], "true")
        self.assertEqual(out["common"], "false")
        self.assertEqual(out["run_all"], "false")
        self.assertEqual(out["run_sonar"], "true")  # alpha has sonar: true

    def test_compute_outputs_force_full_on_workflow_change(self):
        contract = C.build_contract(DEFAULT_CONTRACT)
        out = C.compute_outputs(contract, [".github/workflows/ci.yml"])
        self.assertEqual(out["ci_workflows"], "true")
        self.assertEqual(out["run_all"], "true")

    def test_compute_outputs_fail_closed_on_unknown_path(self):
        contract = C.build_contract(DEFAULT_CONTRACT)
        with self.assertRaises(C.UnknownPathError):
            C.compute_outputs(contract, ["src/alpha/mod.py", "wholly/unknown.py"])

    def test_compute_outputs_fail_closed_on_contradiction(self):
        # An equal-specificity unit/exclusion match is ambiguous ownership; the
        # classifier must fail closed, not silently accept it.
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["exclusions"][0]["paths"] = ["src/alpha/**"]  # same as the alpha unit
        contract = C.build_contract(data)
        with self.assertRaises(C.ContractError):
            C.compute_outputs(contract, ["src/alpha/mod.py"])

    def test_mcp_fanout_all_on_shared_change(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"] = [
            {
                "id": "mcp_a",
                "paths": ["mcp/a/**"],
                "mcp": {"package": "a"},
                "responsibilities": {
                    "lint": [{"job": "mcp-lint", "matrix": {"package": "a"}}],
                    "security": [],
                    "test": [{"job": "mcp-tests", "matrix": {"package": "a"}}],
                },
            },
            {
                "id": "mcp_shared",
                "paths": ["mcp/shared/**"],
                "mcp": {"package": "shared", "fanout_all_on_change": True},
                "responsibilities": {
                    "lint": [{"job": "mcp-lint", "matrix": {"package": "shared"}}],
                    "security": [],
                    "test": [],
                },
            },
        ]
        data["exclusions"] = [{"type": "docs", "reason": "d", "paths": ["docs/**"]}]
        contract = C.build_contract(data)
        out = C.compute_outputs(contract, ["mcp/shared/x.js"])
        self.assertEqual(json.loads(out["mcp_lint_packages"]), ["a", "shared"])
        # shared change fans lint out to all packages even though only shared changed.


# --------------------------------------------------------------------------- #
# contract.py: estate reconciliation
# --------------------------------------------------------------------------- #
class EstateReconciliationTests(unittest.TestCase):
    def test_complete_estate_has_no_violations(self):
        contract = C.build_contract(DEFAULT_CONTRACT)
        tracked = DEFAULT_ESTATE + [
            ".github/workflows/_quality.yml",
            ".github/quality-path-filters.yaml",
            "scripts/quality_ownership/contract.py",
            "scripts/check_layer_imports/layer_imports.yaml",
        ]
        self.assertEqual(C.estate_violations(contract, tracked), [])

    def test_unknown_path_fails_closed(self):
        contract = C.build_contract(DEFAULT_CONTRACT)
        errs = C.estate_violations(contract, ["src/alpha/mod.py", "orphan/thing.bin"])
        self.assertTrue(any("orphan/thing.bin" in e for e in errs))

    def test_rename_flags_stale_glob_and_unknown_new_path(self):
        # Rename the owned package: the contract still points at the old glob,
        # the file now lives at a new unowned path. Both must fail.
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["paths"] = ["src/renamed/**"]
        contract = C.build_contract(data)
        tracked = ["src/alpha/mod.py", "common/lib.py", "docs/readme.md"]
        errs = C.estate_violations(contract, tracked)
        self.assertTrue(any("src/alpha/mod.py" in e for e in errs))  # unowned new
        self.assertTrue(any("src/renamed/**" in e and "stale" in e for e in errs))

    def test_contradiction_is_reported(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["exclusions"][0]["paths"] = ["src/alpha/**"]  # collides with alpha unit
        contract = C.build_contract(data)
        errs = C.estate_violations(contract, ["src/alpha/mod.py"])
        self.assertTrue(any("both a quality unit and an exclusion" in e for e in errs))


# --------------------------------------------------------------------------- #
# classify_paths.py: fail-closed CLI boundary
# --------------------------------------------------------------------------- #
class ClassifyPathsCliTests(unittest.TestCase):
    def _run_main(self, env, changed):
        original = dict(os.environ)
        saved_changed = classify_paths._changed_files
        try:
            os.environ.update(env)
            classify_paths._changed_files = lambda repo_root: changed
            return classify_paths.main()
        finally:
            classify_paths._changed_files = saved_changed
            os.environ.clear()
            os.environ.update(original)

    def test_unknown_changed_path_exits_nonzero_without_emitting_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root)
            out_file = root / "gh_output"
            out_file.write_text("", encoding="utf-8")
            rc = self._run_main(
                {"GITHUB_WORKSPACE": str(root), "GITHUB_OUTPUT": str(out_file)},
                ["totally/unowned.py"],
            )
            self.assertEqual(rc, 1)
            self.assertEqual(out_file.read_text(encoding="utf-8"), "")

    def test_known_changed_path_emits_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root)
            out_file = root / "gh_output"
            out_file.write_text("", encoding="utf-8")
            rc = self._run_main(
                {"GITHUB_WORKSPACE": str(root), "GITHUB_OUTPUT": str(out_file)},
                ["src/alpha/mod.py"],
            )
            self.assertEqual(rc, 0)
            written = out_file.read_text(encoding="utf-8")
            self.assertIn("alpha=true", written)
            self.assertIn("run_all=false", written)

    def test_contradiction_exits_nonzero_without_output(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["exclusions"][0]["paths"] = ["src/alpha/**"]  # collides with alpha unit
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, contract=data)
            out_file = root / "gh_output"
            out_file.write_text("", encoding="utf-8")
            rc = self._run_main(
                {"GITHUB_WORKSPACE": str(root), "GITHUB_OUTPUT": str(out_file)},
                ["src/alpha/mod.py"],
            )
            self.assertEqual(rc, 1)
            self.assertEqual(out_file.read_text(encoding="utf-8"), "")


# --------------------------------------------------------------------------- #
# classify_paths.py: _changed_files excludes deletions (#1776)
# --------------------------------------------------------------------------- #
class ChangedFilesDiffTests(unittest.TestCase):
    """`_changed_files` must exclude deletions. A path removed by the diff no
    longer exists at HEAD, owns no quality job, and must not be classified —
    otherwise the classifier and the estate staleness gate contradict on any PR
    that deletes a narrowly-classified file (#1776)."""

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_changed_files_excludes_deletions(self):
        original = dict(os.environ)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.email", "t@example.com")
            self._git(root, "config", "user.name", "t")
            (root / "keep.py").write_text("x = 1\n", encoding="utf-8")
            (root / "gone.toml").write_text("k = 1\n", encoding="utf-8")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-q", "-m", "base")
            base = self._git(root, "rev-parse", "HEAD")
            (root / "keep.py").write_text("x = 2\n", encoding="utf-8")
            (root / "gone.toml").unlink()
            self._git(root, "add", "-A")
            self._git(root, "commit", "-q", "-m", "delete gone.toml, edit keep.py")
            head = self._git(root, "rev-parse", "HEAD")
            try:
                os.environ.pop("RUN_FULL_MATRIX", None)
                os.environ["DIFF_BASE_SHA"] = base
                os.environ["DIFF_HEAD_SHA"] = head
                changed = classify_paths._changed_files(root)
            finally:
                os.environ.clear()
                os.environ.update(original)
            self.assertIn("keep.py", changed)
            self.assertNotIn("gone.toml", changed)


# --------------------------------------------------------------------------- #
# adr_guard check: end-to-end conformance
# --------------------------------------------------------------------------- #
class QualityOwnershipCheckTests(unittest.TestCase):
    def test_valid_repo_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root)
            self.assertEqual(run_check(root), [], msg=messages(run_check(root)))

    def test_unclassified_estate_path_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, estate=DEFAULT_ESTATE + ["weird/orphan.txt"])
            self.assertTrue(any("weird/orphan.txt" in v.message for v in run_check(root)))

    def test_ownership_gap_flagged(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["responsibilities"]["security"] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, contract=data)
            hits = [v for v in run_check(root) if v.path.endswith("#alpha:security")]
            self.assertTrue(hits, msg=messages(run_check(root)))

    def test_advisory_job_cannot_own_responsibility(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        # security-k8s is an evidence-only (advisory) job by name.
        data["quality_units"][0]["responsibilities"]["security"] = ["security-k8s"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, contract=data)
            self.assertTrue(
                any("advisory" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_missing_job_flagged(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["responsibilities"]["lint"] = ["does-not-exist"]
        # Workflow generated from the DEFAULT contract does not contain the job.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, contract=data, workflow=synthetic_workflow(DEFAULT_CONTRACT))
            self.assertTrue(
                any("missing" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_continue_on_error_job_cannot_own_responsibility(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["responsibilities"]["test"] = ["flaky-tests"]
        wf = yaml.safe_load(synthetic_workflow(data))
        wf["jobs"]["flaky-tests"]["continue-on-error"] = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, contract=data, workflow=yaml.safe_dump(wf))
            self.assertTrue(
                any("continue-on-error" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_new_first_party_package_without_ownership_flagged(self):
        cls = {
            "classification": {
                "domain": ["alpha", "newpkg"],
                "support_contracts": ["common"],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, classification=cls)
            self.assertTrue(
                any("newpkg" in v.message and "no quality-ownership" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_unit_referencing_unclassified_package_flagged(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["packages"] = ["ghost"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, contract=data)
            self.assertTrue(
                any("ghost" in v.message and "not in the #1523" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_routing_unreachable_flagged(self):
        # alpha declares common-lint, whose `if` keys on the `common` category,
        # so an alpha change never runs it.
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["responsibilities"]["lint"] = ["common-lint"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, contract=data)
            self.assertTrue(
                any("routing unreachable" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_docs_change_must_not_route_production_job(self):
        # A unit whose glob over-captures docs/ would let a docs-only change
        # select a production job (routing activates every matching unit).
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"][0]["paths"] = ["src/alpha/**", "docs/*"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, contract=data)
            self.assertTrue(
                any("docs-only change" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_matrix_member_not_selected_flagged(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"] = [
            {
                "id": "mcp_a",
                "paths": ["mcp/a/**"],
                "mcp": {"package": "a"},
                "responsibilities": {
                    # Declares the WRONG matrix member (b), which is never
                    # selected when only mcp_a changes.
                    "lint": [{"job": "mcp-lint", "matrix": {"package": "b"}}],
                    "security": [],
                    "test": [{"job": "mcp-tests", "matrix": {"package": "a"}}],
                },
            },
        ]
        data["exclusions"] = [
            {"type": "docs", "reason": "d", "paths": ["docs/**"]},
            {
                "type": "config",
                "reason": "scaffolding",
                "paths": [
                    "scripts/quality_ownership/**",
                    "scripts/check_layer_imports/**",
                ],
            },
        ]
        cls = {"classification": {"support_contracts": []}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(
                root,
                contract=data,
                classification=cls,
                estate=["mcp/a/x.js", "docs/readme.md"],
            )
            self.assertTrue(
                any("matrix member" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_miswired_output_flagged(self):
        # The paths job maps a category output to the wrong detector key; routing
        # would silently break, so the wiring check must catch it.
        wf = yaml.safe_load(synthetic_workflow(DEFAULT_CONTRACT))
        wf["jobs"]["paths"]["outputs"]["alpha"] = "${{ steps.detect.outputs.common }}"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(root, workflow=yaml.safe_dump(wf))
            self.assertTrue(
                any("not wired to steps.detect.outputs.alpha" in v.message for v in run_check(root)),
                msg=messages(run_check(root)),
            )

    def test_matrix_wired_to_wrong_output_flagged(self):
        data = json.loads(json.dumps(DEFAULT_CONTRACT))
        data["quality_units"] = [
            {
                "id": "mcp_a",
                "paths": ["mcp/a/**"],
                "mcp": {"package": "a"},
                "responsibilities": {
                    "lint": [{"job": "mcp-lint", "matrix": {"package": "a"}}],
                    "security": [],
                    "test": [{"job": "mcp-tests", "matrix": {"package": "a"}}],
                },
            },
        ]
        data["exclusions"] = [
            {"type": "docs", "reason": "d", "paths": ["docs/**"]},
            {
                "type": "config",
                "reason": "scaffolding",
                "paths": ["scripts/quality_ownership/**", "scripts/check_layer_imports/**"],
            },
        ]
        cls = {"classification": {"support_contracts": []}}
        wf = yaml.safe_load(synthetic_workflow(data))
        # Drive the mcp-lint matrix from the WRONG output.
        wf["jobs"]["mcp-lint"]["strategy"]["matrix"]["package"] = (
            "${{ fromJSON(needs.paths.outputs.mcp_test_packages) }}"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repo(
                root,
                contract=data,
                classification=cls,
                workflow=yaml.safe_dump(wf),
                estate=["mcp/a/x.js", "docs/readme.md"],
            )
            self.assertTrue(
                any(
                    "must consume fromJSON(needs.paths.outputs.mcp_lint_packages)" in v.message for v in run_check(root)
                ),
                msg=messages(run_check(root)),
            )


# --------------------------------------------------------------------------- #
# Real repository: the shipped contract is conformant once exceptions apply
# --------------------------------------------------------------------------- #
class RealRepositoryTests(unittest.TestCase):
    def test_real_contract_estate_is_complete(self):
        contract = C.load_contract(_REPO_ROOT / ".github" / "quality-path-filters.yaml")
        tracked = ADR_GUARD._git_tracked_all(_REPO_ROOT)
        self.assertIsNotNone(tracked)
        self.assertEqual(C.estate_violations(contract, tracked), [])

    def test_real_check_passes_after_exceptions(self):
        violations = ADR_GUARD.check_quality_path_ownership(_REPO_ROOT, None)
        exceptions = ADR_GUARD.load_adr_exceptions(_REPO_ROOT)
        remaining = ADR_GUARD.filter_excepted_violations(violations, exceptions)
        self.assertEqual(remaining, [], msg=messages(remaining))

    def test_emitted_outputs_match_declared_paths_job_outputs(self):
        # The classifier's emitted keys must stay in sync with the _quality.yml
        # `paths` job's classifier-sourced outputs, so a new unit cannot silently
        # emit an output no job can consume (or vice versa). Outputs sourced from
        # the independent self-check step (steps.selfcheck) are excluded.
        contract = C.load_contract(_REPO_ROOT / ".github" / "quality-path-filters.yaml")
        emitted = set(C.compute_outputs(contract, None, run_full_matrix=True).keys())
        wf = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "_quality.yml").read_text(encoding="utf-8"))
        declared = {
            key for key, value in wf["jobs"]["paths"]["outputs"].items() if "steps.detect.outputs" in str(value)
        }
        self.assertEqual(emitted, declared)

    def test_guard_verification_reachable_only_via_independent_selfcheck(self):
        # Self-bypass prevention (#1530, ADR-004-R24), proven BEHAVIOURALLY via
        # the routing engine (not substring-matching the if-expression, which the
        # preflight forbids): with every classifier-controlled output false and
        # only the independent guard_selfcheck true, the guard's own verification
        # jobs must still run; with guard_selfcheck also false they must not.
        wf = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "_quality.yml").read_text(encoding="utf-8"))
        jobs = wf["jobs"]
        self.assertIn("steps.selfcheck.outputs", str(jobs["paths"]["outputs"]["guard_selfcheck"]))
        sentinel_on = {"run_all": "false", "adr_guard": "false", "guard_selfcheck": "true"}
        sentinel_off = {"run_all": "false", "adr_guard": "false", "guard_selfcheck": "false"}
        for job_id in ("adr-conformance", "adr-guard-tests"):
            self.assertTrue(
                ADR_GUARD._quality_job_reachable(jobs, job_id, sentinel_on),
                f"{job_id} must run when only the independent sentinel is true",
            )
            self.assertFalse(
                ADR_GUARD._quality_job_reachable(jobs, job_id, sentinel_off),
                f"{job_id} must not run when nothing (incl. sentinel) triggers it",
            )

    def test_run_all_output_folds_independent_selfcheck(self):
        # Production jobs read needs.paths.outputs.run_all; that output must fold
        # in the independent sentinel so a tampered classifier emitting
        # run_all=false cannot suppress the production lint/SAST/test matrix.
        # Evaluated with the real expression engine, not a substring check.
        wf = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "_quality.yml").read_text(encoding="utf-8"))
        expr = ADR_GUARD._quality_strip_if(wf["jobs"]["paths"]["outputs"]["run_all"])

        def evaluate(classifier_run_all: str, sentinel: str) -> bool:
            def resolve(path: str):
                if path == "steps.detect.outputs.run_all":
                    return classifier_run_all
                if path == "steps.selfcheck.outputs.guard_selfcheck":
                    return sentinel
                raise ADR_GUARD._DwExprError(path)

            return ADR_GUARD._dw_truthy(ADR_GUARD._DwParser(ADR_GUARD._dw_tokenize(expr), resolve).evaluate())

        self.assertTrue(evaluate("false", "true"), "sentinel must force the full matrix")
        self.assertTrue(evaluate("true", "false"), "a normal full run still forces it")
        self.assertFalse(evaluate("false", "false"), "neither trigger means no full matrix")


if __name__ == "__main__":
    unittest.main()
