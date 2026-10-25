"""Keep SDK publication confined to tested artifacts from the release branch."""

import unittest
from pathlib import Path

import yaml


class AdapterSdkReleaseTests(unittest.TestCase):
    def test_publication_cannot_build_or_check_out_code_with_release_identity(self):
        root = Path(__file__).resolve().parents[3]
        workflow = yaml.safe_load((root / ".github/workflows/adapter-sdk-release.yml").read_text())
        build = workflow["jobs"]["build"]
        publish = workflow["jobs"]["publish"]
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertNotIn("id-token", build.get("permissions", {}))
        self.assertEqual(publish["permissions"], {"actions": "read", "id-token": "write"})
        self.assertEqual(publish["environment"], "adapter-sdk-pypi")
        self.assertEqual(publish["needs"], "build")
        self.assertEqual(publish["if"], "github.ref == 'refs/heads/main'")
        self.assertIn('"$GITHUB_REF" != refs/heads/main', build["steps"][0]["run"])
        download = publish["steps"][0]
        self.assertTrue(download["uses"].startswith("actions/download-artifact@"))
        self.assertEqual(download["with"]["artifact-ids"], "${{ needs.build.outputs.artifact_id }}")
        self.assertFalse(any("checkout@" in step.get("uses", "") for step in publish["steps"]))
        self.assertEqual(len([step for step in publish["steps"] if "run" in step]), 1)
        command = publish["steps"][-1]["run"]
        self.assertIn("uv publish --trusted-publishing always", command)
        self.assertIn("--publish-url https://upload.pypi.org/legacy/", command)
        self.assertNotIn("${{", command)
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
