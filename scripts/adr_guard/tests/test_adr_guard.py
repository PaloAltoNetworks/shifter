"""Tests for the ADR guard."""

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


class AdrGuardTests(unittest.TestCase):
    def test_load_allowed_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "layer_imports.yaml"
            config.write_text(
                "allowed:\n"
                "  engine:\n"
                "    - shared\n"
                "    - cms.services\n",
                encoding="utf-8",
            )

            loaded = ADR_GUARD.load_allowed_imports(config)

            self.assertEqual(loaded["engine"], ["shared", "cms.services"])

    def test_guardrail_docs_requires_docs_update(self) -> None:
        violations = ADR_GUARD.check_guardrail_docs(
            ADR_GUARD.REPO_ROOT,
            [".github/workflows/_quality.yml", "scripts/adr_guard/adr_guard.py"],
        )

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "ADR-002-R1")

    def test_adr_registry_rejects_unknown_exception_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "docs" / "adr").mkdir(parents=True)
            (repo_root / "docs" / "adr" / "index.yaml").write_text(
                '[{"id":"ADR-001","title":"t","status":"accepted","scope":"repo","decision":"d",'
                '"rules":[{"id":"ADR-001-R1","description":"x","checks":["layer-imports"]}],'
                '"exceptions":[],"enforcement":["ci"],"evidence":["x"]}]',
                encoding="utf-8",
            )
            (repo_root / "docs" / "adr" / "exceptions.yaml").write_text(
                '[{"rule_id":"ADR-404-R9","owner":"me","reason":"tmp","expires_on":"2026-12-31"}]',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_adr_registry(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("unknown rule id", violations[0].message)

    def test_validate_adr_exceptions_rejects_expired_entries(self) -> None:
        errors = ADR_GUARD.validate_adr_exceptions(
            [
                {
                    "rule_id": "ADR-001-R1",
                    "owner": "platform",
                    "reason": "temporary",
                    "expires_on": "2020-01-01",
                }
            ]
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("expired", errors[0])

    def test_filter_excepted_violations(self) -> None:
        violations = [
            ADR_GUARD.Violation(
                "layer-imports",
                "ADR-001-R1",
                "shifter/shifter_platform/cms/example.py",
                "example",
            ),
            ADR_GUARD.Violation(
                "guardrail-docs",
                "ADR-002-R1",
                ".github/workflows/_quality.yml",
                "example",
            ),
        ]
        exceptions = [
            {
                "rule_id": "ADR-001-R1",
                "owner": "platform",
                "reason": "temporary",
                "expires_on": "2099-12-31",
                "paths": ["shifter/shifter_platform/cms/*"],
                "checks": ["layer-imports"],
            }
        ]

        filtered = ADR_GUARD.filter_excepted_violations(violations, exceptions)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].rule_id, "ADR-002-R1")


class CloudFactorySeamTests(unittest.TestCase):
    def _make_cloud_tree(self, tmp: str, aws_files: list[str], gcp_files: list[str]) -> Path:
        """Create a minimal cloud adapter tree under a fake repo root."""
        repo_root = Path(tmp)
        for cloud_root in ADR_GUARD.CLOUD_ROOTS:
            aws_dir = repo_root / cloud_root / "aws"
            gcp_dir = repo_root / cloud_root / "gcp"
            aws_dir.mkdir(parents=True, exist_ok=True)
            gcp_dir.mkdir(parents=True, exist_ok=True)
            for name in aws_files:
                (aws_dir / name).write_text("", encoding="utf-8")
            for name in gcp_files:
                (gcp_dir / name).write_text("", encoding="utf-8")
        return repo_root

    def test_parity_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "base.py", "storage.py", "secrets.py"],
                ["__init__.py", "base.py", "storage.py", "secrets.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(repo_root, None)
            self.assertEqual(violations, [])

    def test_missing_gcp_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "storage.py", "queue.py"],
                ["__init__.py", "storage.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(repo_root, None)
            self.assertTrue(len(violations) >= 1)
            self.assertTrue(any("queue.py" in v.message and "no GCP counterpart" in v.message for v in violations))

    def test_missing_aws_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "storage.py"],
                ["__init__.py", "storage.py", "task_runner.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(repo_root, None)
            self.assertTrue(len(violations) >= 1)
            self.assertTrue(any("task_runner.py" in v.message and "no AWS counterpart" in v.message for v in violations))

    def test_skips_init_and_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "base.py"],
                ["__init__.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(repo_root, None)
            self.assertEqual(violations, [])

    def test_skipped_when_no_cloud_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "storage.py", "queue.py"],
                ["__init__.py", "storage.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(
                repo_root,
                ["shifter/shifter_platform/cms/views.py"],
            )
            self.assertEqual(violations, [])

    def test_runs_when_cloud_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "storage.py", "queue.py"],
                ["__init__.py", "storage.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(
                repo_root,
                ["shifter/shifter_platform/shared/cloud/gcp/storage.py"],
            )
            self.assertTrue(len(violations) >= 1)

    def test_real_repo_passes(self) -> None:
        """The actual repo cloud adapters should be in parity."""
        violations = ADR_GUARD.check_cloud_factory_seam(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(violations, [])


class McpNoShellExecTests(unittest.TestCase):
    """Tests for the mcp-no-shell-exec ADR-010-R1 check."""

    def _write(self, repo_root: Path, rel: str, body: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _run(self, repo_root: Path) -> list:
        return ADR_GUARD.check_mcp_no_shell_exec(repo_root, None)

    def test_clean_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_named_esm_import_with_node_prefix_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { execSync } from "node:child_process";\n'
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-010-R1")

    def test_named_esm_import_without_node_prefix_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                "import { execSync } from 'child_process';\n"
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_namespace_esm_import_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import * as cp from "node:child_process";\n'
                "cp.execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_default_esm_import_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import cp from "node:child_process";\n'
                "cp.execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_destructured_cjs_require_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.cjs",
                'const { execSync } = require("child_process");\n'
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_bare_cjs_require_with_property_access_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.cjs",
                'const cp = require("node:child_process");\n'
                "cp.execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_mjs_extension_is_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.mjs",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_execSync_in_a_comment_does_not_trip_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                "// We used to call execSync('aws s3 ls') here.\n"
                "/* execSync('legacy') */\n"
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_execSync_without_child_process_import_is_not_flagged(self) -> None:
        # An unrelated function happens to be named execSync but is
        # not Node's child_process.execSync; the check requires both
        # the import and the call site.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                "function execSync(query) { return query; }\n"
                "execSync('select 1');\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_node_modules_is_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/node_modules/something/dist.js",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_aliased_named_import_is_flagged(self) -> None:
        """`import { execSync as run } ... run('aws ...')` is a bypass."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { execSync as run } from "node:child_process";\n'
                "run('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-010-R1")

    def test_double_slashes_inside_a_string_do_not_eat_the_call_site(self) -> None:
        """`https://...` URL must not flatten the call line into a comment."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { execSync } from "node:child_process";\n'
                'const endpoint = "https://example.com/foo";\n'
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_block_comment_containing_call_text_does_not_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                "/*\n * old: execSync('aws s3 ls')\n */\n"
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_template_string_containing_call_text_does_not_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                "const note = `we used to call execSync('aws ...') here`;\n"
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_bare_exec_is_flagged(self) -> None:
        """`exec(shellString)` is shell-string execution, same as execSync."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { exec } from "node:child_process";\n'
                "exec('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_namespace_exec_call_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import * as cp from "node:child_process";\n'
                "cp.exec('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_spawn_with_shell_true_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawn } from "node:child_process";\n'
                "spawn('aws s3 ls', { shell: true });\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)
            self.assertIn("shell: true", violations[0].message)

    def test_spawn_without_shell_option_is_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawn } from "node:child_process";\n'
                "spawn('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_spawn_with_shell_false_is_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawn } from "node:child_process";\n'
                "spawn('aws', ['s3', 'ls'], { shell: false });\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_string_containing_alias_pattern_does_not_force_a_false_positive(self) -> None:
        """A comment or string with the literal `execSync as run` text
        must not turn an unrelated `run(` call into a flagged call site."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                'const note = "we used to import { execSync as run } here";\n'
                "function run(x) { return x; }\n"
                "run('legacy');\n"
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_synthetic_repo_with_violator_and_exception(self) -> None:
        """A violator in an excepted path is filtered; a violator outside is not.

        Replaces the older live-repo regression test, which would have
        broken when the deferred mcp/ngfw migration removed those
        violations.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "docs/adr/index.yaml",
                '[{"id":"ADR-010","title":"t","status":"accepted",'
                '"scope":"repository","decision":"d",'
                '"rules":[{"id":"ADR-010-R1","description":"x",'
                '"checks":["mcp-no-shell-exec"]}],'
                '"exceptions":[],"enforcement":["agent-policy"],'
                '"evidence":["scripts/adr_guard/adr_guard.py"]}]',
            )
            self._write(
                repo_root,
                "docs/adr/exceptions.yaml",
                '[{"rule_id":"ADR-010-R1","owner":"team",'
                '"reason":"deferred migration","expires_on":"2099-01-01",'
                '"checks":["mcp-no-shell-exec"],'
                '"paths":["mcp/legacy/*"]}]',
            )
            self._write(
                repo_root,
                "mcp/legacy/index.js",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            )
            self._write(
                repo_root,
                "mcp/fresh/index.js",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            )

            raw = ADR_GUARD.check_mcp_no_shell_exec(repo_root, None)
            paths = sorted(v.path for v in raw)
            self.assertEqual(paths, ["mcp/fresh/index.js", "mcp/legacy/index.js"])

            exceptions = ADR_GUARD.load_adr_exceptions(repo_root)
            filtered = ADR_GUARD.filter_excepted_violations(raw, exceptions)
            self.assertEqual(
                [v.path for v in filtered], ["mcp/fresh/index.js"]
            )


class K8sDeploymentSecurityContextTests(unittest.TestCase):
    """Tests for the k8s-deployment-security-context ADR-006-R2 check."""

    HARDENED_POD = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: web\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      securityContext:\n"
        "        seccompProfile:\n"
        "          type: RuntimeDefault\n"
        "      containers:\n"
        "        - name: web\n"
        "          image: example/web:1\n"
        "          securityContext:\n"
        "            allowPrivilegeEscalation: false\n"
        "            capabilities:\n"
        "              drop: [\"ALL\"]\n"
        "            readOnlyRootFilesystem: true\n"
        "            runAsNonRoot: true\n"
        "            runAsUser: 1000\n"
        "            runAsGroup: 1000\n"
    )

    def _write(self, repo_root: Path, rel: str, body: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _run(self, repo_root: Path, files: list[str] | None = None) -> list:
        if files is None:
            base = repo_root / ADR_GUARD.K8S_BASE_DEPLOYMENT_DIR
            files = sorted(
                ADR_GUARD._repo_relative(p, repo_root)
                for p in list(base.rglob("*.yaml")) + list(base.rglob("*.yml"))
            )
        return ADR_GUARD.check_k8s_deployment_security_context(repo_root, files)

    def test_compliant_deployment_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", self.HARDENED_POD)
            self.assertEqual(self._run(repo_root), [])

    def test_missing_pod_seccomp_profile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "      securityContext:\n        seccompProfile:\n          type: RuntimeDefault\n",
                "",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("seccompProfile" in v.message for v in violations))
            self.assertTrue(all(v.rule_id == "ADR-006-R2" for v in violations))

    def test_wrong_seccomp_profile_type_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("RuntimeDefault", "Unconfined")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("Unconfined" in v.message for v in violations))

    def test_allow_privilege_escalation_true_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "allowPrivilegeEscalation: false", "allowPrivilegeEscalation: true"
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("allowPrivilegeEscalation" in v.message for v in violations))

    def test_missing_read_only_root_fs_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("            readOnlyRootFilesystem: true\n", "")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("readOnlyRootFilesystem" in v.message for v in violations))

    def test_missing_run_as_non_root_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("            runAsNonRoot: true\n", "")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsNonRoot" in v.message for v in violations))

    def test_missing_capabilities_drop_all_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            capabilities:\n              drop: [\"ALL\"]\n", ""
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("drop ALL" in v.message for v in violations))

    def test_capabilities_drop_partial_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace('drop: ["ALL"]', 'drop: ["NET_RAW"]')
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("drop ALL" in v.message for v in violations))

    def test_run_as_root_uid_zero_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("runAsUser: 1000", "runAsUser: 0")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsUser" in v.message for v in violations))

    def test_missing_run_as_user_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("            runAsUser: 1000\n", "")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsUser" in v.message for v in violations))

    def test_missing_run_as_group_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("            runAsGroup: 1000\n", "")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsGroup" in v.message for v in violations))

    def test_missing_container_security_context_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = (
                "apiVersion: apps/v1\n"
                "kind: Deployment\n"
                "metadata:\n"
                "  name: bare\n"
                "spec:\n"
                "  template:\n"
                "    spec:\n"
                "      securityContext:\n"
                "        seccompProfile:\n"
                "          type: RuntimeDefault\n"
                "      containers:\n"
                "        - name: bare\n"
                "          image: example/bare:1\n"
            )
            self._write(repo_root, "platform/k8s/gcp/base/bare-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(len(violations) >= 4)
            self.assertTrue(all(v.rule_id == "ADR-006-R2" for v in violations))

    def test_skips_when_no_relevant_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("RuntimeDefault", "Unconfined")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(
                self._run(repo_root, ["shifter/shifter_platform/cms/views.py"]), []
            )

    def test_runs_when_relevant_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("RuntimeDefault", "Unconfined")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(
                repo_root, ["platform/k8s/gcp/base/web-deployment.yaml"]
            )
            self.assertTrue(any("Unconfined" in v.message for v in violations))

    def test_skips_non_deployment_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/foo-deployment.yaml",
                "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: foo\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_real_repo_base_manifests_pass(self) -> None:
        """The actual repo's base deployments must comply with ADR-006-R2.

        Restricted to base files so the test doesn't depend on `helm`
        being on PATH; the chart-rendered validation has its own test
        guarded by skipUnless.
        """
        base = ADR_GUARD.REPO_ROOT / ADR_GUARD.K8S_BASE_DEPLOYMENT_DIR
        files = sorted(
            ADR_GUARD._repo_relative(p, ADR_GUARD.REPO_ROOT)
            for p in list(base.rglob("*.yaml")) + list(base.rglob("*.yml"))
        )
        violations = ADR_GUARD.check_k8s_deployment_security_context(
            ADR_GUARD.REPO_ROOT, files
        )
        self.assertEqual(violations, [], msg=str(violations))

    def test_privileged_container_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "          securityContext:\n",
                "          securityContext:\n            privileged: true\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("privileged" in v.message for v in violations))

    def test_capabilities_add_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            capabilities:\n              drop: [\"ALL\"]\n",
                "            capabilities:\n              drop: [\"ALL\"]\n              add: [\"SYS_ADMIN\"]\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("capabilities.add" in v.message for v in violations)
            )

    def test_container_level_seccomp_unconfined_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            runAsGroup: 1000\n",
                "            runAsGroup: 1000\n"
                "            seccompProfile:\n"
                "              type: Unconfined\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("container-level seccompProfile" in v.message for v in violations)
            )

    def test_container_level_seccomp_runtime_default_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            runAsGroup: 1000\n",
                "            runAsGroup: 1000\n"
                "            seccompProfile:\n"
                "              type: RuntimeDefault\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(self._run(repo_root), [])

    def test_init_container_unsafe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = (
                self.HARDENED_POD
                + "      initContainers:\n"
                "        - name: setup\n"
                "          image: example/setup:1\n"
                "          securityContext:\n"
                "            allowPrivilegeEscalation: true\n"
                "            capabilities:\n"
                "              drop: []\n"
                "            readOnlyRootFilesystem: false\n"
                "            runAsNonRoot: false\n"
                "            runAsUser: 0\n"
                "            runAsGroup: 0\n"
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("initContainer" in v.message and "'setup'" in v.message for v in violations)
            )

    def test_init_container_compliant_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = (
                self.HARDENED_POD
                + "      initContainers:\n"
                "        - name: setup\n"
                "          image: example/setup:1\n"
                "          securityContext:\n"
                "            allowPrivilegeEscalation: false\n"
                "            capabilities:\n"
                "              drop: [\"ALL\"]\n"
                "            readOnlyRootFilesystem: true\n"
                "            runAsNonRoot: true\n"
                "            runAsUser: 1000\n"
                "            runAsGroup: 1000\n"
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(self._run(repo_root), [])

    def test_boolean_run_as_user_is_rejected(self) -> None:
        """`runAsUser: true` must NOT pass even though bool is a subclass of int."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("runAsUser: 1000", "runAsUser: true")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsUser" in v.message for v in violations))

    def test_boolean_run_as_group_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("runAsGroup: 1000", "runAsGroup: false")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsGroup" in v.message for v in violations))


class K8sDeploymentSecurityContextRobustnessTests(unittest.TestCase):
    """Cycle-3 robustness coverage: PyYAML-backed parsing, kind-based filtering,
    pod-level inheritance, multi-document files, and unsupported shapes."""

    HARDENED_POD = K8sDeploymentSecurityContextTests.HARDENED_POD

    def _write(self, repo_root: Path, rel: str, body: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _run(self, repo_root: Path, files: list[str] | None = None) -> list:
        if files is None:
            base = repo_root / ADR_GUARD.K8S_BASE_DEPLOYMENT_DIR
            files = sorted(
                ADR_GUARD._repo_relative(p, repo_root)
                for p in list(base.rglob("*.yaml")) + list(base.rglob("*.yml"))
            )
        return ADR_GUARD.check_k8s_deployment_security_context(repo_root, files)

    def test_leading_document_separator_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/web-deployment.yaml",
                "---\n" + self.HARDENED_POD,
            )
            self.assertEqual(self._run(repo_root), [])

    def test_indentless_sequence_passes(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
            "      containers:\n"
            "      - name: web\n"
            "        image: example/web:1\n"
            "        securityContext:\n"
            "          allowPrivilegeEscalation: false\n"
            "          capabilities:\n"
            "            drop: [\"ALL\"]\n"
            "          readOnlyRootFilesystem: true\n"
            "          runAsNonRoot: true\n"
            "          runAsUser: 1000\n"
            "          runAsGroup: 1000\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(self._run(repo_root), [])

    def test_empty_flow_security_context_fails_cleanly(self) -> None:
        """`securityContext: {}` parses as an empty mapping but exposes no fields,
        so the container-level checks must report violations rather than crash."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "          securityContext:\n"
                "            allowPrivilegeEscalation: false\n"
                "            capabilities:\n"
                "              drop: [\"ALL\"]\n"
                "            readOnlyRootFilesystem: true\n"
                "            runAsNonRoot: true\n"
                "            runAsUser: 1000\n"
                "            runAsGroup: 1000\n",
                "          securityContext: {}\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(len(violations) >= 4)
            self.assertTrue(all(v.rule_id == "ADR-006-R2" for v in violations))

    def test_non_mapping_security_context_reports_violation(self) -> None:
        """A non-mapping `securityContext:` value (e.g., a YAML alias resolved to a
        string) must produce a clear violation, not crash with AttributeError."""
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext: scalar-not-a-mapping\n"
            "      containers:\n"
            "        - name: web\n"
            "          image: example/web:1\n"
            "          securityContext: scalar-not-a-mapping\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("must be a mapping" in v.message for v in violations)
            )

    def test_pod_level_run_as_user_inheritance_passes(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
            "        runAsNonRoot: true\n"
            "        runAsUser: 1000\n"
            "        runAsGroup: 1000\n"
            "      containers:\n"
            "        - name: web\n"
            "          image: example/web:1\n"
            "          securityContext:\n"
            "            allowPrivilegeEscalation: false\n"
            "            capabilities:\n"
            "              drop: [\"ALL\"]\n"
            "            readOnlyRootFilesystem: true\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(self._run(repo_root), [])

    def test_container_override_beats_pod_level_default(self) -> None:
        """If pod sets runAsUser=1000 but a container overrides to 0, that container fails."""
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
            "        runAsNonRoot: true\n"
            "        runAsUser: 1000\n"
            "        runAsGroup: 1000\n"
            "      containers:\n"
            "        - name: web\n"
            "          image: example/web:1\n"
            "          securityContext:\n"
            "            allowPrivilegeEscalation: false\n"
            "            capabilities:\n"
            "              drop: [\"ALL\"]\n"
            "            readOnlyRootFilesystem: true\n"
            "            runAsUser: 0\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsUser" in v.message for v in violations))

    def test_kind_based_filtering_scans_unsuffixed_yaml(self) -> None:
        """A Deployment placed in a file without the '-deployment.yaml' suffix
        must still be scanned. Filename is not authoritative; `kind:` is."""
        body = self.HARDENED_POD.replace("allowPrivilegeEscalation: false", "allowPrivilegeEscalation: true")
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/worker.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("allowPrivilegeEscalation" in v.message for v in violations))

    def test_non_deployment_kind_is_skipped(self) -> None:
        """A non-Deployment YAML in the base dir must be parsed but not flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/configmap.yaml",
                "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: foo\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_empty_capabilities_add_is_rejected(self) -> None:
        """`capabilities.add: []` is forbidden by key presence; the rule says
        'no capabilities.add', not 'no non-empty capabilities.add'."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            capabilities:\n              drop: [\"ALL\"]\n",
                "            capabilities:\n              drop: [\"ALL\"]\n              add: []\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("capabilities.add" in v.message for v in violations)
            )

    def test_non_mapping_spec_fails_cleanly(self) -> None:
        """A `spec:` value that is a non-mapping scalar must produce a violation,
        not crash the entire ADR guard with an AttributeError."""
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec: scalar-not-a-mapping\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("spec must be a mapping" in v.message for v in violations))

    def test_non_mapping_template_fails_cleanly(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template: scalar-not-a-mapping\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("spec.template must be a mapping" in v.message for v in violations)
            )

    def test_yml_extension_is_scanned(self) -> None:
        """A Deployment in a `.yml`-extension file under base/ must be scanned."""
        body = self.HARDENED_POD.replace("allowPrivilegeEscalation: false", "allowPrivilegeEscalation: true")
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/worker.yml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("allowPrivilegeEscalation" in v.message for v in violations))

    def test_missing_chart_directory_is_a_violation(self) -> None:
        """Deleting the entire chart directory must produce a violation,
        not a silent skip — the chart is the authoritative deployment
        contract per ADR-007."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            # No chart/ directory created.
            rendered, violations = ADR_GUARD._render_chart_for_validation(
                repo_root, ADR_GUARD.HELM_VALUES_FILES
            )
            self.assertEqual(rendered, [])
            self.assertTrue(
                any(
                    v.path == ADR_GUARD.HELM_CHART_DIR
                    and "chart directory is missing" in v.message
                    for v in violations
                )
            )

    def test_chart_violation_path_is_repo_relative(self) -> None:
        """Rendered-chart violations must use the values-file repo-relative
        path so existing exception globs in docs/adr/exceptions.yaml can
        match (the path field, not a synthetic 'helm template -f X' label)."""
        import os
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            chart_dir = repo_root / "platform/charts/shifter"
            chart_dir.mkdir(parents=True)
            for vf in ADR_GUARD.HELM_VALUES_FILES:
                (repo_root / vf).write_text("dummy: true\n", encoding="utf-8")

            unsafe_deployment = (
                "apiVersion: apps/v1\n"
                "kind: Deployment\n"
                "metadata:\n"
                "  name: rendered\n"
                "spec:\n"
                "  template:\n"
                "    spec:\n"
                "      containers:\n"
                "        - name: rendered\n"
                "          image: example/x:1\n"
                "          securityContext:\n"
                "            allowPrivilegeEscalation: true\n"
            )
            shim_dir = repo_root / "_shim"
            shim_dir.mkdir()
            shim_path = shim_dir / "helm"
            shim_path.write_text(
                "#!/usr/bin/env bash\n"
                f"cat <<'YAML'\n{unsafe_deployment}YAML\n",
                encoding="utf-8",
            )
            shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = f"{shim_dir}:{old_path}"
                violations = ADR_GUARD.check_k8s_deployment_security_context(
                    repo_root,
                    ["platform/charts/shifter/values-gcp-dev.yaml"],
                )
            finally:
                os.environ["PATH"] = old_path

            chart_violations = [
                v for v in violations if "allowPrivilegeEscalation" in v.message
            ]
            self.assertTrue(chart_violations)
            for v in chart_violations:
                self.assertIn(v.path, ADR_GUARD.HELM_VALUES_FILES)

    def test_helm_not_installed_returns_actionable_violation(self) -> None:
        """When helm is absent, the chart branch returns a clear violation
        (not a silent skip), so CI surfaces the missing prerequisite."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "platform/charts/shifter").mkdir(parents=True)
            # Override PATH so helm cannot be found.
            import os
            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = ""
                rendered, violations = ADR_GUARD._render_chart_for_validation(
                    repo_root, ADR_GUARD.HELM_VALUES_FILES
                )
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(rendered, [])
            self.assertTrue(any("helm CLI is required" in v.message for v in violations))

    def test_chart_render_via_fake_helm(self) -> None:
        """End-to-end exercise of the chart-rendering branch using a fake
        helm shim that emits a multi-document YAML payload. Validates
        that rendered Deployments are checked and violations are surfaced
        with a `helm template -f <values>` source label. Both configured
        values files exist so the missing-file path doesn't fire."""
        import os
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            chart_dir = repo_root / "platform/charts/shifter"
            chart_dir.mkdir(parents=True)
            for vf in ADR_GUARD.HELM_VALUES_FILES:
                (repo_root / vf).write_text("dummy: true\n", encoding="utf-8")

            # Fake helm shim. Emits a Deployment that violates ADR-006-R2.
            unsafe_deployment = (
                "apiVersion: apps/v1\n"
                "kind: Deployment\n"
                "metadata:\n"
                "  name: rendered\n"
                "spec:\n"
                "  template:\n"
                "    spec:\n"
                "      containers:\n"
                "        - name: rendered\n"
                "          image: example/x:1\n"
                "          securityContext:\n"
                "            allowPrivilegeEscalation: true\n"
            )
            shim_dir = repo_root / "_shim"
            shim_dir.mkdir()
            shim_path = shim_dir / "helm"
            shim_path.write_text(
                "#!/usr/bin/env bash\n"
                f"cat <<'YAML'\n{unsafe_deployment}YAML\n",
                encoding="utf-8",
            )
            shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = f"{shim_dir}:{old_path}"
                violations = ADR_GUARD.check_k8s_deployment_security_context(
                    repo_root,
                    ["platform/charts/shifter/values-gcp-dev.yaml"],
                )
            finally:
                os.environ["PATH"] = old_path

            self.assertTrue(
                any("allowPrivilegeEscalation" in v.message for v in violations)
            )
            # Violation path is the repo-relative values file (so existing
            # exception globs in docs/adr/exceptions.yaml can match), not a
            # synthetic 'helm template -f X' label.
            self.assertTrue(
                any(v.path in ADR_GUARD.HELM_VALUES_FILES for v in violations)
            )

    def test_missing_helm_values_file_is_a_violation(self) -> None:
        """Deleting / renaming a configured values file must produce a violation,
        not a silent skip — the file is part of the enforcement contract."""
        import os
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            chart_dir = repo_root / "platform/charts/shifter"
            chart_dir.mkdir(parents=True)
            # Create only ONE of the configured values files.
            (repo_root / ADR_GUARD.HELM_VALUES_FILES[0]).write_text(
                "dummy: true\n", encoding="utf-8"
            )

            # Compliant deployment from the shim so the existing one passes.
            compliant_deployment = self.HARDENED_POD
            shim_dir = repo_root / "_shim"
            shim_dir.mkdir()
            shim_path = shim_dir / "helm"
            shim_path.write_text(
                "#!/usr/bin/env bash\n"
                f"cat <<'YAML'\n{compliant_deployment}YAML\n",
                encoding="utf-8",
            )
            shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = f"{shim_dir}:{old_path}"
                rendered, violations = ADR_GUARD._render_chart_for_validation(
                    repo_root, ADR_GUARD.HELM_VALUES_FILES
                )
            finally:
                os.environ["PATH"] = old_path

            missing_file = ADR_GUARD.HELM_VALUES_FILES[1]
            self.assertTrue(
                any(missing_file in v.path and "missing" in v.message for v in violations),
                msg=f"expected violation for missing {missing_file}; got {violations}",
            )

    def test_empty_containers_list_is_a_violation(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
            "      containers: []\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("containers must be a non-empty list" in v.message for v in violations)
            )

    def test_missing_containers_key_is_a_violation(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("containers must be a non-empty list" in v.message for v in violations)
            )

    def test_multi_document_file_scans_only_deployments(self) -> None:
        """A multi-document YAML file with a ConfigMap and a Deployment must only
        flag violations in the Deployment document."""
        body = (
            "apiVersion: v1\n"
            "kind: ConfigMap\n"
            "metadata:\n"
            "  name: cfg\n"
            "---\n"
            + self.HARDENED_POD.replace("allowPrivilegeEscalation: false", "allowPrivilegeEscalation: true")
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/bundle.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("allowPrivilegeEscalation" in v.message for v in violations))


if __name__ == "__main__":
    unittest.main()
