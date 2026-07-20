"""Tests for check_gcp_tf_modules.py.

Run from the repo root:
    python3 -m unittest scripts.check_gcp_tf_modules.test_check_gcp_tf_modules -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from .check_gcp_tf_modules import (
    ALLOWED_DIRECT_RESOURCES,
    check_platform_core_facade,
    check_required_submodule_dirs,
)


class CheckGcpTfModulesTest(unittest.TestCase):
    def test_required_submodule_dirs_exist_in_repo(self) -> None:
        with patch(
            "scripts.check_gcp_tf_modules.check_gcp_tf_modules.GCP_MODULES",
            Path(__file__).resolve().parents[2] / "platform" / "terraform" / "gcp" / "modules",
        ):
            violations = check_required_submodule_dirs()
        self.assertEqual(violations, [])

    def test_platform_core_facade_passes_in_repo(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        platform_core_main = (
            repo_root / "platform" / "terraform" / "gcp" / "modules" / "platform-core" / "main.tf"
        )
        with patch(
            "scripts.check_gcp_tf_modules.check_gcp_tf_modules.PLATFORM_CORE_MAIN",
            platform_core_main,
        ):
            violations = check_platform_core_facade()
        self.assertEqual(violations, [])

    def test_rejects_disallowed_direct_google_resource(self) -> None:
        module_blocks = "\n".join(
            f'module "mod_{idx}" {{\n  source = "{source}"\n}}'
            for idx, source in enumerate(
                [
                    "../project-services",
                    "../portal/vpc",
                    "../range/vpc",
                    "../portal/gcs",
                    "../portal/artifact-registry",
                    "../portal/ingress",
                    "../portal/messaging",
                    "../portal/identity-platform",
                    "../portal/cloud-sql",
                    "../portal/redis",
                    "../portal/secrets",
                    "../portal/iam",
                    "../portal/gke",
                ]
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            main_tf = Path(tmp) / "main.tf"
            main_tf.write_text(
                textwrap.dedent(
                    f"""
                    {module_blocks}

                    resource "google_storage_bucket" "assets" {{
                      name = "example"
                    }}
                    """
                ).lstrip()
            )
            with patch(
                "scripts.check_gcp_tf_modules.check_gcp_tf_modules.PLATFORM_CORE_MAIN",
                main_tf,
            ):
                violations = check_platform_core_facade()
        self.assertEqual(len(violations), 1)
        self.assertIn("google_storage_bucket.assets", str(violations[0]))

    def test_allows_vpc_peering_resources(self) -> None:
        self.assertIn(
            ("google_compute_network_peering", "platform_to_range"),
            ALLOWED_DIRECT_RESOURCES,
        )
        self.assertIn(
            ("google_compute_network_peering", "range_to_platform"),
            ALLOWED_DIRECT_RESOURCES,
        )


if __name__ == "__main__":
    unittest.main()
